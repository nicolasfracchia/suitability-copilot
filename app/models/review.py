import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, Integer, String, Numeric, Text, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class Review(Base):
    __tablename__ = "reviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    
    # New status field for async processing
    # PENDING: Task queued but not finished
    # COMPLETED: AI evaluation and policy applied successfully
    # FAILED: Error during processing (e.g. LLM timeout, DB error)
    status = Column(String(20), nullable=False, default="PENDING")

    # These may be null initially while status is PENDING
    suitability_score = Column(Integer, nullable=True)
    confidence = Column(Numeric, nullable=True)
    ai_decision = Column(String(20), nullable=True)           # Raw LLM recommendation
    effective_decision = Column(String(20), nullable=True)    # Final policy decision
    ai_reasoning = Column(Text, nullable=True)
    ai_justification_note = Column(Text, nullable=True)
    model_version = Column(String(50), nullable=True)
    
    # Override fields — set when a human changes the effective decision
    override_flag = Column(Boolean, nullable=False, default=False)
    override_reason = Column(Text, nullable=True)
    
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )