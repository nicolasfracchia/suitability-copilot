"""Integration tests for the review endpoint with mocked LLM.

The LLMService is patched so no real OpenAI call is made.
The DB is real (requires Docker with postgres running).
"""
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.ai_output import AIReviewOutput

client = TestClient(app)

MOCK_APPROVE = AIReviewOutput(
    suitability_score=85,
    confidence=0.95,
    decision="APPROVE",
    reasoning="Client demonstrates a balanced risk profile consistent with stated goals.",
    justification_note="Risk tolerance aligns with the selected strategy.",
)

MOCK_ESCALATE = AIReviewOutput(
    suitability_score=40,
    confidence=0.60,
    decision="ESCALATE",
    reasoning="Risk mismatch detected between tolerance and investment choice.",
    justification_note="Client selected aggressive strategy despite low risk tolerance.",
)

MOCK_BLOCK = AIReviewOutput(
    suitability_score=10,
    confidence=0.99,
    decision="BLOCK",
    reasoning="Clear regulatory violation detected.",
    justification_note="Investment exceeds client's stated net worth capacity.",
)


def _create_account(risk_tolerance="Medium", investment_choice="Balanced fund"):
    res = client.post("/accounts", json={
        "age": 35,
        "income": 80000.0,
        "net_worth": 50000.0,
        "risk_tolerance": risk_tolerance,
        "investment_choice": investment_choice,
        "investment_horizon": 10,
        "notes": "Integration test account",
    })
    assert res.status_code == 200, res.text
    return res.json()["account_id"]


@patch("app.api.reviews.LLMService")
def test_high_confidence_approve_returns_auto_approved(MockLLMService):
    MockLLMService.return_value.evaluate.return_value = MOCK_APPROVE

    account_id = _create_account()
    res = client.post(f"/accounts/{account_id}/review")

    assert res.status_code == 200
    data = res.json()
    assert data["ai_decision"] == "APPROVE"
    assert data["effective_decision"] == "AUTO_APPROVED"
    assert data["confidence"] == 0.95
    assert "reasoning" in data
    assert data["model_version"] is not None


@patch("app.api.reviews.LLMService")
def test_escalate_decision_returns_escalated(MockLLMService):
    MockLLMService.return_value.evaluate.return_value = MOCK_ESCALATE

    account_id = _create_account()
    res = client.post(f"/accounts/{account_id}/review")

    assert res.status_code == 200
    data = res.json()
    assert data["ai_decision"] == "ESCALATE"
    assert data["effective_decision"] == "ESCALATED"


@patch("app.api.reviews.LLMService")
def test_block_decision_is_escalated_not_auto_blocked(MockLLMService):
    """Even BLOCK at 0.99 confidence must never auto-block — it must escalate."""
    MockLLMService.return_value.evaluate.return_value = MOCK_BLOCK

    account_id = _create_account()
    res = client.post(f"/accounts/{account_id}/review")

    assert res.status_code == 200
    assert res.json()["effective_decision"] == "ESCALATED"


@patch("app.api.reviews.LLMService")
def test_review_stored_and_retrievable_via_get(MockLLMService):
    """End-to-end: create → review → GET /reviews/{id} returns full detail."""
    MockLLMService.return_value.evaluate.return_value = MOCK_APPROVE

    account_id = _create_account()
    review_res = client.post(f"/accounts/{account_id}/review")
    assert review_res.status_code == 200
    review_id = review_res.json()["review_id"]

    detail_res = client.get(f"/reviews/{review_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()

    assert detail["review_id"] == review_id
    assert detail["ai_decision"] == "APPROVE"
    assert detail["effective_decision"] == "AUTO_APPROVED"
    assert "justification_note" in detail
    assert "created_at" in detail


def test_review_unknown_account_returns_404():
    res = client.post("/accounts/00000000-0000-0000-0000-000000000000/review")
    assert res.status_code == 404
