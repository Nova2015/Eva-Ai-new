from types import SimpleNamespace
import pytest
from cognitive.task_order_validator import validate_execution_order


def make_tasks():
    return [
        SimpleNamespace(task_id="A", depends_on=[]),
        SimpleNamespace(task_id="B", depends_on=["A"]),
        SimpleNamespace(task_id="C", depends_on=["A"]),
        SimpleNamespace(task_id="D", depends_on=["B", "C", "E"]),
        SimpleNamespace(task_id="E", depends_on=[]),
    ]


def test_sample_has_exactly_eight_valid_orders():
    report = validate_execution_order(make_tasks())

    assert report.valid is True
    assert report.order_count == 8
    assert report.count_exact is True
    assert len(report.valid_order) == 5


def test_valid_proposed_order_is_accepted():
    report = validate_execution_order(
        make_tasks(),
        proposed_order=["A", "B", "C", "E", "D"],
    )

    assert report.valid is True
    assert report.errors == ()


def test_invalid_proposed_order_is_rejected():
    report = validate_execution_order(
        make_tasks(),
        proposed_order=["B", "A", "C", "E", "D"],
    )

    assert report.valid is False
    assert any("A must execute before B" in e for e in report.errors)


def test_another_valid_order_is_accepted():
    report = validate_execution_order(
        make_tasks(),
        proposed_order=["E", "A", "C", "B", "D"],
    )

    assert report.valid is True


def test_missing_task_is_rejected():
    report = validate_execution_order(
        make_tasks(),
        proposed_order=["A", "B", "C", "D"],
    )

    assert report.valid is False
    assert any("missing tasks" in e for e in report.errors)


def test_duplicate_task_id_is_rejected():
    tasks = [
        SimpleNamespace(task_id="A", depends_on=[]),
        SimpleNamespace(task_id="A", depends_on=[]),
    ]

    report = validate_execution_order(tasks)

    assert report.valid is False
    assert any("Duplicate task_id" in e for e in report.errors)


def test_unknown_dependency_is_rejected():
    tasks = [
        SimpleNamespace(task_id="A", depends_on=["MISSING"]),
    ]

    report = validate_execution_order(tasks)

    assert report.valid is False
    assert any("unknown task" in e for e in report.errors)


def test_dependency_cycle_is_detected():
    tasks = [
        SimpleNamespace(task_id="A", depends_on=["B"]),
        SimpleNamespace(task_id="B", depends_on=["A"]),
    ]

    report = validate_execution_order(tasks)

    assert report.valid is False
    assert report.order_count == 0
    assert any("cycle" in e.lower() for e in report.errors)


def test_empty_task_list_is_rejected():
    report = validate_execution_order([])

    assert report.valid is False
    assert report.order_count == 0


def test_count_is_not_claimed_above_limit():
    tasks = [
        SimpleNamespace(task_id=f"T{i}", depends_on=[])
        for i in range(17)
    ]

    report = validate_execution_order(tasks)

    assert report.valid is True
    assert report.count_exact is False
    assert report.order_count is None
    assert len(report.valid_order) == 17

def test_string_dependencies_are_rejected():
    tasks = [SimpleNamespace(task_id="A", depends_on="ABC")]
    report = validate_execution_order(tasks)
    assert not report.valid
    assert any("invalid dependencies" in e for e in report.errors)


def test_empty_dependency_id_is_rejected():
    tasks = [SimpleNamespace(task_id="A", depends_on=[""])]
    report = validate_execution_order(tasks)
    assert not report.valid
    assert any("empty dependency ID" in e for e in report.errors)


def test_string_proposed_order_is_rejected():
    with pytest.raises(TypeError):
        validate_execution_order(make_tasks(), proposed_order="ABCDE")


def test_non_string_proposed_task_id_is_rejected():
    report = validate_execution_order(
        make_tasks(), proposed_order=["A", "B", "C", "E", 123]
    )
    assert not report.valid
    assert any("only string task IDs" in e for e in report.errors)


def test_zero_count_limit_is_rejected():
    with pytest.raises(ValueError):
        validate_execution_order(make_tasks(), max_count_tasks=0)


def test_count_limit_above_maximum_is_rejected():
    with pytest.raises(ValueError):
        validate_execution_order(make_tasks(), max_count_tasks=17)


def test_boolean_count_limit_is_rejected():
    with pytest.raises(TypeError):
        validate_execution_order(make_tasks(), max_count_tasks=True)

