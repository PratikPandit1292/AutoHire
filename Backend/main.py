from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from api.jd import router as jd_router
from api.resumes import router as resumes_router
from api.audit import router as audit_router




app = FastAPI(title="AutoHire API")
app.include_router(jd_router)
app.include_router(resumes_router)
app.include_router(audit_router)

@app.get("/health")
def health_check():
    return {"status": "ok"}