"""Original end-to-end flow test (requires Docker DB to be running).

Uses a mocked LLMService so it never calls the real OpenAI API.
"""
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.schemas.ai_output import AIReviewOutput

client = TestClient(app)

MOCK_MISMATCH = AIReviewOutput(
    suitability_score=40,
    confidence=0.85,
    decision="ESCALATE",
    reasoning="Risk mismatch detected.",
    justification_note="Client selected high-growth strategy despite low risk tolerance.",
)


@patch("app.api.reviews.LLMService")
def test_full_review_flow(MockLLMService):
    MockLLMService.return_value.evaluate.return_value = MOCK_MISMATCH

    account_data = {
        "age": 30,
        "income": 50000.0,
        "net_worth": 20000.0,
        "risk_tolerance": "Low",
        "investment_choice": "High-growth equities",
        "investment_horizon": 3,
        "notes": "Looking for fast gains",
    }

    res = client.post("/accounts", json=account_data)
    assert res.status_code == 200
    account_id = res.json()["account_id"]

    review_res = client.post(f"/accounts/{account_id}/review")
    assert review_res.status_code == 200

    data = review_res.json()
    assert data["effective_decision"] in ["AUTO_APPROVED", "ESCALATED"]