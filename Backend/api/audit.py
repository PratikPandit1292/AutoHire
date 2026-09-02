# api/audit.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agents.bias_auditor import run_batch_audit

from db.persistence import fetch_review_queue


router = APIRouter()


class BatchAuditRequest(BaseModel):
    job_id: str


@router.post("/audit/screen-batch")
def audit_batch_endpoint(payload: BatchAuditRequest):
    try:
        return run_batch_audit(payload.job_id)
    except Exception:
        raise HTTPException(status_code=502, detail="Batch bias audit run failed")



@router.get("/review-queue")
def review_queue_endpoint(job_id: str):
    try:
        return fetch_review_queue(job_id)
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to fetch review queue")