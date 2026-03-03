from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.models.account import Account
from app.models.review import Review
from app.schemas.account import AccountCreate
from app.worker.tasks import process_review

router = APIRouter()


@router.post("/accounts")
def create_account(account: AccountCreate, db: Session = Depends(get_db)):
    """
    Creates a new account and automatically triggers a background suitability review.
    Implemented as a fast-return endpoint for production scale.
    """
    # 1. Create Account
    new_account = Account(**account.model_dump())
    db.add(new_account)
    db.flush() # Get the account.id without committing yet

    # 2. Create Review entry in PENDING status (Idempotency foundation)
    new_review = Review(
        account_id=new_account.id,
        status="PENDING"
    )
    db.add(new_review)
    
    # 3. Commit the transaction
    db.commit()
    db.refresh(new_account)
    db.refresh(new_review)

    # 4. Queue the AI review job
    process_review.delay(str(new_review.id))

    return {
        "account_id": new_account.id,
        "review_id": new_review.id,
        "status": new_review.status
    }