from pydantic import BaseModel
from uuid import UUID

class ReviewResponse(BaseModel):
    review_id: UUID
    decision: str
    confidence: float