# api/resumes.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agents.resume_screener import run_screening, store_resume_embedding

router = APIRouter()


class ScreenRequest(BaseModel):
    job_id: str


class EmbedResumeRequest(BaseModel):
    resume_text: str


@router.post("/resumes/embed")
def embed_resume_endpoint(payload: EmbedResumeRequest):
    """Call this once per candidate after upload, before running /resumes/screen."""
    candidate_id = store_resume_embedding(payload.resume_text)
    return {"status": "embedded", "candidate_id": candidate_id}


@router.post("/resumes/screen")
def screen_endpoint(payload: ScreenRequest):
    try:
        return run_screening(payload.job_id)
    except Exception:
        raise HTTPException(status_code=502, detail="Resume screening run failed")