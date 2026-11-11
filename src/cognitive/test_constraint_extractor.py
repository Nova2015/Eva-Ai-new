
import json

import pytest

try:
    from .constraint_extractor import (
    extract_constraints as _extract_constraints,
    _validate_payload,
    )
except ImportError:
    from constraint_extractor import (
    extract_constraints as _extract_constraints,
    _validate_payload,
    )


class FakeLLM:
    def __init__(self, response):
        self.response = response
        self.calls = 0
        self.prompts: list[str] = []

    def __call__(self, prompt: str):
        self.calls += 1
        self.prompts.append(prompt)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

def extract_constraints(message: str, llm=None):
    return _extract_constraints(
        question=message,
        answer="Proposed order: A, B, C, D",
        llm=llm,
    )

def valid_payload() -> dict[str, object]:
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


def test_valid_extraction():
    llm = FakeLLM(json.dumps(valid_payload()))

    result = extract_constraints(
        "A before B and C; D requires both B and C",
        llm=llm,
    )

    assert result.extraction_valid
    assert len(result.tasks) == 4
    assert result.proposed_order == ("A", "B", "C", "D")
    assert result.confidence == 0.95
    assert llm.calls == 1


def test_dependency_graph_is_preserved():
    llm = FakeLLM(json.dumps(valid_payload()))

    result = extract_constraints("Task constraints", llm=llm)

    dependencies = {
        task.task_id: task.depends_on
        for task in result.tasks
    }

    assert dependencies["A"] == []
    assert dependencies["B"] == ["A"]
    assert dependencies["C"] == ["A"]
    assert set(dependencies["D"]) == {"B", "C"}


def test_invalid_proposed_order_is_preserved_for_adapter_validation():
    payload = valid_payload()
    payload["proposed_order"] = ["B", "A", "C", "D"]

    result = extract_constraints(
        "A before B",
        llm=FakeLLM(json.dumps(payload)),
    )

    # Extraction validates the task graph, not the assistant's answer.
    assert result.extraction_valid
    assert result.proposed_order == ("B", "A", "C", "D")

    # The consistency adapter is responsible for rejecting this order.


def test_dependency_cycle_is_rejected():
    payload = valid_payload()
    payload["tasks"] = [
        {"task_id": "A", "depends_on": ["B"]},
        {"task_id": "B", "depends_on": ["A"]},
    ]
    payload["proposed_order"] = ["A", "B"]

    result = extract_constraints(
        "Circular tasks",
        llm=FakeLLM(json.dumps(payload)),
    )

    assert not result.extraction_valid
    assert result.errors


def test_unresolved_ambiguity_is_rejected():
    payload = valid_payload()
    payload["ambiguities"] = ["The meaning of task C is unclear"]

    result = extract_constraints(
        "Unclear task constraints",
        llm=FakeLLM(json.dumps(payload)),
    )

    assert not result.extraction_valid
    assert result.ambiguities


def test_missing_dependency_is_rejected():
    payload = valid_payload()
    payload["tasks"][1]["depends_on"] = ["UNKNOWN"]

    result = extract_constraints(
        "Unknown dependency",
        llm=FakeLLM(json.dumps(payload)),
    )

    assert not result.extraction_valid
    assert result.errors


@pytest.mark.parametrize(
    "response",
    ["", "not json", "{broken", "[]", "null", "123"],
)
def test_malformed_response_fails_closed(response):
    result = extract_constraints(
        "A before B",
        llm=FakeLLM(response),
    )

    assert not result.extraction_valid
    assert result.errors


def test_provider_failure_fails_closed():
    result = extract_constraints(
        "A before B",
        llm=FakeLLM(RuntimeError("provider unavailable")),
    )

    assert not result.extraction_valid
    assert result.errors


def test_missing_llm_fails_closed():
    result = extract_constraints("A before B")

    assert not result.extraction_valid
    assert "no LLM callback" in result.errors[0]


def test_empty_message_fails_closed():
    result = extract_constraints("", llm=FakeLLM("{}"))

    assert not result.extraction_valid
    assert "empty" in result.errors[0]


def test_proposed_order_can_be_absent():
    payload = valid_payload()
    payload["proposed_order"] = None
    payload["proposed_order_count"] = None

    result = extract_constraints(
        "A before B",
        llm=FakeLLM(json.dumps(payload)),
    )

    assert result.extraction_valid
    assert result.proposed_order is None


def test_prompt_does_not_request_chain_of_thought():
    llm = FakeLLM(json.dumps(valid_payload()))

    extract_constraints("A before B", llm=llm)

    prompt = llm.prompts[0].lower()
    assert "do not explain your reasoning" in prompt
    assert "chain of thought" not in prompt
    assert "think step by step" not in prompt
def test_question_and_answer_are_separated_in_prompt():
    llm = FakeLLM(json.dumps(valid_payload()))

    result = _extract_constraints(
        question="A must happen before B",
        answer="The proposed order is B, A, C, D",
        llm=llm,
    )

    assert result.extraction_valid
    prompt = llm.prompts[0]

    assert "USER QUESTION:" in prompt
    assert "A must happen before B" in prompt
    assert "ASSISTANT ANSWER:" in prompt
    assert "The proposed order is B, A, C, D" in prompt
def test_rejects_more_than_16_tasks():
    payload = valid_payload()

    payload["tasks"] = [
        {
            "task_id": f"T{i}",
            "depends_on": [],
        }
        for i in range(17)
    ]

    result = _validate_payload(payload)

    assert result.extraction_valid is False
    assert any(
        "more than 16" in error
        for error in result.errors
    )


def test_accepts_exactly_16_tasks():
    payload = valid_payload()

    payload["tasks"] = [
        {
            "task_id": f"T{i}",
            "depends_on": [],
        }
        for i in range(16)
    ]
    payload["proposed_order"] = None

    result = _validate_payload(payload)

    assert result.extraction_valid is True
    assert len(result.tasks) == 16