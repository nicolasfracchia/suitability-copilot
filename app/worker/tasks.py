import logging
import asyncio
from celery.utils.log import get_task_logger
from app.worker.celery import celery
from app.db.session import SessionLocal
from app.models.account import Account
from app.models.review import Review
from app.services.llm_service import LLMService, MODEL_VERSION
from app.services.policy_engine import apply_policy
from app.services.audit_service import log_event
from app.services import metrics

logger = get_task_logger(__name__)

@celery.task(bind=True, max_retries=3)
def process_review(self, review_id: str):
    """
    Background Task: Executes the full AI suitability review pipeline.
    
    Flow:
    1. Fetch Review from DB
    2. Run Async LLM Evaluation
    3. Run Policy Engine
    4. Update Review & Write Audit Logs
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

        # ── Step 1: Async LLM Evaluation ───────────────────────────────────
        service = LLMService()
        # Run the async evaluation in the sync worker thread
        ai_output = asyncio.run(service.evaluate(account))

        # Track LLM failures (fail-safe output has confidence=0.0 and decision=ESCALATE)
        if ai_output.confidence == 0.0 and ai_output.decision == "ESCALATE":
            metrics.increment("llm_failures")

        # ── Step 2: Policy Engine ──────────────────────────────────────────
        effective_decision = apply_policy(ai_output)

        logger.info(
            f"Background Review | review={review_id} ai_decision={ai_output.decision} effective_decision={effective_decision}"
        )

        # ── Step 3: Update Review ──────────────────────────────────────────
        review.suitability_score = ai_output.suitability_score
        review.confidence = ai_output.confidence
        review.ai_decision = ai_output.decision
        review.effective_decision = effective_decision
        review.ai_reasoning = ai_output.reasoning
        review.ai_justification_note = ai_output.justification_note
        review.model_version = MODEL_VERSION
        review.status = "COMPLETED"

        # ── Step 4: Audit Logs ─────────────────────────────────────────────
        # Audit: AI Evaluation
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
                "model_version": MODEL_VERSION,
            },
        )

        # Audit: Policy Application
        log_event(
            db,
            entity_type="review",
            entity_id=review.id,
            event_type="POLICY_APPLIED",
            actor="system",
            old_value={"ai_decision": ai_output.decision},
            new_value={"effective_decision": effective_decision},
        )

        db.commit()

        # ── Step 5: Metrics ────────────────────────────────────────────────
        metrics.increment("total_reviews")
        if effective_decision == "AUTO_APPROVED":
            metrics.increment("auto_approved")
        else:
            metrics.increment("escalated")

    except Exception as exc:
        db.rollback()
        logger.warning(f"Task failed for review {review_id}, checking for retry: {exc}")
        
        # If we have retries left, trigger one
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=5)
        else:
            # Final failure after 3 retries
            logger.error(f"Max retries reached for review {review_id}")
            review = db.query(Review).filter(Review.id == review_id).first()
            if review:
                review.status = "FAILED"
                db.commit()
                
                # Audit the failure
                log_event(
                    db,
                    entity_type="review",
                    entity_id=review.id,
                    event_type="REVIEW_FAILED",
                    actor="system",
                    new_value={"error": str(exc), "retries": self.max_retries},
                )
                db.commit()
    finally:
        db.close()
