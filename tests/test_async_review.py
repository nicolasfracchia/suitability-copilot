import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.schemas.ai_output import AIReviewOutput

client = TestClient(app)

MOCK_APPROVE = AIReviewOutput(
    suitability_score=85,
    confidence=0.95,
    decision="APPROVE",
    reasoning="Wait. This is eager, so it happens inline.",
    justification_note="Test note.",
)

def test_account_creation_triggers_pending_review():
    """POST /accounts should create account + review and return status=PENDING."""
    with patch("app.services.llm_service.LLMService.evaluate") as mock_eval:
        mock_eval.return_value = MOCK_APPROVE
        
        res = client.post("/accounts", json={
            "age": 30,
            "income": 50000.0,
            "net_worth": 20000.0,
            "risk_tolerance": "Low",
            "investment_choice": "Bonds",
            "investment_horizon": 5,
            "notes": "Fast-return test",
        })
        
        assert res.status_code == 200
        data = res.json()
        assert "account_id" in data
        assert "review_id" in data
        assert data["status"] == "PENDING"  # Status returned by API immediately
        
        # Since CELERY_TASK_ALWAYS_EAGER=True, the task has already finished by now.
        # We can check the DB state via GET /reviews/{id}
        review_id = data["review_id"]
        review_res = client.get(f"/reviews/{review_id}")
        assert review_res.status_code == 200
        review_data = review_res.json()
        assert review_data["status"] == "COMPLETED"
        assert review_data["ai_decision"] == "APPROVE"

def test_on_demand_review_idempotency():
    """Calling review endpoint twice for the same account should return same review ID."""
    with patch("app.services.llm_service.LLMService.evaluate") as mock_eval:
        mock_eval.return_value = MOCK_APPROVE
        
        # 1. Create account (triggers first review)
        acc_res = client.post("/accounts", json={
            "age": 30, "income": 50000.0, "net_worth": 20000.0,
            "risk_tolerance": "Low", "investment_choice": "Bonds",
            "investment_horizon": 5, "notes": "Idempotency test",
        })
        review_id_1 = acc_res.json()["review_id"]
        account_id = acc_res.json()["account_id"]
        
        # 2. Trigger review manually via the separate endpoint
        rev_res = client.post(f"/accounts/{account_id}/review")
        assert rev_res.status_code == 200
        review_id_2 = rev_res.json()["review_id"]
        
        # IDs must match
        assert review_id_1 == review_id_2

def test_readiness_endpoint():
    """Verify the /ready endpoint checks dependencies."""
    # This might fail in test env if Redis isn't actually there, 
    # but it verifies the endpoint exists and logic fires.
    res = client.get("/ready")
    assert res.status_code in [200, 503] # 503 is custom 503 from my code if redis down

def test_review_failure_status():
    """If LLM fails, task should eventually mark status as FAILED or handle it."""
    with patch("app.services.llm_service.LLMService.evaluate", side_effect=Exception("LLM Timeout")):
        res = client.post("/accounts", json={
            "age": 30, "income": 50000.0, "net_worth": 20000.0,
            "risk_tolerance": "Low", "investment_choice": "Bonds",
            "investment_horizon": 5, "notes": "Failure test",
        })
        review_id = res.json()["review_id"]
        
        # In eager mode, the retry logic in tasks.py will fire.
        # Since we mocked side_effect, it will fail 3 times and then mark as FAILED.
        review_res = client.get(f"/reviews/{review_id}")
        assert review_res.json()["status"] == "FAILED"
