from sqlalchemy import Column, Integer, String, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID
import uuid
from app.db.base import Base

class Account(Base):
    __tablename__ = "accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    age = Column(Integer, nullable=False)
    income = Column(Numeric, nullable=False)
    net_worth = Column(Numeric, nullable=False)
    risk_tolerance = Column(String(20), nullable=False)
    investment_choice = Column(String(100), nullable=False)
    investment_horizon = Column(Integer, nullable=False)
    notes = Column(Text)