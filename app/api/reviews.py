import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.models.account import Account
from app.models.review import Review
from app.schemas.review import (
    ReviewResponse,
    ReviewDetail,
    OverrideRequest,
    OverrideResponse,
)
from app.services.llm_service import LLMService, MODEL_VERSION
from app.services.policy_engine import apply_policy
from app.services.audit_service import log_event
from app.services import metrics

logger = logging.getLogger(__name__)
router = APIRouter()

# Valid decision values for the override endpoint
VALID_DECISIONS = {"AUTO_APPROVED", "ESCALATED", "REJECTED"}


@router.post("/accounts/{account_id}/review", response_model=ReviewResponse)
def review_account(account_id: str, db: Session = Depends(get_db)):
    """
    Full pipeline: LLM → Policy → Persist → Audit.

    All DB writes (review + audit logs) are in ONE transaction.
    If any step fails — including audit logging — everything rolls back.
    """
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # ── Step 1: LLM Evaluation ─────────────────────────────────────────────
    service = LLMService()
    ai_output = service.evaluate(account)

    # Track LLM failures (fail-safe output has confidence=0.0 and decision=ESCALATE)
    if ai_output.confidence == 0.0 and ai_output.decision == "ESCALATE":
        metrics.increment("llm_failures")

    # ── Step 2: Policy Engine ──────────────────────────────────────────────
    effective_decision = apply_policy(ai_output)

    logger.info(
        "Review pipeline | account=%s ai_decision=%s effective_decision=%s confidence=%.2f",
        account_id,
        ai_output.decision,
        effective_decision,
        ai_output.confidence,
    )

    # ── Step 3: Persist — review + audit logs in one atomic transaction ────
    try:
        review = Review(
            account_id=account.id,
            suitability_score=ai_output.suitability_score,
            confidence=ai_output.confidence,
            ai_decision=ai_output.decision,
            effective_decision=effective_decision,
            ai_reasoning=ai_output.reasoning,
            ai_justification_note=ai_output.justification_note,
            model_version=MODEL_VERSION,
            override_flag=False,
        )
        db.add(review)
        db.flush()  # Assigns review.id without committing so we can reference it below

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
        db.refresh(review)

    except Exception as exc:
        db.rollback()
        logger.error(
            "Review transaction failed for account %s — rolled back: %s",
            account_id,
            exc,
        )
        raise HTTPException(status_code=500, detail="Review processing failed. No data was persisted.")

    # ── Step 4: Metrics ────────────────────────────────────────────────────
    metrics.increment("total_reviews")
    if effective_decision == "AUTO_APPROVED":
        metrics.increment("auto_approved")
    else:
        metrics.increment("escalated")

    return ReviewResponse(
        review_id=review.id,
        ai_decision=review.ai_decision,
        effective_decision=review.effective_decision,
        confidence=float(review.confidence),
        reasoning=review.ai_reasoning,
        model_version=review.model_version,
    )


@router.post("/reviews/{review_id}/override", response_model=OverrideResponse)
def override_review(
    review_id: str,
    body: OverrideRequest,
    db: Session = Depends(get_db),
):
    """
    Human override: change the effective decision without touching AI output.

    AI reasoning is NEVER modified. We only update effective_decision.
    The override event is written to the audit log in the same transaction.
    """
    if body.new_decision not in VALID_DECISIONS:
        raise HTTPException(
            status_code=422,
            detail=f"new_decision must be one of: {sorted(VALID_DECISIONS)}",
        )

    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    old_decision = review.effective_decision

    try:
        review.effective_decision = body.new_decision
        review.override_flag = True
        review.override_reason = body.reason

        log_event(
            db,
            entity_type="review",
            entity_id=review.id,
            event_type="HUMAN_OVERRIDE",
            actor="admin_user",
            old_value={"effective_decision": old_decision},
            new_value={
                "effective_decision": body.new_decision,
                "reason": body.reason,
            },
        )

        db.commit()
        db.refresh(review)

    except Exception as exc:
        db.rollback()
        logger.error("Override transaction failed for review %s: %s", review_id, exc)
        raise HTTPException(status_code=500, detail="Override failed. No data was changed.")

    metrics.increment("overridden")
    logger.info(
        "Human override | review=%s %s → %s",
        review_id,
        old_decision,
        body.new_decision,
    )

    return OverrideResponse(
        review_id=review.id,
        old_decision=old_decision,
        new_decision=review.effective_decision,
        actor="admin_user",
        message=f"Decision updated from {old_decision} to {body.new_decision}. AI reasoning preserved.",
    )


@router.get("/reviews/{review_id}", response_model=ReviewDetail)
def get_review(review_id: str, db: Session = Depends(get_db)):
    """
    Transparency endpoint: full audit record for a review, including
    whether it was human-overridden and the override reason.
    """
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    return ReviewDetail(
        review_id=review.id,
        account_id=review.account_id,
        suitability_score=review.suitability_score,
        confidence=float(review.confidence),
        ai_decision=review.ai_decision,
        effective_decision=review.effective_decision,
        reasoning=review.ai_reasoning,
        justification_note=review.ai_justification_note,
        model_version=review.model_version,
        override_flag=review.override_flag,
        override_reason=review.override_reason,
        created_at=review.created_at,
    )


@router.get("/reviews", response_model=list[ReviewDetail])
def list_reviews(
    decision: Optional[str] = Query(None, description="Filter by effective_decision (e.g. ESCALATED, AUTO_APPROVED)"),
    db: Session = Depends(get_db),
):
    """
    Admin operations endpoint: list reviews with optional decision filter.

    GET /reviews                        → all reviews
    GET /reviews?decision=ESCALATED     → only escalated
    GET /reviews?decision=AUTO_APPROVED → only auto-approved
    """
    query = db.query(Review)
    if decision:
        query = query.filter(Review.effective_decision == decision.upper())
    reviews = query.order_by(Review.created_at.desc()).all()

    return [
        ReviewDetail(
            review_id=r.id,
            account_id=r.account_id,
            suitability_score=r.suitability_score,
            confidence=float(r.confidence),
            ai_decision=r.ai_decision,
            effective_decision=r.effective_decision,
            reasoning=r.ai_reasoning,
            justification_note=r.ai_justification_note,
            model_version=r.model_version,
            override_flag=r.override_flag,
            override_reason=r.override_reason,
            created_at=r.created_at,
        )
        for r in reviews
    ]