from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


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
    created_at: datetime

    model_config = {"from_attributes": True}