"""Adapter between structured task-order validation and cognitive verification."""

from typing import Optional, Sequence

from .state import PlannedTask, VerificationResult, VerificationStatus
from .task_order_validator import validate_execution_order


def verify_task_order_consistency(
    tasks: Sequence[PlannedTask],
    proposed_order: Optional[Sequence[str]],
    proposed_order_count: Optional[int] = None,
) -> VerificationResult:
    """Verify an explicitly structured execution order.

    This adapter does not extract constraints from natural language.
    """

    criteria = [
        "Every task appears exactly once",
        "Every dependency executes before its dependent task",
        "All task IDs and dependency references are valid",
    ]
    if proposed_order_count is not None and (
        isinstance(proposed_order_count, bool)
        or not isinstance(proposed_order_count, int)
        or proposed_order_count < 0
    ):
        return VerificationResult(
            status=VerificationStatus.INCONCLUSIVE,
            verification_type="TASK_ORDER_CONSISTENCY",
            criteria=criteria,
            failure_reason=(
                "Invalid proposed_order_count; "
                "expected a non-negative integer or None."
            ),
            confidence=0.0,
        )

    try:
        # Validate the dependency graph independently first.
        graph_report = validate_execution_order(
            tasks=tasks,
            proposed_order=None,
        )

        if graph_report.errors:
            return VerificationResult(
                status=VerificationStatus.INCONCLUSIVE,
                verification_type="TASK_ORDER_CONSISTENCY",
                criteria=criteria,
                failure_reason="Invalid dependency graph: "
                + "; ".join(graph_report.errors),
                confidence=0.0,
            )

        if proposed_order is None:
            return VerificationResult(
                status=VerificationStatus.INCONCLUSIVE,
                verification_type="TASK_ORDER_CONSISTENCY",
                criteria=criteria,
                failure_reason=(
                    "No proposed order was supplied; "
                    "only a valid order was generated."
                ),
                confidence=0.0,
            )

        # Only evaluate the proposed answer after graph validation passes.
        report = validate_execution_order(
            tasks=tasks,
            proposed_order=proposed_order,
        )

    except (TypeError, ValueError) as exc:
        return VerificationResult(
            status=VerificationStatus.INCONCLUSIVE,
            verification_type="TASK_ORDER_CONSISTENCY",
            criteria=criteria,
            failure_reason=f"Invalid verification input: {exc}",
            confidence=0.0,
        )

    if report.errors:
        return VerificationResult(
            status=VerificationStatus.FAILED,
            verification_type="TASK_ORDER_CONSISTENCY",
            criteria=criteria,
            failure_reason="; ".join(report.errors),
            confidence=0.0,
        )

    if proposed_order_count is not None:
        if not report.count_exact:
            return VerificationResult(
                status=VerificationStatus.INCONCLUSIVE,
                verification_type="TASK_ORDER_CONSISTENCY",
                criteria=criteria,
                failure_reason=(
                    "Exact valid-order count is unavailable; "
                    "cannot verify the assistant's stated count."
                ),
                confidence=0.0,
            )

        if proposed_order_count != report.order_count:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                verification_type="TASK_ORDER_CONSISTENCY",
                criteria=criteria,
                failure_reason=(
                    f"Incorrect valid-order count: assistant stated "
                    f"{proposed_order_count}, but validator calculated "
                    f"{report.order_count}."
                ),
                confidence=0.0,
            )

        criteria.append(
            f"Assistant's stated order count matches exact count: "
            f"{report.order_count}"
        )

    if report.count_exact:
        criteria.append(
            f"Exact number of valid execution orders: {report.order_count}"
        )

    return VerificationResult(
        status=VerificationStatus.VERIFIED,
        verification_type="TASK_ORDER_CONSISTENCY",
        criteria=criteria,
        failure_reason=None,
        confidence=1.0,
    )
