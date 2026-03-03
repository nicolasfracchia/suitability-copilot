"""
Comprehensive end-to-end flow test.

This is the authoritative full-stack test for a single review lifecycle:
  1. Create account
  2. Trigger review (mocked LLM — no real OpenAI calls)
  3. Confirm HTTP response shape
  4. Confirm DB state (review row persisted correctly)
  5. Confirm audit event log (AI_EVALUATED + POLICY_APPLIED events created)
"""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.main import app
from app.db.deps import get_db
from app.models.review import Review
from app.models.audit_log import AuditLog
from app.schemas.ai_output import AIReviewOutput

client = TestClient(app)

MOCK_ESCALATE = AIReviewOutput(
    suitability_score=40,
    confidence=0.85,
    decision="ESCALATE",
    reasoning="Risk mismatch: aggressive fund with low risk tolerance.",
    justification_note="Client selected high-growth strategy despite low risk tolerance.",
)


@patch("app.services.llm_service.LLMService.evaluate")
def test_full_review_flow(mock_evaluate):
    """
    Full pipeline integration test:
    Create account → Trigger review → Verify response, DB state, and audit events.
    """
    mock_evaluate.return_value = MOCK_ESCALATE

    # ── Step 1: Create Account ─────────────────────────────────────────────
    acc_res = client.post("/accounts", json={
        "age": 30,
        "income": 50000.0,
        "net_worth": 20000.0,
        "risk_tolerance": "Low",
        "investment_choice": "High-growth equities",
        "investment_horizon": 3,
        "notes": "Looking for fast gains",
    })
    assert acc_res.status_code == 200
    account_id = acc_res.json()["account_id"]

    # ── Step 2: Trigger Review ─────────────────────────────────────────────
    review_res = client.post(f"/accounts/{account_id}/review")
    assert review_res.status_code == 200
    response_data = review_res.json()
    review_id = response_data["review_id"]

    # ── Step 3: Confirm HTTP Response Shape ────────────────────────────────
    assert response_data["status"] == "COMPLETED"
    assert response_data["ai_decision"] == "ESCALATE"
    assert response_data["effective_decision"] == "ESCALATED"
    assert response_data["confidence"] == pytest.approx(0.85, abs=1e-9)

    # ── Step 4: Confirm DB State ───────────────────────────────────────────
    db = next(get_db())
    try:
        review = db.query(Review).filter(Review.id == review_id).first()

        assert review is not None, "Review must be persisted to DB"
        assert str(review.account_id) == account_id
        assert review.status == "COMPLETED"
        assert review.ai_decision == "ESCALATE"
        assert review.effective_decision == "ESCALATED"
        assert review.suitability_score == 40
        assert float(review.confidence) == pytest.approx(0.85, abs=1e-9)
        assert review.ai_reasoning == MOCK_ESCALATE.reasoning
        assert review.ai_justification_note == MOCK_ESCALATE.justification_note
        assert review.model_version is not None
        assert review.override_flag is False
        assert review.override_reason is None

        # ── Step 5: Confirm Audit Event Log ───────────────────────────────
        audit_logs = (
            db.query(AuditLog)
            .filter(AuditLog.entity_id == review_id)
            .order_by(AuditLog.created_at)
            .all()
        )
        event_types = [log.event_type for log in audit_logs]

        # Both events must exist in correct order
        assert event_types == ["AI_EVALUATED", "POLICY_APPLIED"], (
            f"Expected [AI_EVALUATED, POLICY_APPLIED], got {event_types}"
        )

        # AI_EVALUATED event assertions
        ai_log = next(l for l in audit_logs if l.event_type == "AI_EVALUATED")
        assert ai_log.actor == "system"
        assert ai_log.entity_type == "review"
        assert ai_log.old_value is None
        assert ai_log.new_value["decision"] == "ESCALATE"
        assert ai_log.new_value["suitability_score"] == 40

        # POLICY_APPLIED event assertions
        policy_log = next(l for l in audit_logs if l.event_type == "POLICY_APPLIED")
        assert policy_log.actor == "system"
        assert policy_log.old_value["ai_decision"] == "ESCALATE"
        assert policy_log.new_value["effective_decision"] == "ESCALATED"

    finally:
        db.close()