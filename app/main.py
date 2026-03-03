from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from redis import Redis

from app.db.session import engine, SessionLocal
from app.db.base import Base
from app.api import accounts, reviews
from app.services import metrics
from app.worker.celery import REDIS_URL

app = FastAPI(title="AI Suitability Copilot")

app.include_router(accounts.router)
app.include_router(reviews.router)


@app.get("/health")
def health():
    """Basic alive check."""
    return {"status": "ok"}


@app.get("/ready")
def ready():
    """Verifies DB and Redis connectivity for production readiness."""
    # Check DB
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database unreachable: {str(e)}")
    finally:
        db.close()

    # Check Redis
    try:
        redis_client = Redis.from_url(REDIS_URL)
        redis_client.ping()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Redis unreachable: {str(e)}")

    return {"status": "ready"}


@app.get("/metrics")
def get_metrics():
    """Expose in-memory pipeline counters for observability."""
    return metrics.get_all()