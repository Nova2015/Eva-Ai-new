
import json

import pytest

from .reasoning_orchestrator import verify_reasoning_answer
from .state import VerificationStatus


QUESTION = (
    "A must happen before B. "
    "C depends on A. "
    "D requires both B and C. "
    "Count all valid execution orders."
)

ANSWER = (
    "One valid order is A, B, C, D. "
    "There are 2 valid execution orders."
)


def valid_payload():
    return {
        "tasks": [
            {"task_id": "A", "depends_on": []},
            {"task_id": "B", "depends_on": ["A"]},
            {"task_id": "C", "depends_on": ["A"]},
            {"task_id": "D", "depends_on": ["B", "C"]},
        ],
        "proposed_order": ["A", "B", "C", "D"],
        "proposed_order_count": 2,
        "ambiguities": [],
        "confidence": 0.95,
    }


def fake_llm_from(payload):
    def llm(prompt):
        assert "USER QUESTION:" in prompt
        assert "ASSISTANT ANSWER:" in prompt
        return json.dumps(payload)

    return llm


def test_valid_order_and_count_are_verified():
    result = verify_reasoning_answer(
        QUESTION,
        ANSWER,
        llm=fake_llm_from(valid_payload()),
    )

    assert result.attempted is True
    assert result.extraction is not None
    assert result.extraction.extraction_valid is True
    assert result.verification.status == VerificationStatus.VERIFIED


def test_invalid_order_is_failed():
    payload = valid_payload()
    payload["proposed_order"] = ["B", "A", "C", "D"]

    result = verify_reasoning_answer(
        QUESTION,
        ANSWER,
        llm=fake_llm_from(payload),
    )

    assert result.attempted is True
    assert result.verification.status == VerificationStatus.FAILED


def test_incorrect_order_count_is_failed():
    payload = valid_payload()
    payload["proposed_order_count"] = 6

    result = verify_reasoning_answer(
        QUESTION,
        ANSWER,
        llm=fake_llm_from(payload),
    )

    assert result.verification.status == VerificationStatus.FAILED
    assert "Incorrect valid-order count" in result.verification.failure_reason


def test_ambiguous_extraction_is_inconclusive():
    payload = valid_payload()
    payload["ambiguities"] = ["Task C dependency is unclear"]

    result = verify_reasoning_answer(
        QUESTION,
        ANSWER,
        llm=fake_llm_from(payload),
    )

    assert result.attempted is True
    assert result.verification.status == VerificationStatus.INCONCLUSIVE


def test_malformed_json_is_inconclusive():
    result = verify_reasoning_answer(
        QUESTION,
        ANSWER,
        llm=lambda prompt: "not valid JSON",
    )

    assert result.attempted is True
    assert result.extraction is not None
    assert result.extraction.extraction_valid is False
    assert result.verification.status == VerificationStatus.INCONCLUSIVE


def test_missing_llm_callback_is_inconclusive():
    result = verify_reasoning_answer(
        QUESTION,
        ANSWER,
    )

    assert result.attempted is False
    assert result.verification.status == VerificationStatus.INCONCLUSIVE


def test_unrelated_question_does_not_call_llm():
    def unexpected_llm(prompt):
        pytest.fail("LLM must not be called for unrelated questions")

    result = verify_reasoning_answer(
        "Explain Python functions.",
        "Python functions are reusable blocks of code.",
        llm=unexpected_llm,
    )

    assert result.attempted is False
    assert result.extraction is None
    assert result.eligibility.eligible is False


def test_empty_answer_does_not_call_llm():
    def unexpected_llm(prompt):
        pytest.fail("LLM must not be called for an empty answer")

    result = verify_reasoning_answer(
        QUESTION,
        "",
        llm=unexpected_llm,
    )

    assert result.attempted is False
    assert result.verification.status == VerificationStatus.INCONCLUSIVE


def test_provider_exception_fails_closed():
    def failing_llm(prompt):
        raise RuntimeError("provider unavailable")

    result = verify_reasoning_answer(
        QUESTION,
        ANSWER,
        llm=failing_llm,
    )

    assert result.attempted is True
    assert result.verification.status == VerificationStatus.INCONCLUSIVE


def test_extraction_and_verification_are_separate():
    result = verify_reasoning_answer(
        QUESTION,
        ANSWER,
        llm=fake_llm_from(valid_payload()),
    )

    assert result.extraction is not None
    assert len(result.extraction.tasks) == 4

    # This orchestrator verifies a proposed order; it does not execute tasks.
    assert all(
        task.status.value == "PENDING"
        for task in result.extraction.tasks
    )
