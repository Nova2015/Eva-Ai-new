
import pytest

from .reasoning_eligibility import is_reasoning_eligible


@pytest.mark.parametrize(
    "question",
    [
        "B depends on A",
        "Task C requires both A and B",
        "D can start only after B",
        "Find the execution order",
        "Count all valid orders",
        "काम A आधी पूर्ण झाले पाहिजे",
        "B हे A वर अवलंबून आहे",
        "एकूण शक्य क्रम किती आहेत?",
    ],
)
def test_detects_reasoning_signals(question):
    result = is_reasoning_eligible(question)

    assert result.eligible is True
    assert result.signals
    assert result.reason == "possible_task_order_constraints"


@pytest.mark.parametrize(
    "question",
    [
        "",
        "   ",
        "Hello, how are you?",
        "Explain Python functions",
        "Write an email to my manager",
    ],
)
def test_rejects_unrelated_questions(question):
    result = is_reasoning_eligible(question)

    assert result.eligible is False
    assert result.signals == ()


@pytest.mark.parametrize(
    "question",
    [
        None,
        123,
        [],
        {},
    ],
)
def test_rejects_invalid_input(question):
    result = is_reasoning_eligible(question)

    assert result.eligible is False
    assert result.reason == "empty_or_invalid_question"


def test_detects_multiple_signal_categories():
    result = is_reasoning_eligible(
        "A before B. Find the execution order and count all valid orders."
    )

    assert result.eligible is True
    categories = {signal.split(":", 1)[0] for signal in result.signals}

    assert "dependency" in categories
    assert "execution_order" in categories
    assert "order_count" in categories


def test_case_insensitive_matching():
    result = is_reasoning_eligible("B DEPENDS ON A")

    assert result.eligible is True


def test_does_not_claim_semantic_verification():
    result = is_reasoning_eligible("B depends on A")

    assert result.reason == "possible_task_order_constraints"
    assert result.eligible is True
