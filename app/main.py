from fastapi import FastAPI
from app.db.session import engine
from app.db.base import Base
from app.api import accounts, reviews
from app.services import metrics

app = FastAPI(title="AI Suitability Copilot")

app.include_router(accounts.router)
app.include_router(reviews.router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics")
def get_metrics():
    """Expose in-memory pipeline counters for observability."""
    return metrics.get_all()