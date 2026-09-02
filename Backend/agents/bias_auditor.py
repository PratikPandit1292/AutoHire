"""
agents/bias_auditor.py
"""

import os
import json
import logging

from groq import Groq, RateLimitError
import time

from agents.resume_screener import groq_rate_limiter, _parse_json_response, MODEL

logger = logging.getLogger("autohire.bias_auditor")

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

BIAS_AUDITOR_PROMPT = """You are a bias auditor reviewing a resume screening decision.
Your job is NOT to re-score the candidate. Your job is to evaluate whether the
screener's stated reasoning is grounded in job-relevant criteria, or whether it
relies on proxy signals unrelated to actual job fitness.

Proxy signals to watch for (not an exhaustive list — also flag other patterns
that seem unrelated to job-relevant skill or experience):
- Institution/school name, used as a stand-in for skill rather than connected to demonstrated ability
- Employment gaps, penalized without evidence they affected capability
- Gendered language (e.g., inconsistent framing of similar traits across candidates)
- Age-indicating signals (e.g., graduation year) used to infer and penalize age

Return ONLY valid JSON:
{{
  "flag_level": "none" | "review" | "high-concern",
  "reasoning": "plain-language explanation of your judgment",
  "proxy_signals_detected": ["..."]
}}

Job Requirements:
{structured_jd}

Candidate Resume:
{resume_text}

Screener Score: {score}
Screener Justification: {justification}
"""

def route_screening_result(flag_level: str) -> str:
    if flag_level == "none":
        return "auto_approved"
    elif flag_level == "review":
        return "needs_review"
    elif flag_level == "high-concern":
        return "blocked"
    else:
        return "needs_review"



def audit_screening(
    structured_jd: dict, resume_text: str, score: float, justification: str, max_retries: int = 4
) -> dict:
    """
    Calls Groq to audit one screening result, using the same shared
    rate limiter and retry/backoff pattern as screen_candidate() in
    resume_screener.py, since both draw from the same Groq account budget.
    """
    delay = 2.0
    last_error = None

    for attempt in range(max_retries):
        try:
            groq_rate_limiter.acquire()

            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": BIAS_AUDITOR_PROMPT.format(
                            structured_jd=json.dumps(structured_jd),
                            resume_text=resume_text,
                            score=score,
                            justification=justification,
                        ),
                    }
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_completion_tokens=600,
            )
            return _parse_json_response(response.choices[0].message.content)

        except RateLimitError as e:
            last_error = e
            logger.warning(
                "Rate limited (attempt %d/%d), backing off %.1fs",
                attempt + 1, max_retries, delay,
            )
            time.sleep(delay)
            delay *= 2

    raise last_error

from concurrent.futures import ThreadPoolExecutor, as_completed
from db.persistence import fetch_screening_results_for_job, save_audit_result, update_routing_status

def _audit_one(row: dict) -> dict:
    audit_result = audit_screening(
        structured_jd=row["structured_requirements"],
        resume_text=row["resume_text"],
        score=row["score"],
        justification=row["justification"],
    )
    audit_id = save_audit_result(row["id"], audit_result)

    routing_status = route_screening_result(audit_result["flag_level"])
    update_routing_status(audit_id, routing_status)

    return {
        "screening_result_id": row["id"],
        "audit_id": audit_id,
        "routing_status": routing_status,
        **audit_result,
    }


def run_batch_audit(job_id: str, max_workers: int = 3) -> dict:
    rows = fetch_screening_results_for_job(job_id)

    results = []
    failed = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_audit_one, row): row["id"] for row in rows}
        for future in as_completed(futures):
            screening_result_id = futures[future]
            try:
                results.append(future.result())
            except Exception as e:
                logger.exception("Audit failed for screening_result_id=%s", screening_result_id)
                failed.append({"screening_result_id": screening_result_id, "reason": str(e)})

    return {"results": results, "failed_audits": failed}