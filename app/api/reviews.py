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
from app.worker.tasks import process_review

logger = logging.getLogger(__name__)
router = APIRouter()

# Valid decision values for the override endpoint
VALID_DECISIONS = {"AUTO_APPROVED", "ESCALATED", "REJECTED"}


@router.post("/accounts/{account_id}/review", response_model=ReviewResponse)
def trigger_review(account_id: str, db: Session = Depends(get_db)):
    """
    Triggers a background review for an existing account.
    
    🛡 Idempotency Protection:
    If a review is already PENDING or COMPLETED for this account, returns the existing record.
    """
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Check for existing review (Idempotency)
    existing_review = db.query(Review).filter(Review.account_id == account_id).order_by(Review.created_at.desc()).first()
    if existing_review and existing_review.status in ["PENDING", "COMPLETED"]:
        logger.info(f"Returning existing review {existing_review.id} for account {account_id} (Idempotency)")
        return ReviewResponse(
            review_id=existing_review.id,
            status=existing_review.status,
            ai_decision=existing_review.ai_decision,
            effective_decision=existing_review.effective_decision,
            confidence=float(existing_review.confidence) if existing_review.confidence else None,
            reasoning=existing_review.ai_reasoning,
            model_version=existing_review.model_version,
        )

    # Create new PENDING review
    review = Review(
        account_id=account.id,
        status="PENDING"
    )
    db.add(review)
    db.commit()
    db.refresh(review)

    # Queue background task
    process_review.delay(str(review.id))

    return ReviewResponse(
        review_id=review.id,
        status=review.status
    )


@router.post("/reviews/{review_id}/override", response_model=OverrideResponse)
def override_review(
    review_id: str,
    body: OverrideRequest,
    db: Session = Depends(get_db),
):
    """
    Human override: change the effective decision without touching AI output.
    Only works for COMPLETED reviews.
    """
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    
    if review.status != "COMPLETED":
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot override a review in state '{review.status}'. It must be COMPLETED."
        )

    if body.new_decision not in VALID_DECISIONS:
        raise HTTPException(
            status_code=422,
            detail=f"new_decision must be one of: {sorted(VALID_DECISIONS)}",
        )

    old_decision = review.effective_decision

    try:
        from app.services.audit_service import log_event
        from app.services import metrics
        
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
        metrics.increment("overridden")

    except Exception as exc:
        db.rollback()
        logger.error("Override transaction failed for review %s: %s", review_id, exc)
        raise HTTPException(status_code=500, detail="Override failed. No data was changed.")

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
    Transparency endpoint: returns the review record, supporting polling for async status.
    """
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    return ReviewDetail(
        review_id=review.id,
        account_id=review.account_id,
        status=review.status,
        suitability_score=review.suitability_score,
        confidence=float(review.confidence) if review.confidence else None,
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
    decision: Optional[str] = Query(None, description="Filter by effective_decision"),
    status: Optional[str] = Query(None, description="Filter by status (PENDING, COMPLETED, FAILED)"),
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
    if status:
        query = query.filter(Review.status == status.upper())
    
    reviews = query.order_by(Review.created_at.desc()).all()

    return [
        ReviewDetail(
            review_id=r.id,
            account_id=r.account_id,
            status=r.status,
            suitability_score=r.suitability_score,
            confidence=float(r.confidence) if r.confidence else None,
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