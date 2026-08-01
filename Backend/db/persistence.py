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


def save_structured_jd(job_id: str, jd_text: str, structured_jd: dict):
    """
    Persists the JD Analyzer's output onto the `jobs` row.
    Assumes `jobs` has a `raw_text` column and a `structured_data` (JSONB) column.
    Adjust column names if your Phase 1 schema differs.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                SET raw_jd_text = %s,
                structured_requirements = %s
                WHERE id = %s
                """,
                (jd_text, json.dumps(structured_jd), job_id),
            )
        conn.commit()
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