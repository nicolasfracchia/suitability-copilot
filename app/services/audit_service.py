"""
Audit service — single point of entry for writing to the audit trail.

DESIGN CONTRACT:
  - log_event() adds to the session but does NOT commit.
  - The caller owns the transaction; if any step fails, the entire
    transaction (including the audit row) rolls back.
  - This enforces the rule: if you can't audit it, you don't process it.
"""
from uuid import UUID
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def log_event(
    db: Session,
    *,
    entity_type: str,
    entity_id: UUID,
    event_type: str,
    actor: str,
    new_value: dict[str, Any],
    old_value: dict[str, Any] | None = None,
) -> AuditLog:
    """
    Append an audit event to the current session.

    Does NOT commit — caller is responsible for commit/rollback.
    Raises on any persistence error so the caller's transaction rolls back.
    """
    entry = AuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=event_type,
        actor=actor,
        old_value=old_value,
        new_value=new_value,
    )
    db.add(entry)
    return entry
