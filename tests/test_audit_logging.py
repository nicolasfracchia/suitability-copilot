"""
Tests for audit logging during the review pipeline.

Verifies that AI_EVALUATED and POLICY_APPLIED audit events are created
atomically alongside the Review row.
"""
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.main import app
from app.db.deps import get_db
from app.models.audit_log import AuditLog
from app.schemas.ai_output import AIReviewOutput

client = TestClient(app)

MOCK_APPROVE = AIReviewOutput(
    suitability_score=85,
    confidence=0.95,
    decision="APPROVE",
    reasoning="Client demonstrates a balanced risk profile.",
    justification_note="Risk tolerance aligns with the selected strategy.",
)

MOCK_ESCALATE = AIReviewOutput(
    suitability_score=40,
    confidence=0.60,
    decision="ESCALATE",
    reasoning="Risk mismatch detected.",
    justification_note="Client selected aggressive strategy despite low risk tolerance.",
)


def _create_account():
    res = client.post("/accounts", json={
        "age": 35,
        "income": 80000.0,
        "net_worth": 50000.0,
        "risk_tolerance": "Medium",
        "investment_choice": "Balanced fund",
        "investment_horizon": 10,
        "notes": "Audit test account",
    })
    assert res.status_code == 200, res.text
    return res.json()["account_id"]


def _get_audit_logs(review_id: str) -> list[dict]:
    """Query audit_logs for a given review_id via the DB session."""
    # Get a real DB session directly for assertion queries
    db = next(get_db())
    try:
        logs = (
            db.query(AuditLog)
            .filter(AuditLog.entity_id == review_id)
            .order_by(AuditLog.created_at)
            .all()
        )
        return logs
    finally:
        db.close()


@patch("app.api.reviews.LLMService")
def test_ai_evaluated_audit_event_created(MockLLMService):
    """After a review, an AI_EVALUATED audit log must exist."""
    MockLLMService.return_value.evaluate.return_value = MOCK_APPROVE

    account_id = _create_account()
    res = client.post(f"/accounts/{account_id}/review")
    assert res.status_code == 200
    review_id = res.json()["review_id"]

    logs = _get_audit_logs(review_id)
    event_types = [log.event_type for log in logs]

    assert "AI_EVALUATED" in event_types, f"Expected AI_EVALUATED in {event_types}"

    ai_log = next(l for l in logs if l.event_type == "AI_EVALUATED")
    assert ai_log.actor == "system"
    assert ai_log.entity_type == "review"
    assert ai_log.new_value["decision"] == "APPROVE"
    assert ai_log.new_value["suitability_score"] == 85
    assert ai_log.old_value is None  # No prior state for AI evaluation


@patch("app.api.reviews.LLMService")
def test_policy_applied_audit_event_created(MockLLMService):
    """After a review, a POLICY_APPLIED audit log must exist."""
    MockLLMService.return_value.evaluate.return_value = MOCK_APPROVE

    account_id = _create_account()
    res = client.post(f"/accounts/{account_id}/review")
    assert res.status_code == 200
    review_id = res.json()["review_id"]

    logs = _get_audit_logs(review_id)
    event_types = [log.event_type for log in logs]

    assert "POLICY_APPLIED" in event_types, f"Expected POLICY_APPLIED in {event_types}"

    policy_log = next(l for l in logs if l.event_type == "POLICY_APPLIED")
    assert policy_log.actor == "system"
    assert policy_log.old_value["ai_decision"] == "APPROVE"
    assert policy_log.new_value["effective_decision"] == "AUTO_APPROVED"


@patch("app.api.reviews.LLMService")
def test_both_audit_events_created_in_order(MockLLMService):
    """Both AI_EVALUATED and POLICY_APPLIED must be present, in that order."""
    MockLLMService.return_value.evaluate.return_value = MOCK_ESCALATE

    account_id = _create_account()
    res = client.post(f"/accounts/{account_id}/review")
    assert res.status_code == 200
    review_id = res.json()["review_id"]

    logs = _get_audit_logs(review_id)
    event_types = [log.event_type for log in logs]

    assert event_types == ["AI_EVALUATED", "POLICY_APPLIED"]

    # For escalation: policy escalates ESCALATE decision
    policy_log = next(l for l in logs if l.event_type == "POLICY_APPLIED")
    assert policy_log.new_value["effective_decision"] == "ESCALATED"


@patch("app.api.reviews.LLMService")
def test_audit_logs_are_immutable_insert_only(MockLLMService):
    """Audit logs are created but never modified — they're append-only."""
    MockLLMService.return_value.evaluate.return_value = MOCK_APPROVE

    account_id = _create_account()
    res = client.post(f"/accounts/{account_id}/review")
    review_id = res.json()["review_id"]

    logs_before = _get_audit_logs(review_id)
    ids_before = {str(l.id) for l in logs_before}

    # Trigger another review on a different account (shouldn't affect prior logs)
    account_id_2 = _create_account()
    client.post(f"/accounts/{account_id_2}/review")

    logs_after = _get_audit_logs(review_id)
    ids_after = {str(l.id) for l in logs_after}

    # Original review's audit logs must be unchanged
    assert ids_before == ids_after
    assert len(logs_after) == 2  # Only 2 events per review
