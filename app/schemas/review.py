from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional


class ReviewResponse(BaseModel):
    review_id: UUID
    ai_decision: str
    effective_decision: str
    confidence: float
    reasoning: str
    model_version: str


class ReviewDetail(BaseModel):
    review_id: UUID
    account_id: UUID
    suitability_score: int
    confidence: float
    ai_decision: str
    effective_decision: str
    reasoning: str
    justification_note: str
    model_version: str
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