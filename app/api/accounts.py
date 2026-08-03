import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.models.account import Account
from app.models.review import Review
from app.schemas.account import AccountCreate
from app.services.audit_service import log_event
from app.worker.tasks import process_review

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/accounts")
def create_account(account: AccountCreate, db: Session = Depends(get_db)):
    """
    Creates a new account and automatically triggers a background suitability review.
    Implemented as a fast-return endpoint for production scale.
    """
    try:
        # 1. Create Account
        new_account = Account(**account.model_dump())
        db.add(new_account)
        db.flush()  # Get the account.id without committing yet

        # 2. Create Review entry in PENDING status (Idempotency foundation)
        new_review = Review(account_id=new_account.id, status="PENDING")
        db.add(new_review)
        db.flush()

        # 3. Audit intake in the same transaction as the rows it describes.
        log_event(
            db,
            entity_type="account",
            entity_id=new_account.id,
            event_type="ACCOUNT_CREATED",
            actor="system",
            new_value={
                "account_id": str(new_account.id),
                "review_id": str(new_review.id),
                "status": new_review.status,
            },
        )

        # 4. Commit the transaction
        db.commit()
        db.refresh(new_account)
        db.refresh(new_review)
    except Exception:
        db.rollback()
        logger.exception("Account creation failed; no data was written")
        raise HTTPException(status_code=500, detail="Account creation failed.")

    # 5. Queue the review job only after the transaction is durable, so the
    #    worker can never observe a review row that was rolled back.
    process_review.delay(str(new_review.id))

    return {
        "account_id": new_account.id,
        "review_id": new_review.id,
        "status": new_review.status,
    }
