from pydantic import BaseModel
from typing import Optional

class AccountCreate(BaseModel):
    age: int
    income: float
    net_worth: float
    risk_tolerance: str
    investment_choice: str
    investment_horizon: int
    notes: Optional[str]