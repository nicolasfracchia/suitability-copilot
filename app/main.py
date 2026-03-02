from fastapi import FastAPI
from app.db.session import engine
from app.db.base import Base

app = FastAPI(title="AI Suitability Copilot")

@app.get("/health")
def health():
    return {"status": "ok"}