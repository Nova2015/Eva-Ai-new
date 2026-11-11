
"""Orchestrate structured reasoning verification.

Flow:
    eligibility -> constraint extraction -> deterministic verification

This module does not execute tasks, generate answers, or modify chat_bridge.
The LLM is injected by the caller. All failures fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from .consistency_adapter import verify_task_order_consistency
from .constraint_extractor import (
    ConstraintExtraction,
    extract_constraints,
)
from .reasoning_eligibility import (
    ReasoningEligibility,
    is_reasoning_eligible,
)
from .state import VerificationResult, VerificationStatus


@dataclass(frozen=True)
class ReasoningVerification:
    """Complete result of one structured reasoning verification attempt."""

    eligibility: ReasoningEligibility
    extraction: Optional[ConstraintExtraction]
    verification: VerificationResult
    attempted: bool


def _inconclusive(reason: str) -> VerificationResult:
    return VerificationResult(
        status=VerificationStatus.INCONCLUSIVE,
        verification_type="TASK_ORDER_CONSISTENCY",
        criteria=[
            "Natural-language constraints must be extracted unambiguously",
            "Structured task dependencies must pass deterministic validation",
            "The assistant's proposed order must be independently verified",
        ],
        failure_reason=reason,
        confidence=0.0,
    )


def verify_reasoning_answer(
    question: str,
    answer: str,
    llm: Optional[Callable[[str], str]] = None,
) -> ReasoningVerification:
    """Verify a proposed task order when the question appears relevant.

    Args:
        question: Original user question.
        answer: Assistant's already-generated answer.
        llm: Injected callback accepting an extraction prompt and returning
             a JSON string.

    Returns:
        ReasoningVerification containing eligibility, extraction and
        deterministic verification results.

    Important:
        - Ineligible questions do not trigger an LLM call.
        - Missing LLM callbacks fail closed.
        - Ambiguous or invalid extraction is INCONCLUSIVE.
        - Only the deterministic adapter can return VERIFIED.
        - No tasks are executed or marked completed here.
    """

    eligibility = is_reasoning_eligible(question)

    if not eligibility.eligible:
        return ReasoningVerification(
            eligibility=eligibility,
            extraction=None,
            verification=_inconclusive(
                "Question did not match task-order reasoning signals."
            ),
            attempted=False,
        )

    if not isinstance(answer, str) or not answer.strip():
        return ReasoningVerification(
            eligibility=eligibility,
            extraction=None,
            verification=_inconclusive(
                "Assistant answer is empty or invalid."
            ),
            attempted=False,
        )

    if llm is None:
        return ReasoningVerification(
            eligibility=eligibility,
            extraction=None,
            verification=_inconclusive(
                "No LLM callback was supplied for constraint extraction."
            ),
            attempted=False,
        )

    extraction = extract_constraints(
        question=question,
        answer=answer,
        llm=llm,
    )

    if not extraction.extraction_valid:
        return ReasoningVerification(
            eligibility=eligibility,
            extraction=extraction,
            verification=_inconclusive(
                "Constraint extraction failed: "
                + "; ".join(extraction.errors)
            ),
            attempted=True,
        )

    if extraction.ambiguities:
        return ReasoningVerification(
            eligibility=eligibility,
            extraction=extraction,
            verification=_inconclusive(
                "Ambiguous task constraints: "
                + "; ".join(extraction.ambiguities)
            ),
            attempted=True,
        )

    if not extraction.tasks:
        return ReasoningVerification(
            eligibility=eligibility,
            extraction=extraction,
            verification=_inconclusive(
                "No structured tasks were extracted."
            ),
            attempted=True,
        )

    try:
        verification = verify_task_order_consistency(
            tasks=extraction.tasks,
            proposed_order=extraction.proposed_order,
            proposed_order_count=extraction.proposed_order_count,
        )
    except Exception:
        # Unexpected errors must never become a VERIFIED result.
        verification = _inconclusive(
            "Unexpected error during deterministic consistency verification."
        )

    return ReasoningVerification(
        eligibility=eligibility,
        extraction=extraction,
        verification=verification,
        attempted=True,
    )
