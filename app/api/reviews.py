import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.models.account import Account
from app.models.review import Review
from app.schemas.review import ReviewResponse, ReviewDetail
from app.services.llm_service import LLMService, MODEL_VERSION
from app.services.policy_engine import apply_policy

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/accounts/{account_id}/review", response_model=ReviewResponse)
def review_account(account_id: str, db: Session = Depends(get_db)):
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Step 1 — LLM evaluation (always returns AIReviewOutput; fail-safe on error)
    service = LLMService()
    ai_output = service.evaluate(account)

    # Step 2 — Policy engine determines the effective decision
    effective_decision = apply_policy(ai_output)

    logger.info(
        "Review complete | account=%s ai_decision=%s effective_decision=%s confidence=%.2f",
        account_id,
        ai_output.decision,
        effective_decision,
        ai_output.confidence,
    )

    # Step 3 — Persist review with both AI and policy decisions
    review = Review(
        account_id=account.id,
        suitability_score=ai_output.suitability_score,
        confidence=ai_output.confidence,
        ai_decision=ai_output.decision,
        effective_decision=effective_decision,
        ai_reasoning=ai_output.reasoning,
        ai_justification_note=ai_output.justification_note,
        model_version=MODEL_VERSION,
    )
    db.add(review)
    db.commit()
    db.refresh(review)

    return ReviewResponse(
        review_id=review.id,
        ai_decision=review.ai_decision,
        effective_decision=review.effective_decision,
        confidence=float(review.confidence),
        reasoning=review.ai_reasoning,
        model_version=review.model_version,
    )


@router.get("/reviews/{review_id}", response_model=ReviewDetail)
def get_review(review_id: str, db: Session = Depends(get_db)):
    """
    Transparency endpoint: returns the full audit record for a review,
    including raw AI reasoning, AI decision, effective policy decision,
    confidence score, and model version.
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
        created_at=review.created_at,
    )