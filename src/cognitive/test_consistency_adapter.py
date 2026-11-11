from types import SimpleNamespace

import pytest

try:
    from cognitive.consistency_adapter import verify_task_order_consistency
    from cognitive.verification import verify
    from cognitive.executor import ExecutionResult
    from cognitive.planning import TaskPlan
    from cognitive.strategy import StrategyDecision, VerificationRequirement
    from cognitive.state import VerificationStatus, PlannedTask
except ImportError:
    from src.cognitive.consistency_adapter import verify_task_order_consistency
    from src.cognitive.verification import verify
    from src.cognitive.executor import ExecutionResult
    from src.cognitive.planning import TaskPlan
    from src.cognitive.strategy import StrategyDecision, VerificationRequirement
    from src.cognitive.state import VerificationStatus, PlannedTask


def make_tasks():
    return [
        SimpleNamespace(task_id="A", depends_on=[]),
        SimpleNamespace(task_id="B", depends_on=["A"]),
        SimpleNamespace(task_id="C", depends_on=["A"]),
        SimpleNamespace(task_id="D", depends_on=["B", "C"]),
    ]
def make_task(task_id, depends_on=None):
    return PlannedTask(
        task_id=task_id,
        depends_on=depends_on or [],
        objective=f"Complete task {task_id}",
        verification_criteria=["task completed"],
    )

def test_valid_order_is_verified():
    result = verify_task_order_consistency(
        make_tasks(), ["A", "B", "C", "D"]
    )
    assert result.status == VerificationStatus.VERIFIED
    assert result.verification_type == "TASK_ORDER_CONSISTENCY"
    assert result.confidence == 1.0

def test_correct_proposed_order_count_is_verified():
    result = verify_task_order_consistency(
        make_tasks(),
        ["A", "B", "C", "D"],
        proposed_order_count=2,
    )
    assert result.status == VerificationStatus.VERIFIED
    assert any(
        "matches exact count: 2" in item
        for item in result.criteria
    )


def test_incorrect_proposed_order_count_is_failed():
    result = verify_task_order_consistency(
        make_tasks(),
        ["A", "B", "C", "D"],
        proposed_order_count=6,
    )
    assert result.status == VerificationStatus.FAILED
    assert "assistant stated 6" in result.failure_reason
    assert "validator calculated 2" in result.failure_reason

def test_invalid_dependency_order_is_failed():
    result = verify_task_order_consistency(
        make_tasks(), ["B", "A", "C", "D"]
    )
    assert result.status == VerificationStatus.FAILED
    assert "must execute before" in result.failure_reason


def test_missing_proposed_order_is_inconclusive():
    result = verify_task_order_consistency(make_tasks(), None)
    assert result.status == VerificationStatus.INCONCLUSIVE
    assert "No proposed order" in result.failure_reason


def test_invalid_dependency_graph_is_inconclusive():
    tasks = [
        SimpleNamespace(task_id="A", depends_on=["UNKNOWN"]),
    ]
    result = verify_task_order_consistency(tasks, ["A"])
    assert result.status == VerificationStatus.INCONCLUSIVE
    assert "unknown task" in result.failure_reason


def test_incomplete_proposed_order_is_failed():
    result = verify_task_order_consistency(
        make_tasks(), ["A", "B", "C"]
    )
    assert result.status == VerificationStatus.FAILED
    assert "missing tasks" in result.failure_reason


def test_invalid_input_is_inconclusive():
    result = verify_task_order_consistency(None, ["A"])
    assert result.status == VerificationStatus.INCONCLUSIVE
    assert result.confidence == 0.0

def test_duplicate_task_ids_are_inconclusive():
    tasks = [
        SimpleNamespace(task_id="A", depends_on=[]),
        SimpleNamespace(task_id="A", depends_on=[]),
    ]
    result = verify_task_order_consistency(tasks, ["A"])
    assert result.status == VerificationStatus.INCONCLUSIVE
    assert "Duplicate task_id" in result.failure_reason


def test_dependency_cycle_is_inconclusive():
    tasks = [
        SimpleNamespace(task_id="A", depends_on=["B"]),
        SimpleNamespace(task_id="B", depends_on=["A"]),
    ]
    result = verify_task_order_consistency(tasks, ["A", "B"])
    assert result.status == VerificationStatus.INCONCLUSIVE
    assert "cycle" in result.failure_reason.lower()


def test_unknown_proposed_task_is_failed():
    result = verify_task_order_consistency(
        make_tasks(), ["A", "B", "C", "X"]
    )
    assert result.status == VerificationStatus.FAILED
    assert "unknown tasks" in result.failure_reason


def test_duplicate_proposed_task_is_failed():
    result = verify_task_order_consistency(
        make_tasks(), ["A", "B", "B", "C", "D"]
    )
    assert result.status == VerificationStatus.FAILED
    assert "duplicate task IDs" in result.failure_reason


def test_malformed_task_object_is_inconclusive():
    result = verify_task_order_consistency(
        [SimpleNamespace()], ["A"]
    )
    assert result.status == VerificationStatus.INCONCLUSIVE


def test_large_task_graph_does_not_claim_exact_count():
    tasks = [
        SimpleNamespace(task_id=f"T{i}", depends_on=[])
        for i in range(17)
    ]
    order = [f"T{i}" for i in range(17)]
    result = verify_task_order_consistency(tasks, order)
    assert result.status == VerificationStatus.VERIFIED
    assert not any("Exact number" in item for item in result.criteria)


def test_unknown_dependency_is_inconclusive():
    tasks = [
        SimpleNamespace(task_id="A", depends_on=["MISSING"]),
    ]
    result = verify_task_order_consistency(tasks, ["A"])
    assert result.status == VerificationStatus.INCONCLUSIVE
    assert "unknown task" in result.failure_reason
def test_verify_integration_valid_order():
    from cognitive.verification import verify
    from cognitive.executor import ExecutionResult
    from cognitive.planning import TaskPlan
    from cognitive.strategy import (
        StrategyDecision,
        VerificationRequirement,
    )
    from cognitive.state import VerificationStatus

    tasks = [
        make_task("A"),
        make_task("B", depends_on=["A"]),
        make_task("C", depends_on=["A"]),
    ]

    decision = StrategyDecision(
        verification_requirements=[
            VerificationRequirement.CONSISTENCY_CHECK
        ]
    )

    report = verify(
        result=ExecutionResult(),
        plan=TaskPlan(tasks=tasks),
        decision=decision,
        proposed_order=["A", "B", "C"],
    )

    assert report.status is VerificationStatus.VERIFIED
    assert report.verified_count == 1


def test_verify_integration_missing_order():
    from cognitive.verification import verify
    from cognitive.executor import ExecutionResult
    from cognitive.planning import TaskPlan
    from cognitive.strategy import (
        StrategyDecision,
        VerificationRequirement,
    )
    from cognitive.state import VerificationStatus

    decision = StrategyDecision(
        verification_requirements=[
            VerificationRequirement.CONSISTENCY_CHECK
        ]
    )

    report = verify(
        result=ExecutionResult(),
        plan=TaskPlan(tasks=[make_task("A")]),
        decision=decision,
    )

    assert report.status is VerificationStatus.INCONCLUSIVE
    assert report.inconclusive_count == 1
    assert report.unverifiable