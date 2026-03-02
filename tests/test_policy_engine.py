"""Unit tests for the policy engine.

Tests are pure logic — no DB, no LLM, no network.
"""
from app.schemas.ai_output import AIReviewOutput
from app.services.policy_engine import apply_policy, CONFIDENCE_THRESHOLD


def _result(decision: str, confidence: float) -> AIReviewOutput:
    return AIReviewOutput(
        suitability_score=70,
        confidence=confidence,
        decision=decision,
        reasoning="test",
        justification_note="test",
    )


# --- APPROVE path -----------------------------------------------------------

def test_high_confidence_approve_is_auto_approved():
    assert apply_policy(_result("APPROVE", 0.95)) == "AUTO_APPROVED"


def test_exactly_at_threshold_approve_is_auto_approved():
    assert apply_policy(_result("APPROVE", CONFIDENCE_THRESHOLD)) == "AUTO_APPROVED"


def test_just_below_threshold_approve_is_escalated():
    assert apply_policy(_result("APPROVE", CONFIDENCE_THRESHOLD - 0.01)) == "ESCALATED"


def test_low_confidence_approve_is_escalated():
    assert apply_policy(_result("APPROVE", 0.50)) == "ESCALATED"


# --- ESCALATE path ----------------------------------------------------------

def test_llm_escalate_is_escalated_regardless_of_confidence():
    assert apply_policy(_result("ESCALATE", 0.99)) == "ESCALATED"


def test_llm_escalate_low_confidence_is_escalated():
    assert apply_policy(_result("ESCALATE", 0.10)) == "ESCALATED"


# --- BLOCK path -------------------------------------------------------------

def test_block_with_high_confidence_is_still_escalated():
    """BLOCK must NEVER auto-block — always escalate to a human."""
    assert apply_policy(_result("BLOCK", 0.99)) == "ESCALATED"


def test_block_with_any_confidence_is_escalated():
    assert apply_policy(_result("BLOCK", 0.50)) == "ESCALATED"
