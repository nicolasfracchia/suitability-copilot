"""
Tests for the human override endpoint.

Verifies that:
  - effective_decision changes
  - AI reasoning and ai_decision are NEVER modified
  - override_flag is set to True
  - A HUMAN_OVERRIDE audit event is created
  - Invalid decisions are rejected
"""
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.main import app
from app.db.deps import get_db
from app.models.audit_log import AuditLog
from app.schemas.ai_output import AIReviewOutput

client = TestClient(app)

MOCK_ESCALATE = AIReviewOutput(
    suitability_score=40,
    confidence=0.60,
    decision="ESCALATE",
    reasoning="Risk mismatch: aggressive fund with low tolerance.",
    justification_note="Client selected aggressive strategy despite low risk tolerance.",
)

MOCK_APPROVE = AIReviewOutput(
    suitability_score=85,
    confidence=0.95,
    decision="APPROVE",
    reasoning="Balanced risk profile consistent with goals.",
    justification_note="Risk tolerance aligns with selected strategy.",
)


def _create_account():
    res = client.post("/accounts", json={
        "age": 35,
        "income": 80000.0,
        "net_worth": 50000.0,
        "risk_tolerance": "Medium",
        "investment_choice": "Balanced fund",
        "investment_horizon": 10,
        "notes": "Override test account",
    })
    assert res.status_code == 200, res.text
    return res.json()["account_id"]


def _get_audit_logs(review_id: str) -> list:
    db = next(get_db())
    try:
        return (
            db.query(AuditLog)
            .filter(AuditLog.entity_id == review_id)
            .order_by(AuditLog.created_at)
            .all()
        )
    finally:
        db.close()


@patch("app.api.reviews.LLMService")
def test_override_changes_effective_decision(MockLLMService):
    """Override must change effective_decision to the requested value."""
    MockLLMService.return_value.evaluate.return_value = MOCK_ESCALATE

    account_id = _create_account()
    review_res = client.post(f"/accounts/{account_id}/review")
    assert review_res.status_code == 200
    review_id = review_res.json()["review_id"]
    assert review_res.json()["effective_decision"] == "ESCALATED"

    override_res = client.post(f"/reviews/{review_id}/override", json={
        "new_decision": "AUTO_APPROVED",
        "reason": "Client provided additional documentation confirming suitability.",
    })
    assert override_res.status_code == 200
    data = override_res.json()
    assert data["new_decision"] == "AUTO_APPROVED"
    assert data["old_decision"] == "ESCALATED"
    assert data["actor"] == "admin_user"


@patch("app.api.reviews.LLMService")
def test_override_preserves_ai_reasoning(MockLLMService):
    """AI decision and reasoning must NEVER be modified by an override."""
    MockLLMService.return_value.evaluate.return_value = MOCK_ESCALATE

    account_id = _create_account()
    review_res = client.post(f"/accounts/{account_id}/review")
    review_id = review_res.json()["review_id"]
    original_ai_decision = review_res.json()["ai_decision"]
    original_reasoning = review_res.json()["reasoning"]

    client.post(f"/reviews/{review_id}/override", json={
        "new_decision": "AUTO_APPROVED",
        "reason": "Documentation provided.",
    })

    detail_res = client.get(f"/reviews/{review_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()

    # AI fields must be UNCHANGED
    assert detail["ai_decision"] == original_ai_decision
    assert detail["reasoning"] == original_reasoning

    # But effective decision reflects the override
    assert detail["effective_decision"] == "AUTO_APPROVED"


@patch("app.api.reviews.LLMService")
def test_override_sets_override_flag(MockLLMService):
    """After an override, override_flag must be True and override_reason must be set."""
    MockLLMService.return_value.evaluate.return_value = MOCK_ESCALATE

    account_id = _create_account()
    review_res = client.post(f"/accounts/{account_id}/review")
    review_id = review_res.json()["review_id"]

    override_reason = "Client provided additional documentation."
    client.post(f"/reviews/{review_id}/override", json={
        "new_decision": "AUTO_APPROVED",
        "reason": override_reason,
    })

    detail_res = client.get(f"/reviews/{review_id}")
    detail = detail_res.json()

    assert detail["override_flag"] is True
    assert detail["override_reason"] == override_reason


@patch("app.api.reviews.LLMService")
def test_override_creates_human_override_audit_log(MockLLMService):
    """Override must create a HUMAN_OVERRIDE audit event with correct values."""
    MockLLMService.return_value.evaluate.return_value = MOCK_ESCALATE

    account_id = _create_account()
    review_res = client.post(f"/accounts/{account_id}/review")
    review_id = review_res.json()["review_id"]

    client.post(f"/reviews/{review_id}/override", json={
        "new_decision": "REJECTED",
        "reason": "Compliance team confirmed hard block.",
    })

    logs = _get_audit_logs(review_id)
    event_types = [l.event_type for l in logs]

    assert "HUMAN_OVERRIDE" in event_types

    override_log = next(l for l in logs if l.event_type == "HUMAN_OVERRIDE")
    assert override_log.actor == "admin_user"
    assert override_log.old_value["effective_decision"] == "ESCALATED"
    assert override_log.new_value["effective_decision"] == "REJECTED"
    assert override_log.new_value["reason"] == "Compliance team confirmed hard block."


@patch("app.api.reviews.LLMService")
def test_override_not_overridden_review_has_flag_false(MockLLMService):
    """A review that was NOT overridden must have override_flag=False."""
    MockLLMService.return_value.evaluate.return_value = MOCK_APPROVE

    account_id = _create_account()
    review_res = client.post(f"/accounts/{account_id}/review")
    review_id = review_res.json()["review_id"]

    detail_res = client.get(f"/reviews/{review_id}")
    detail = detail_res.json()

    assert detail["override_flag"] is False
    assert detail["override_reason"] is None


def test_override_invalid_decision_rejected():
    """Invalid new_decision values must return 422."""
    # Create a minimal review to get a real review_id
    with patch("app.api.reviews.LLMService") as MockLLMService:
        MockLLMService.return_value.evaluate.return_value = MOCK_ESCALATE
        account_res = client.post("/accounts", json={
            "age": 30, "income": 50000.0, "net_worth": 20000.0,
            "risk_tolerance": "Low", "investment_choice": "Bonds",
            "investment_horizon": 5, "notes": "",
        })
        account_id = account_res.json()["account_id"]
        review_res = client.post(f"/accounts/{account_id}/review")
        review_id = review_res.json()["review_id"]

    res = client.post(f"/reviews/{review_id}/override", json={
        "new_decision": "TOTALLY_MADE_UP",
        "reason": "This should fail.",
    })
    assert res.status_code == 422


def test_override_unknown_review_returns_404():
    """Override on a non-existent review must return 404."""
    res = client.post(
        "/reviews/00000000-0000-0000-0000-000000000000/override",
        json={"new_decision": "AUTO_APPROVED", "reason": "Test."},
    )
    assert res.status_code == 404
