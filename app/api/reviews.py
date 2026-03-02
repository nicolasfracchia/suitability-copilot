from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.account import Account
from app.models.review import Review
from app.schemas.review import ReviewResponse
from app.services.mock_ai import evaluate_account

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/accounts/{account_id}/review", response_model=ReviewResponse)
def review_account(account_id: str, db: Session = Depends(get_db)):
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    ai_result = evaluate_account(account)

    review = Review(
        account_id=account.id,
        suitability_score=ai_result["suitability_score"],
        confidence=ai_result["confidence"],
        decision=ai_result["decision"],
        ai_reasoning=ai_result["reasoning"],
        ai_justification_note=ai_result["justification_note"],
        model_version=ai_result["model_version"],
    )

    db.add(review)
    db.commit()
    db.refresh(review)

    return {
        "review_id": review.id,
        "decision": review.decision,
        "confidence": review.confidence
    }