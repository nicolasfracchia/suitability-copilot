from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.account import Account
from app.schemas.account import AccountCreate

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/accounts")
def create_account(account: AccountCreate, db: Session = Depends(get_db)):
    new_account = Account(**account.model_dump())
    db.add(new_account)
    db.commit()
    db.refresh(new_account)
    return {"account_id": new_account.id}