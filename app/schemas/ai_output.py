from pydantic import BaseModel, Field
from typing import Literal


class AIReviewOutput(BaseModel):
    suitability_score: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0)
    decision: Literal["APPROVE", "ESCALATE", "BLOCK"]
    reasoning: str
    justification_note: str
