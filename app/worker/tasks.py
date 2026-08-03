import asyncio

from celery.utils.log import get_task_logger

from app.db.session import SessionLocal
from app.models.account import Account
from app.models.review import Review
from app.services.audit_service import log_event
from app.services.llm_service import LLMService
from app.services.policy_engine import apply_policy
from app.worker.celery import celery

logger = get_task_logger(__name__)


@celery.task(bind=True, max_retries=3)
def process_review(self, review_id: str):
    """
    Background Task: Executes the full AI suitability review pipeline.

    Flow:
    1. Fetch Review from DB
    2. Run the configured review provider (OpenAI or deterministic stub)
    3. Run Policy Engine
    4. Update Review & Write Audit Logs in one transaction
    5. Handle Retries/Failures
    """
    db = SessionLocal()
    try:
        review = db.query(Review).filter(Review.id == review_id).first()
        if not review:
            logger.error(f"Review {review_id} not found")
            return

        # Skip if already processed (Idempotency)
        if review.status != "PENDING":
            logger.info(f"Review {review_id} already in status {review.status}")
            return

        account = db.query(Account).filter(Account.id == review.account_id).first()
        if not account:
            logger.error(f"Account {review.account_id} not found for review {review_id}")
            review.status = "FAILED"
            db.commit()
            return

        # ── Step 1: Evaluation ─────────────────────────────────────────────
        service = LLMService()
        # The provider API is async; the Celery worker is sync.
        ai_output = asyncio.run(service.evaluate(account))
        model_version = service.model_version

        # ── Step 2: Policy Engine ──────────────────────────────────────────
        effective_decision = apply_policy(ai_output)

        logger.info(
            f"Background Review | review={review_id} model={model_version} "
            f"ai_decision={ai_output.decision} effective_decision={effective_decision}"
        )

        # ── Step 3: Update Review ──────────────────────────────────────────
        review.suitability_score = ai_output.suitability_score
        review.confidence = ai_output.confidence
        review.ai_decision = ai_output.decision
        review.effective_decision = effective_decision
        review.ai_reasoning = ai_output.reasoning
        review.ai_justification_note = ai_output.justification_note
        review.model_version = model_version
        review.status = "COMPLETED"

        # ── Step 4: Audit Logs ─────────────────────────────────────────────
        # Same transaction as the update above: if the audit write fails, the
        # review update rolls back with it.
        log_event(
            db,
            entity_type="review",
            entity_id=review.id,
            event_type="AI_EVALUATED",
            actor="system",
            new_value={
                "suitability_score": ai_output.suitability_score,
                "confidence": float(ai_output.confidence),
                "decision": ai_output.decision,
                "reasoning": ai_output.reasoning,
                "justification_note": ai_output.justification_note,
                "model_version": model_version,
            },
        )

        log_event(
            db,
            entity_type="review",
            entity_id=review.id,
            event_type="POLICY_APPLIED",
            actor="system",
            old_value={"ai_decision": ai_output.decision},
            new_value={"effective_decision": effective_decision},
        )

        # Persists the review update and both audit rows together. Pipeline
        # metrics are derived from these rows at read time, so there is no
        # separate counter to increment here.
        db.commit()

    except Exception as exc:
        db.rollback()
        logger.warning(f"Task failed for review {review_id}, checking for retry: {exc}")

        # If we have retries left, trigger one
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=5)

        # Final failure after the retry budget is exhausted.
        logger.error(f"Max retries reached for review {review_id}")
        _mark_failed(db, review_id, exc, self.max_retries)
    finally:
        db.close()


def _mark_failed(db, review_id: str, exc: Exception, retries: int) -> None:
    """
    Record terminal failure. The status change and its audit row share one
    transaction — a FAILED review must never exist without an audit trail.
    """
    try:
        review = db.query(Review).filter(Review.id == review_id).first()
        if not review:
            return

        review.status = "FAILED"
        log_event(
            db,
            entity_type="review",
            entity_id=review.id,
            event_type="REVIEW_FAILED",
            actor="system",
            new_value={"error": str(exc), "retries": retries},
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "Could not record terminal failure for review %s; it remains PENDING for reprocessing.",
            review_id,
        )
