from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional


class ReviewResponse(BaseModel):
    review_id: UUID
    status: str
    ai_decision: Optional[str] = None
    effective_decision: Optional[str] = None
    confidence: Optional[float] = None
    reasoning: Optional[str] = None
    model_version: Optional[str] = None


class ReviewDetail(BaseModel):
    review_id: UUID
    account_id: UUID
    status: str
    suitability_score: Optional[int] = None
    confidence: Optional[float] = None
    ai_decision: Optional[str] = None
    effective_decision: Optional[str] = None
    reasoning: Optional[str] = None
    justification_note: Optional[str] = None
    model_version: Optional[str] = None
    override_flag: bool
    override_reason: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class OverrideRequest(BaseModel):
    new_decision: str
    reason: str


class OverrideResponse(BaseModel):
    review_id: UUID
    old_decision: str
    new_decision: str
    actor: str
    message: str