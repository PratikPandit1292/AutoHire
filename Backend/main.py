from fastapi import FastAPI

app = FastAPI(title="AutoHire API")

@app.get("/health")
def health_check():
    return {"status": "ok"}