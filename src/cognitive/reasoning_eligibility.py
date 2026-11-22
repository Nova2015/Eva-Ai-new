
"""Detect whether a chat turn may need structured task-order verification.

This module provides candidate signals only. It does not extract constraints,
interpret dependencies, call an LLM, execute tasks, or prove correctness.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class ReasoningEligibility:
    eligible: bool
    signals: Tuple[str, ...]
    reason: str


_REASONING_SIGNALS = {
    "dependency": (
        "depends on",
        "dependent on",
        "requires both",
        "only after",
        "after both",
        "prerequisite",
        "prerequisites",
        "must be completed before",
        "must happen before",
        "before task",
        "after task",
        " before ",
        " after ",
        "आधी पूर्ण",
        "नंतरच",
        "अवलंबून",
        "पूर्वअट",
    ),
    "execution_order": (
        "execution order",
        "task order",
        "valid order",
        "arrange the tasks",
        "order these tasks",
        "sequence of tasks",
        "क्रम लावा",
        "कामांचा क्रम",
        "कार्यांचा क्रम",
    ),
    "order_count": (
        "how many valid",
        "count all valid",
        "number of possible orders",
        "total possible orders",
        "किती क्रम",
        "एकूण शक्य क्रम",
        "सर्व शक्य क्रम",
    ),
}


def is_reasoning_eligible(question: str) -> ReasoningEligibility:
    """Return candidate task-order signals found in the user's question."""

    if not isinstance(question, str) or not question.strip():
        return ReasoningEligibility(
            eligible=False,
            signals=(),
            reason="empty_or_invalid_question",
        )

    text = question.casefold()

    matched = tuple(
        f"{category}:{phrase.strip()}"
        for category, phrases in _REASONING_SIGNALS.items()
        for phrase in phrases
        if phrase.casefold() in text
    )

    if not matched:
        return ReasoningEligibility(
            eligible=False,
            signals=(),
            reason="no_task_order_signals_found",
        )

    return ReasoningEligibility(
        eligible=True,
        signals=matched,
        reason="possible_task_order_constraints",
    )
