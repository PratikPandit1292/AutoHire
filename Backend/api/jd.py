# api/jd.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agents.jd_analyzer import analyze_jd
from db.persistence import insert_job

router = APIRouter()


class JDAnalyzeRequest(BaseModel):
    jd_text: str


@router.post("/jd/analyze")
def jd_analyze_endpoint(payload: JDAnalyzeRequest):
    try:
        structured = analyze_jd(payload.jd_text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=502, detail="JD Analyzer failed to produce valid output")

    job_id = insert_job(payload.jd_text, structured)
    return {"job_id": job_id, "structured_requirements": structured}