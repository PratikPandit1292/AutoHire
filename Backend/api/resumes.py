# api/resumes.py
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from pypdf import PdfReader
import io

from agents.resume_screener import run_screening, store_resume_embedding

router = APIRouter()


class ScreenRequest(BaseModel):
    job_id: str


def extract_text_from_pdf(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if not text.strip():
        raise ValueError("No extractable text found in PDF")
    return text


@router.post("/resumes/embed")
async def embed_resume_endpoint(file: UploadFile = File(...)):
    """Call this once per candidate after upload, before running /resumes/screen."""
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    file_bytes = await file.read()
    try:
        resume_text = extract_text_from_pdf(file_bytes)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    candidate_id = store_resume_embedding(resume_text)
    return {"status": "embedded", "candidate_id": candidate_id}


@router.post("/resumes/screen")
def screen_endpoint(payload: ScreenRequest):
    try:
        return run_screening(payload.job_id)
    except Exception:
        raise HTTPException(status_code=502, detail="Resume screening run failed")