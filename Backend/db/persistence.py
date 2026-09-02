"""
db/persistence.py

Thin persistence layer for Phase 2. Assumes the `jobs`, `candidates`,
and `screening_results` tables already exist from Phase 1's schema.

Adjust connection details to match how you set up PostgreSQL in Phase 1
(this assumes a DATABASE_URL env var — swap for your existing db.py
connection helper if you already have one).
"""

import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor


def get_connection():
    return psycopg2.connect(os.getenv("DATABASE_URL"))


def insert_job(jd_text: str, structured_jd: dict) -> int:
    """
    Inserts a new job row with its analyzed structured data and
    returns the auto-generated integer id.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO jobs (raw_jd_text, structured_requirements)
                VALUES (%s, %s)
                RETURNING id
                """,
                (jd_text, json.dumps(structured_jd)),
            )
            job_id = cur.fetchone()[0]
        conn.commit()
        return job_id
    finally:
        conn.close()

def insert_candidate(resume_text: str) -> int:
    """
    Inserts a new candidate row and returns the auto-generated integer id.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO candidates (resume_text) VALUES (%s) RETURNING id",
                (resume_text,),
            )
            candidate_id = cur.fetchone()[0]
        conn.commit()
        return candidate_id
    finally:
        conn.close()


def fetch_resume_text(candidate_id: str) -> str:
    """
    Pulls the raw resume text for a candidate from PostgreSQL.
    Assumes `candidates` has an `id` and a `resume_text` column.
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT resume_text FROM candidates WHERE id = %s",
                (candidate_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"No candidate found with id={candidate_id}")
            return row["resume_text"]
    finally:
        conn.close()


def save_screening_result(job_id: str, candidate_id: str, result: dict):
    """
    Persists one Resume Screener result into `screening_results`.
    Assumes columns: job_id, candidate_id, score, justification.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
    """
    INSERT INTO screening_results (job_id, candidate_id, score, justification)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (job_id, candidate_id)
    DO UPDATE SET score = EXCLUDED.score,
                  justification = EXCLUDED.justification
    """,
    (job_id, candidate_id, result["score"], json.dumps(result["justification"])),
)
        conn.commit()
    finally:
        conn.close()

def fetch_job(job_id: str) -> dict:
    """
    Fetches the raw JD text and structured requirements for a job.
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT raw_jd_text, structured_requirements FROM jobs WHERE id = %s",
                (job_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"No job found with id={job_id}")
            return row
    finally:
        conn.close()

def fetch_screening_result(screening_result_id: str) -> dict:
    """
    Fetches everything the Bias Auditor needs for one screening result:
    the score/justification being audited, plus the candidate's resume
    and the job's structured requirements, via a join.
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT sr.id, sr.job_id, sr.candidate_id, sr.score, sr.justification,
                       c.resume_text, j.structured_requirements
                FROM screening_results sr
                JOIN candidates c ON c.id = sr.candidate_id
                JOIN jobs j ON j.id = sr.job_id
                WHERE sr.id = %s
                """,
                (screening_result_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"No screening_result found with id={screening_result_id}")
            return row
    finally:
        conn.close()

def update_routing_status(audit_flag_id: int, routing_status: str):
    """
    Updates the routing_status on an audit_flags row after a bias
    audit completes, based on the flag_level routing decision.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE audit_flags
                SET routing_status = %s
                WHERE id = %s
                """,
                (routing_status, audit_flag_id),
            )
        conn.commit()
    finally:
        conn.close()


def save_audit_result(screening_result_id: str, audit_result: dict) -> int:
    """
    Persists one Bias Auditor result into audit_flags, returns its id.
    Upserts on screening_result_id so re-running an audit updates the
    existing row instead of creating a duplicate.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_flags (screening_result_id, flag_level, reasoning, proxy_signals)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (screening_result_id)
                DO UPDATE SET flag_level = EXCLUDED.flag_level,
                              reasoning = EXCLUDED.reasoning,
                              proxy_signals = EXCLUDED.proxy_signals
                RETURNING id
                """,
                (
                    screening_result_id,
                    audit_result["flag_level"],
                    audit_result["reasoning"],
                    json.dumps(audit_result["proxy_signals_detected"]),
                ),
            )
            audit_id = cur.fetchone()[0]
        conn.commit()
        return audit_id
    finally:
        conn.close()


def fetch_review_queue(job_id: str) -> list[dict]:
    """
    Fetches all candidates for a job whose bias audit routing_status
    is needs_review or blocked — the queue a recruiter needs to act on.
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT c.id AS candidate_id, sr.id AS screening_result_id,
                       sr.score, af.flag_level, af.reasoning, af.proxy_signals,
                       af.routing_status
                FROM audit_flags af
                JOIN screening_results sr ON sr.id = af.screening_result_id
                JOIN candidates c ON c.id = sr.candidate_id
                WHERE sr.job_id = %s
                  AND af.routing_status IN ('needs_review', 'blocked')
                ORDER BY af.flag_level = 'high-concern' DESC, af.id DESC
                """,
                (job_id,),
            )
            return cur.fetchall()
    finally:
        conn.close()

def fetch_screening_results_for_job(job_id: str) -> list[dict]:
    """
    Fetches all screening_results rows for a given job, joined with
    candidate resume text and job requirements — for batch auditing.
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT sr.id, sr.job_id, sr.candidate_id, sr.score, sr.justification,
                       c.resume_text, j.structured_requirements
                FROM screening_results sr
                JOIN candidates c ON c.id = sr.candidate_id
                JOIN jobs j ON j.id = sr.job_id
                WHERE sr.job_id = %s
                """,
                (job_id,),
            )
            return cur.fetchall()
    finally:
        conn.close()