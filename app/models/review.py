import uuid
from sqlalchemy import Column, Integer, String, Numeric, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base

class Review(Base):
    __tablename__ = "reviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    suitability_score = Column(Integer, nullable=False)
    confidence = Column(Numeric, nullable=False)
    decision = Column(String(20), nullable=False)
    ai_reasoning = Column(Text, nullable=False)
    ai_justification_note = Column(Text, nullable=False)
    model_version = Column(String(50), nullable=False)