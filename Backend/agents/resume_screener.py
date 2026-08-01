"""
agents/resume_screener.py

Two-stage screener:
  1. Fast pre-filter with ChromaDB (narrows N resumes down to top-K by
     semantic similarity to the JD).
  2. Deep reasoning with Groq's free API (Llama 3.3 70B), run only on
     the narrowed set.
"""

import os
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import chromadb
from groq import Groq

from db.persistence import fetch_resume_text, save_screening_result, insert_candidate, fetch_job
logger = logging.getLogger("autohire.resume_screener")

chroma_client = chromadb.PersistentClient(path="./chroma_data")
collection = chroma_client.get_or_create_collection(name="resume_embeddings")

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

MODEL = "llama-3.3-70b-versatile"

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


from db.persistence import fetch_resume_text, save_screening_result, insert_candidate

def store_resume_embedding(resume_text: str) -> str:
    """
    Inserts the resume into Postgres (source of truth for resume text),
    then adds the embedding to ChromaDB using the same id, so both stores
    always agree on candidate identity.
    """
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


def screen_candidate(structured_jd: dict, resume_text: str) -> dict:
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


def _screen_one(job_id: str, candidate_id: str, structured_jd: dict) -> dict:
    resume_text = fetch_resume_text(candidate_id)
    result = screen_candidate(structured_jd, resume_text)
    result["candidate_id"] = candidate_id
    save_screening_result(job_id, candidate_id, result)
    return result


def run_screening(job_id: str, k: int = 20, max_workers: int = 3) -> list[dict]:
    job = fetch_job(job_id)
    jd_text = job["raw_jd_text"]
    structured_jd = job["structured_requirements"]
    """
    Narrows the candidate pool with ChromaDB, then screens the narrowed set
    with Groq. max_workers is kept modest (3) since Groq's free tier has a
    per-minute request cap -- too much concurrency will trip 429s faster
    than it saves time.
    """
    top_candidate_ids = get_top_candidates(jd_text, k=k)

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_screen_one, job_id, candidate_id, structured_jd): candidate_id
            for candidate_id in top_candidate_ids
        }
        for future in as_completed(futures):
            candidate_id = futures[future]
            try:
                results.append(future.result())
            except Exception:
                logger.exception("Screening failed for candidate_id=%s", candidate_id)

    return sorted(results, key=lambda r: r["score"], reverse=True)