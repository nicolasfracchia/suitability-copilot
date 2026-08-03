import logging

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from redis import Redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import accounts, reviews
from app.core.config import settings
from app.db.deps import get_db
from app.db.session import SessionLocal
from app.services import metrics
from app.services.providers import get_provider

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Suitability Copilot")

app.include_router(accounts.router)
app.include_router(reviews.router)


@app.on_event("startup")
def log_active_provider() -> None:
    """Make it unambiguous which reviewer is backing this deployment."""
    try:
        logger.info("Review provider active: %s", get_provider().model_version)
    except Exception as exc:  # pragma: no cover - configuration error
        logger.error("Review provider misconfigured: %s", exc)


@app.get("/health")
def health():
    """Liveness probe: the process is up. No dependency checks."""
    return {"status": "ok"}


@app.get("/ready")
def ready():
    """
    Readiness probe: verifies DB and Redis connectivity.

    Failure detail is logged server-side but never returned — driver errors
    routinely embed the full connection string, including credentials.
    """
    checks = {"database": _check_database(), "redis": _check_redis()}

    if not all(checks.values()):
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "checks": checks},
        )

    return {"status": "ready", "checks": checks}


def _check_database() -> bool:
    db = None
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.exception("Readiness check failed: database unreachable")
        return False
    finally:
        # Guarded: SessionLocal() itself can raise, leaving db unbound.
        if db is not None:
            db.close()


def _check_redis() -> bool:
    try:
        Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2).ping()
        return True
    except Exception:
        logger.exception("Readiness check failed: redis unreachable")
        return False


@app.get("/metrics")
def get_metrics(db: Session = Depends(get_db)):
    """
    Pipeline vitals for operator oversight.

    Derived from the reviews table rather than in-process counters, so the
    numbers are correct across the API and worker processes and survive
    restarts. See app/services/metrics.py.
    """
    return metrics.collect(db)
