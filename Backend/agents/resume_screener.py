"""
agents/resume_screener.py
"""

import os
import json
import logging
import time
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed

import chromadb
from groq import Groq, RateLimitError

from db.persistence import fetch_resume_text, save_screening_result, insert_candidate, fetch_job

logger = logging.getLogger("autohire.resume_screener")

chroma_client = chromadb.PersistentClient(path="./chroma_data")
collection = chroma_client.get_or_create_collection(name="resume_embeddings")

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

MODEL = "llama-3.3-70b-versatile"


class RateLimiter:
    """
    Shared, thread-safe sliding-window rate limiter.

    Groq's free tier caps requests-per-minute (RPM) at the account level,
    not per-request — so previously, every /resumes/screen call spun up
    its own ThreadPoolExecutor unaware of any other in-flight request,
    and all of them independently blew through the shared Groq limit.

    This limiter is a single module-level instance shared by every
    thread across every request, so all Groq calls in the whole process
    respect one real budget instead of racing each other.
    """

    def __init__(self, max_calls: int, period_seconds: float = 60.0):
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self._calls = deque()
        self._lock = threading.Lock()

    def acquire(self):
        while True:
            with self._lock:
                now = time.monotonic()
                # Drop timestamps older than the window
                while self._calls and now - self._calls[0] >= self.period_seconds:
                    self._calls.popleft()

                if len(self._calls) < self.max_calls:
                    self._calls.append(now)
                    return

                # Window is full — figure out how long until the oldest
                # call ages out, and sleep just that long.
                sleep_for = self.period_seconds - (now - self._calls[0])

            time.sleep(max(sleep_for, 0.05))


# Cap at 25 (not 30) to leave headroom below Groq's actual RPM limit,
# since other traffic (e.g. JD analysis calls) may share the same key.
groq_rate_limiter = RateLimiter(max_calls=25, period_seconds=60.0)

SCREENER_PROMPT = """You are a resume screening assistant.
Given structured job requirements and a candidate's resume, score the fit from 0-100.

Return ONLY valid JSON:
{{
  "score": 0-100,
  "justification": "plain-language explanation grounded in specific resume content and JD requirements"
}}

Job Requirements:
{structured_jd}

Candidate Resume:
{resume_text}
"""


def store_resume_embedding(resume_text: str) -> str:
    candidate_id = insert_candidate(resume_text)
    collection.add(documents=[resume_text], ids=[str(candidate_id)])
    return str(candidate_id)


def get_top_candidates(jd_text: str, k: int = 20) -> list[str]:
    results = collection.query(query_texts=[jd_text], n_results=k)
    return results["ids"][0]


def _parse_json_response(raw_output: str) -> dict:
    try:
        return json.loads(raw_output)
    except json.JSONDecodeError:
        cleaned = raw_output.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.error("Resume Screener returned unparseable output: %r", raw_output)
            raise


def screen_candidate(structured_jd: dict, resume_text: str, max_retries: int = 4) -> dict:
    """
    Calls Groq with retry-on-429 using exponential backoff, since the free
    tier's TPM cap gets hit routinely under concurrent load.
    """
    delay = 2.0
    last_error = None

    for attempt in range(max_retries):
        try:
            # Block here (not inside the try/except) until a slot in the
            # shared rate limit window is free. This is what actually
            # prevents concurrent requests from blowing through Groq's
            # RPM limit in the first place — the retry/backoff below is
            # now a safety net, not the primary defense.
            groq_rate_limiter.acquire()

            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": SCREENER_PROMPT.format(
                            structured_jd=json.dumps(structured_jd), resume_text=resume_text
                        ),
                    }
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_completion_tokens=500,
            )
            return _parse_json_response(response.choices[0].message.content)

        except RateLimitError as e:
            last_error = e
            logger.warning(
                "Rate limited (attempt %d/%d), backing off %.1fs",
                attempt + 1, max_retries, delay,
            )
            time.sleep(delay)
            delay *= 2  # exponential backoff: 2s, 4s, 8s, 16s

    raise last_error


def _screen_one(job_id: str, candidate_id: str, structured_jd: dict) -> dict:
    resume_text = fetch_resume_text(candidate_id)
    result = screen_candidate(structured_jd, resume_text)
    result["candidate_id"] = candidate_id
    save_screening_result(job_id, candidate_id, result)
    return result


def run_screening(job_id: str, k: int = 20, max_workers: int = 3) -> dict:
    job = fetch_job(job_id)
    jd_text = job["raw_jd_text"]
    structured_jd = job["structured_requirements"]

    top_candidate_ids = get_top_candidates(jd_text, k=k)

    results = []
    failed = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_screen_one, job_id, candidate_id, structured_jd): candidate_id
            for candidate_id in top_candidate_ids
        }
        for future in as_completed(futures):
            candidate_id = futures[future]
            try:
                results.append(future.result())
            except Exception as e:
                logger.exception("Screening failed for candidate_id=%s", candidate_id)
                failed.append({"candidate_id": candidate_id, "reason": str(e)})

    return {
        "results": sorted(results, key=lambda r: r["score"], reverse=True),
        "failed_candidates": failed,
    }