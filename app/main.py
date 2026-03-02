from fastapi import FastAPI
from app.db.session import engine
from app.db.base import Base
from app.api import accounts, reviews

app = FastAPI(title="AI Suitability Copilot")

app.include_router(accounts.router)
app.include_router(reviews.router)

@app.get("/health")
def health():
    return {"status": "ok"}