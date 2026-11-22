"""Deterministic validator for task dependency ordering.

This module validates structured task IDs and depends_on edges.
It deliberately does not parse natural-language instructions.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Optional, Sequence, Tuple



@dataclass(frozen=True)
class TaskOrderReport:
    valid: bool
    errors: Tuple[str, ...]
    valid_order: Tuple[str, ...]
    order_count: Optional[int]
    count_exact: bool


def validate_execution_order(
    tasks: Sequence,
    proposed_order: Optional[Sequence[str]] = None,
    max_count_tasks: int = 16,
) -> TaskOrderReport:
    """Validate a proposed order and count all valid topological orders.

    Each task must expose:
      - task_id: unique string
      - depends_on: iterable of task IDs that must execute first

    If proposed_order is omitted, the validator returns one valid order.
    """
        # Validate function arguments before processing tasks.
    if not isinstance(max_count_tasks, int) or isinstance(max_count_tasks, bool):
        raise TypeError("max_count_tasks must be an integer.")

    if not 1 <= max_count_tasks <= 16:
        raise ValueError("max_count_tasks must be between 1 and 16.")

    if isinstance(tasks, (str, bytes)) or not isinstance(tasks, Sequence):
        raise TypeError("tasks must be a sequence of task objects.")

    if proposed_order is not None:
        if isinstance(proposed_order, (str, bytes)):
            raise TypeError("proposed_order must be a sequence of task IDs.")
        if not isinstance(proposed_order, Sequence):
            raise TypeError("proposed_order must be a sequence of task IDs.")

    errors = []
    ids = []

    for task in tasks:
        raw_task_id = getattr(task, "task_id", None)

        if not isinstance(raw_task_id, str):
            errors.append("A task has a non-string task_id.")
            ids.append("")
            continue

        task_id = raw_task_id.strip()

        if not task_id:
            errors.append("A task has an empty task_id.")

        ids.append(task_id)

    if not ids:
        return TaskOrderReport(
            valid=False,
            errors=("Task list is empty.",),
            valid_order=(),
            order_count=0,
            count_exact=True,
        )

    if len(ids) != len(set(ids)):
        errors.append("Duplicate task_id values were found.")

    known = set(ids)
    dependencies = {}

    for task in tasks:
        task_id = str(getattr(task, "task_id", "") or "").strip()
        raw_deps = getattr(task, "depends_on", ())

        if raw_deps is None:
            raw_deps = ()

        if isinstance(raw_deps, (str, bytes)) or not isinstance(
            raw_deps, (list, tuple, set)
        ):
            errors.append(
                f"Task {task_id} has invalid dependencies: "
                "expected a list, tuple, or set of task IDs."
            )
            continue

        if not all(isinstance(dep, str) for dep in raw_deps):
            errors.append(
                f"Task {task_id} has a non-string dependency ID."
            )
            continue

        deps = tuple(dep.strip() for dep in raw_deps)

        if any(not dep for dep in deps):
            errors.append(f"Task {task_id} contains an empty dependency ID.")
        if len(deps) != len(set(deps)):
            errors.append(f"Task {task_id} contains duplicate dependencies.")

        for dep in deps:
            if dep not in known:
                errors.append(
                    f"Task {task_id} depends on unknown task {dep}."
                )
            elif dep == task_id:
                errors.append(f"Task {task_id} depends on itself.")

        dependencies[task_id] = deps

        if raw_deps is None:
            raw_deps = ()

        if isinstance(raw_deps, (str, bytes)) or not isinstance(
            raw_deps, (list, tuple, set)
        ):
            errors.append(
                f"Task {task_id} has invalid dependencies: "
                "expected a list, tuple, or set of task IDs."
            )
            continue

        if isinstance(raw_deps, (str, bytes)):
            errors.append(
                f"Task {task_id} has invalid dependencies: expected a sequence of task IDs."
            )
            continue

        try:
            deps = tuple(str(dep).strip() for dep in raw_deps)
        except TypeError:
            errors.append(
                f"Task {task_id} has invalid dependencies: expected an iterable of task IDs."
            )
            continue

        if any(not dep for dep in deps):
            errors.append(f"Task {task_id} contains an empty dependency ID.")
        if len(deps) != len(set(deps)):
            errors.append(f"Task {task_id} contains duplicate dependencies.")

        for dep in deps:
            if dep not in known:
                errors.append(
                    f"Task {task_id} depends on unknown task {dep}."
                )
            elif dep == task_id:
                errors.append(f"Task {task_id} depends on itself.")

        dependencies[task_id] = deps

    if errors:
        return TaskOrderReport(
            valid=False,
            errors=tuple(errors),
            valid_order=(),
            order_count=None,
            count_exact=False,
        )

    # Convert dependencies into bit masks.
    index = {task_id: i for i, task_id in enumerate(ids)}
    n = len(ids)
    prereq_masks = [0] * n

    for task_id, deps in dependencies.items():
        mask = 0
        for dep in deps:
            mask |= 1 << index[dep]
        prereq_masks[index[task_id]] = mask

    full_mask = (1 << n) - 1

    @lru_cache(maxsize=None)
    def count_orders(done_mask: int) -> int:
        if done_mask == full_mask:
            return 1

        total = 0
        for i in range(n):
            bit = 1 << i
            if done_mask & bit:
                continue
            if prereq_masks[i] & ~done_mask:
                continue
            total += count_orders(done_mask | bit)

        return total

    # Construct one deterministic valid order.
    done = 0
    one_order = []

    while done != full_mask:
        selected = None

        for i, task_id in enumerate(ids):
            bit = 1 << i
            if done & bit:
                continue
            if prereq_masks[i] & ~done:
                continue
            selected = i
            break

        if selected is None:
            break

        done |= 1 << selected
        one_order.append(ids[selected])

    count_exact = n <= max_count_tasks
    total_orders = count_orders(0) if count_exact else None

    if len(one_order) != n:
        return TaskOrderReport(
            valid=False,
            errors=("Dependency cycle detected; no valid execution order exists.",),
            valid_order=(),
            order_count=0 if count_exact else None,
            count_exact=count_exact,
        )

    if proposed_order is not None:
        if any(not isinstance(item, str) for item in proposed_order):
            errors.append("Proposed order must contain only string task IDs.")
            proposed = []
        else:
            proposed = [item.strip() for item in proposed_order]

        if any(not item for item in proposed):
            errors.append("Proposed order contains an empty task ID.")

        if len(proposed) != len(set(proposed)):
            errors.append("Proposed order contains duplicate task IDs.")

        if set(proposed) != known:
            missing = sorted(known - set(proposed))
            unknown = sorted(set(proposed) - known)

            if missing:
                errors.append("Proposed order is missing tasks: " + ", ".join(missing))
            if unknown:
                errors.append("Proposed order contains unknown tasks: " + ", ".join(unknown))

        positions = {task_id: i for i, task_id in enumerate(proposed)}

        for task_id, deps in dependencies.items():
            if task_id not in positions:
                continue
            for dep in deps:
                if dep in positions and positions[dep] > positions[task_id]:
                    errors.append(
                        f"Invalid order: {dep} must execute before {task_id}."
                    )

    return TaskOrderReport(
        valid=not errors,
        errors=tuple(errors),
        valid_order=tuple(one_order),
        order_count=total_orders if count_exact else None,
        count_exact=count_exact,
    )

