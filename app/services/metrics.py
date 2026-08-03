"""
Pipeline metrics, derived from the database.

These were previously in-process counters. That worked while the review ran
inside the API request, but broke silently when the pipeline moved to Celery:
the worker incremented counters in its own memory, so the API's /metrics
endpoint reported zero for every pipeline counter no matter how many reviews
had been processed.

Deriving them from the reviews table instead means the numbers are correct
across processes, survive restarts, and agree with the SQL drift queries in
docs/model_versioning_strategy.md — the reviews table is the source of truth,
so there is no second thing to keep in sync.
"""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.review import Review

COMPLETED = Review.status == "COMPLETED"


def collect(db: Session) -> dict:
    """Aggregate pipeline vitals in a single query."""
    row = db.query(
        func.count(Review.id).label("total"),
        func.count(Review.id).filter(COMPLETED).label("completed"),
        func.count(Review.id).filter(Review.status == "PENDING").label("pending"),
        func.count(Review.id).filter(Review.status == "FAILED").label("failed"),
        func.count(Review.id)
        .filter(COMPLETED, Review.effective_decision == "AUTO_APPROVED")
        .label("auto_approved"),
        func.count(Review.id)
        .filter(COMPLETED, Review.effective_decision == "ESCALATED")
        .label("escalated"),
        func.count(Review.id).filter(Review.override_flag.is_(True)).label("overridden"),
        # The fail-safe signature: confidence pinned to exactly 0.0 with an
        # ESCALATE recommendation means the provider call did not succeed.
        func.count(Review.id)
        .filter(COMPLETED, Review.confidence == 0, Review.ai_decision == "ESCALATE")
        .label("fail_safe_escalations"),
    ).one()

    completed = row.completed or 0
    llm_failures = (row.fail_safe_escalations or 0) + (row.failed or 0)

    return {
        "total_reviews": row.total or 0,
        "completed": completed,
        "pending": row.pending or 0,
        "failed": row.failed or 0,
        "auto_approved": row.auto_approved or 0,
        "escalated": row.escalated or 0,
        "overridden": row.overridden or 0,
        "llm_failures": llm_failures,
        # The two ratios a human operator actually watches for drift.
        "auto_approval_rate": _ratio(row.auto_approved, completed),
        "override_rate": _ratio(row.overridden, completed),
    }


def _ratio(numerator: int | None, denominator: int) -> float | None:
    """None rather than 0.0 when there is nothing to divide — an unknown rate
    is not the same as a rate of zero, and operators alert on these."""
    if not denominator:
        return None
    return round((numerator or 0) / denominator, 4)
