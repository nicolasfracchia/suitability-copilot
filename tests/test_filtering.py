"""
Tests for the admin review filtering endpoint.

GET /reviews                       → all reviews
GET /reviews?decision=ESCALATED    → only escalated
GET /reviews?decision=AUTO_APPROVED → only auto-approved
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
    reasoning="Balanced risk profile.",
    justification_note="Risk tolerance aligns.",
)

MOCK_ESCALATE = AIReviewOutput(
    suitability_score=40,
    confidence=0.60,
    decision="ESCALATE",
    reasoning="Risk mismatch detected.",
    justification_note="Aggressive strategy with low tolerance.",
)


def _create_account_and_review(mock_output: AIReviewOutput) -> dict:
    """Helper: create an account and trigger a review with the given mock output."""
    with patch("app.api.reviews.LLMService") as MockLLMService:
        MockLLMService.return_value.evaluate.return_value = mock_output

        account_res = client.post("/accounts", json={
            "age": 35,
            "income": 80000.0,
            "net_worth": 50000.0,
            "risk_tolerance": "Medium",
            "investment_choice": "Balanced fund",
            "investment_horizon": 10,
            "notes": "Filtering test account",
        })
        assert account_res.status_code == 200, account_res.text
        account_id = account_res.json()["account_id"]

        review_res = client.post(f"/accounts/{account_id}/review")
        assert review_res.status_code == 200, review_res.text
        return review_res.json()


def test_filter_returns_only_escalated():
    """GET /reviews?decision=ESCALATED must return only ESCALATED reviews."""
    escalated = _create_account_and_review(MOCK_ESCALATE)

    res = client.get("/reviews?decision=ESCALATED")
    assert res.status_code == 200
    data = res.json()

    assert len(data) >= 1
    # Every returned review must have ESCALATED effective_decision
    for r in data:
        assert r["effective_decision"] == "ESCALATED", (
            f"Expected ESCALATED but got {r['effective_decision']}"
        )

    # The review we just created must be in the results
    review_ids = {r["review_id"] for r in data}
    assert escalated["review_id"] in review_ids


def test_filter_returns_only_auto_approved():
    """GET /reviews?decision=AUTO_APPROVED must return only AUTO_APPROVED reviews."""
    approved = _create_account_and_review(MOCK_APPROVE)

    res = client.get("/reviews?decision=AUTO_APPROVED")
    assert res.status_code == 200
    data = res.json()

    assert len(data) >= 1
    for r in data:
        assert r["effective_decision"] == "AUTO_APPROVED", (
            f"Expected AUTO_APPROVED but got {r['effective_decision']}"
        )

    review_ids = {r["review_id"] for r in data}
    assert approved["review_id"] in review_ids


def test_filter_excludes_other_decisions():
    """Escalated reviews must NOT appear in AUTO_APPROVED filter results."""
    escalated = _create_account_and_review(MOCK_ESCALATE)

    res = client.get("/reviews?decision=AUTO_APPROVED")
    assert res.status_code == 200
    data = res.json()

    review_ids = {r["review_id"] for r in data}
    assert escalated["review_id"] not in review_ids


def test_no_filter_returns_all_reviews():
    """GET /reviews with no filter must return all reviews."""
    _create_account_and_review(MOCK_APPROVE)
    _create_account_and_review(MOCK_ESCALATE)

    res = client.get("/reviews")
    assert res.status_code == 200
    data = res.json()

    decisions = {r["effective_decision"] for r in data}
    # Both decision types must be present after we created both above
    assert "AUTO_APPROVED" in decisions
    assert "ESCALATED" in decisions


def test_filter_response_shape_is_correct():
    """Each item in the filtered response must have the full ReviewDetail shape."""
    _create_account_and_review(MOCK_APPROVE)

    res = client.get("/reviews?decision=AUTO_APPROVED")
    assert res.status_code == 200

    required_fields = {
        "review_id", "account_id", "suitability_score", "confidence",
        "ai_decision", "effective_decision", "reasoning", "justification_note",
        "model_version", "override_flag", "created_at",
    }
    for review in res.json():
        assert required_fields.issubset(review.keys()), (
            f"Missing fields: {required_fields - review.keys()}"
        )


def test_filter_case_insensitive_via_upper():
    """Client sending lowercase decision should still match (API calls .upper())."""
    _create_account_and_review(MOCK_ESCALATE)

    res = client.get("/reviews?decision=escalated")
    assert res.status_code == 200
    data = res.json()

    for r in data:
        assert r["effective_decision"] == "ESCALATED"
