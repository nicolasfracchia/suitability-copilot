import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB

from app.db.base import Base


class AuditLog(Base):
    """
    Immutable audit trail for every critical system event.

    Rule: rows are never updated or deleted — only inserted.
    If you can't audit it, you don't process it.
    """

    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type = Column(String, nullable=False)         # "account", "review"
    entity_id = Column(UUID(as_uuid=True), nullable=False)
    event_type = Column(String, nullable=False)          # "AI_EVALUATED", "POLICY_APPLIED", "HUMAN_OVERRIDE"
    actor = Column(String, nullable=False)               # "system", "admin_user"
    old_value = Column(JSONB, nullable=True)
    new_value = Column(JSONB, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
