"""
Regression guard for GET /metrics.

History: /metrics once reported zero for every pipeline counter. The counters
lived in process memory, the Celery worker incremented its own copy, and the API
served a different one. Nothing caught it.

A test that creates reviews through the API would NOT have caught it either:
the suite runs Celery eagerly, so during tests the "worker" is the API process
and the in-memory counters appear to work.

So these tests write reviews directly to the database instead, standing in for
"some other process produced this", and assert /metrics sees them. That is the
property that actually broke, and it fails against the old implementation.

Counts are asserted as deltas because the suite shares a database.
"""
from fastapi.testclient import TestClient

from app.db.deps import get_db
from app.main import app
from app.models.account import Account
from app.models.review import Review

client = TestClient(app)


def _metrics() -> dict:
    res = client.get("/metrics")
    assert res.status_code == 200, res.text
    return res.json()


def _seed_review(**review_kwargs) -> None:
    """Persist a review without going through the API or the Celery task."""
    db = next(get_db())
    try:
        account = Account(
            age=40,
            income=100_000,
            net_worth=250_000,
            risk_tolerance="Medium",
            investment_choice="Balanced fund",
            investment_horizon=10,
            notes="Metrics test account",
        )
        db.add(account)
        db.flush()

        db.add(Review(account_id=account.id, **review_kwargs))
        db.commit()
    finally:
        db.close()


def test_auto_approved_review_from_another_process_is_counted():
    """The core regression: metrics must reflect persisted state, not local counters."""
    before = _metrics()

    _seed_review(
        status="COMPLETED",
        effective_decision="AUTO_APPROVED",
        ai_decision="APPROVE",
        confidence=0.95,
        suitability_score=88,
    )

    after = _metrics()
    assert after["total_reviews"] == before["total_reviews"] + 1
    assert after["completed"] == before["completed"] + 1
    assert after["auto_approved"] == before["auto_approved"] + 1


def test_escalated_review_is_counted():
    before = _metrics()

    _seed_review(
        status="COMPLETED",
        effective_decision="ESCALATED",
        ai_decision="ESCALATE",
        confidence=0.62,
        suitability_score=40,
    )

    after = _metrics()
    assert after["escalated"] == before["escalated"] + 1
    assert after["auto_approved"] == before["auto_approved"]


def test_human_override_is_counted():
    before = _metrics()

    _seed_review(
        status="COMPLETED",
        effective_decision="AUTO_APPROVED",
        ai_decision="ESCALATE",
        confidence=0.55,
        suitability_score=45,
        override_flag=True,
        override_reason="Reviewer confirmed by phone",
    )

    after = _metrics()
    assert after["overridden"] == before["overridden"] + 1


def test_fail_safe_and_terminal_failures_count_as_llm_failures():
    """
    Both failure shapes roll into llm_failures: the fail-safe signature
    (confidence exactly 0.0 with an ESCALATE recommendation) and a task that
    exhausted its retries.
    """
    before = _metrics()

    _seed_review(
        status="COMPLETED",
        effective_decision="ESCALATED",
        ai_decision="ESCALATE",
        confidence=0.0,
        suitability_score=0,
    )
    _seed_review(status="FAILED")

    after = _metrics()
    assert after["llm_failures"] == before["llm_failures"] + 2
    assert after["failed"] == before["failed"] + 1


def test_pending_reviews_are_visible_but_not_completed():
    """Queue depth must be observable — it is the operator's saturation signal."""
    before = _metrics()

    _seed_review(status="PENDING")

    after = _metrics()
    assert after["pending"] == before["pending"] + 1
    assert after["completed"] == before["completed"]


def test_rates_are_consistent_with_their_counts():
    _seed_review(
        status="COMPLETED",
        effective_decision="AUTO_APPROVED",
        ai_decision="APPROVE",
        confidence=0.95,
        suitability_score=88,
    )

    m = _metrics()
    assert m["completed"] > 0
    assert m["auto_approval_rate"] == round(m["auto_approved"] / m["completed"], 4)
    assert m["override_rate"] == round(m["overridden"] / m["completed"], 4)


def test_metrics_response_has_the_documented_shape():
    expected = {
        "total_reviews", "completed", "pending", "failed",
        "auto_approved", "escalated", "overridden", "llm_failures",
        "auto_approval_rate", "override_rate",
    }
    assert expected.issubset(_metrics().keys())
