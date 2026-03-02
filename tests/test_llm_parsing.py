"""Unit tests for AIReviewOutput JSON parsing and validation.

These tests exercise the validation firewall between raw LLM output and the DB.
No DB, no network — pure schema validation.
"""
import pytest
from pydantic import ValidationError
from app.schemas.ai_output import AIReviewOutput

VALID_JSON = """{
    "suitability_score": 75,
    "confidence": 0.92,
    "decision": "APPROVE",
    "reasoning": "Client profile is consistent with stated investment goals.",
    "justification_note": "Risk tolerance aligns with the selected strategy."
}"""


def test_valid_json_parses_correctly():
    result = AIReviewOutput.model_validate_json(VALID_JSON)
    assert result.suitability_score == 75
    assert result.confidence == 0.92
    assert result.decision == "APPROVE"
    assert result.reasoning != ""


def test_missing_required_field_raises():
    # Missing 'reasoning' and 'justification_note'
    bad = '{"suitability_score": 75, "confidence": 0.92, "decision": "APPROVE"}'
    with pytest.raises(ValidationError):
        AIReviewOutput.model_validate_json(bad)


def test_confidence_above_one_is_rejected():
    bad = VALID_JSON.replace('"confidence": 0.92', '"confidence": 1.5')
    with pytest.raises(ValidationError):
        AIReviewOutput.model_validate_json(bad)


def test_confidence_below_zero_is_rejected():
    bad = VALID_JSON.replace('"confidence": 0.92', '"confidence": -0.1')
    with pytest.raises(ValidationError):
        AIReviewOutput.model_validate_json(bad)


def test_score_above_100_is_rejected():
    bad = VALID_JSON.replace('"suitability_score": 75', '"suitability_score": 150')
    with pytest.raises(ValidationError):
        AIReviewOutput.model_validate_json(bad)


def test_score_below_zero_is_rejected():
    bad = VALID_JSON.replace('"suitability_score": 75', '"suitability_score": -5')
    with pytest.raises(ValidationError):
        AIReviewOutput.model_validate_json(bad)


def test_invalid_decision_literal_is_rejected():
    bad = VALID_JSON.replace('"decision": "APPROVE"', '"decision": "MAYBE"')
    with pytest.raises(ValidationError):
        AIReviewOutput.model_validate_json(bad)


def test_block_decision_is_valid():
    ok = VALID_JSON.replace('"decision": "APPROVE"', '"decision": "BLOCK"')
    result = AIReviewOutput.model_validate_json(ok)
    assert result.decision == "BLOCK"


def test_escalate_decision_is_valid():
    ok = VALID_JSON.replace('"decision": "APPROVE"', '"decision": "ESCALATE"')
    result = AIReviewOutput.model_validate_json(ok)
    assert result.decision == "ESCALATE"
