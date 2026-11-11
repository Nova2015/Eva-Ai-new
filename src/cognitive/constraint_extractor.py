
"""Extract structured task dependencies from natural-language constraints.

The LLM is injected as llm(prompt) -> str.
This module never imports a model provider and never executes tasks.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from .state import PlannedTask
from .task_order_validator import validate_execution_order


@dataclass(frozen=True)
class ConstraintExtraction:
    """Validated structured constraints; not proof of correctness."""

    tasks: Tuple[PlannedTask, ...]
    proposed_order: Optional[Tuple[str, ...]]
    proposed_order_count: Optional[int]
    ambiguities: Tuple[str, ...]
    confidence: float
    extraction_valid: bool
    errors: Tuple[str, ...]


_EXTRACTION_PROMPT = """Analyze the user's task-order constraints and
the assistant's proposed answer. Convert them into ONE JSON object.

Required JSON keys:
{
  "tasks": [
    {"task_id": "A", "depends_on": []},
    {"task_id": "B", "depends_on": ["A"]}
  ],
  "proposed_order": ["A", "B"],
  "proposed_order_count": 1,
  "ambiguities": [],
  "confidence": 0.0
}

Rules:
- Extract proposed_order_count from the ASSISTANT ANSWER only.
- proposed_order_count must be null if the answer does not explicitly state a total count.
- Extract tasks and dependencies from the USER QUESTION only.
- Represent every task exactly once.
- If A must happen before B, B depends_on must include A.
- If C requires both A and B, C depends_on must include both.
- Include only explicitly stated dependencies.
- Do not invent tasks or dependencies.
- Extract proposed_order from the ASSISTANT ANSWER only.
- proposed_order must be null if no execution order is proposed.
- If task identity or a dependency is unclear, describe it in ambiguities.
- If the answer contains multiple conflicting proposed orders, describe that in ambiguities.
- confidence must be between 0 and 1.
- Do not treat confidence as proof of semantic correctness.
- Do not explain your reasoning.
- Return JSON only.

USER QUESTION:
{question}

ASSISTANT ANSWER:
{answer}

Return the JSON object now.
"""

def _parse_json(raw: str) -> Optional[dict]:
    """Parse one JSON object; reject malformed or non-object replies."""
    if not isinstance(raw, str) or not raw.strip():
        return None

    text = raw.strip()

    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    else:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return None
        text = match.group(0)

    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None

    return value if isinstance(value, dict) else None


def _validate_payload(payload: dict) -> ConstraintExtraction:
    """Validate the extractor's output before creating task objects."""

    errors = []
    ambiguities = payload.get("ambiguities")
    confidence = payload.get("confidence")
    raw_tasks = payload.get("tasks")
    raw_order = payload.get("proposed_order")
    raw_order_count = payload.get("proposed_order_count")

    if not isinstance(ambiguities, list) or not all(
        isinstance(item, str) and item.strip()
        for item in ambiguities
    ):
        errors.append("ambiguities must be a list of non-empty strings")
        ambiguities = []

    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0.0 <= confidence <= 1.0
    ):
        errors.append("confidence must be a number between 0 and 1")
        confidence = 0.0

    if not isinstance(raw_tasks, list) or not raw_tasks:
        errors.append("tasks must be a non-empty list")
        raw_tasks = []
    if isinstance(raw_tasks, list) and len(raw_tasks) > 16:
        errors.append("tasks cannot contain more than 16 items")

    tasks = []
    seen_ids = set()

    for index, item in enumerate(raw_tasks):
        if not isinstance(item, dict):
            errors.append(f"task at index {index} must be an object")
            continue

        task_id = item.get("task_id")
        dependencies = item.get("depends_on")

        if not isinstance(task_id, str) or not task_id.strip():
            errors.append(f"task at index {index} has an invalid task_id")
            continue

        task_id = task_id.strip()

        if task_id in seen_ids:
            errors.append(f"duplicate task_id: {task_id}")
            continue

        seen_ids.add(task_id)

        if (
            not isinstance(dependencies, list)
            or not all(
                isinstance(dep, str) and dep.strip()
                for dep in dependencies
            )
        ):
            errors.append(f"invalid dependencies for task {task_id}")
            continue

        dependencies = [dep.strip() for dep in dependencies]

        tasks.append(
            PlannedTask(
                task_id=task_id,
                objective=f"Complete task {task_id}",
                verification_criteria=["task completed"],
                depends_on=dependencies,
            )
        )
    proposed_order_count = None

    if raw_order_count is not None:
        if (
            isinstance(raw_order_count, bool)
            or not isinstance(raw_order_count, int)
            or raw_order_count < 0
        ):
            errors.append(
                "proposed_order_count must be null or a non-negative integer"
            )
        else:
            proposed_order_count = raw_order_count

    proposed_order = None

    if raw_order is not None:
        if (
            not isinstance(raw_order, list)
            or not all(
                isinstance(item, str) and item.strip()
                for item in raw_order
            )
        ):
            errors.append("proposed_order must be null or a list of task IDs")
        else:
            proposed_order = tuple(item.strip() for item in raw_order)

    if ambiguities:
        errors.append("constraint extraction contains unresolved ambiguities")

        
    if not errors:
        # Validate only the extracted task graph here.
        # Proposed-order validation belongs to the consistency adapter.
        graph = validate_execution_order(
            tasks=tasks,
        )
        if graph.errors:
            errors.extend(graph.errors)

    return ConstraintExtraction(
        tasks=tuple(tasks),
        proposed_order=proposed_order,
        proposed_order_count=proposed_order_count,
        ambiguities=tuple(ambiguities),
        confidence=float(confidence),
        extraction_valid=not errors,
        errors=tuple(errors),
    )

def extract_constraints(
    question: str,
    answer: str,
    llm: Optional[Callable[[str], str]] = None,
) -> ConstraintExtraction:
    """Extract constraints from the question and proposed order from the answer.

    This function never executes tasks. If extraction is unavailable,
    malformed, ambiguous, or structurally invalid, it fails closed.
    """

    def failed(reason: str) -> ConstraintExtraction:
        return ConstraintExtraction(
            tasks=(),
            proposed_order=None,
            proposed_order_count=None,
            ambiguities=(),
            confidence=0.0,
            extraction_valid=False,
            errors=(reason,),
        )

    if not isinstance(question, str) or not question.strip():
        return failed("user question is empty or invalid")

    if not isinstance(answer, str) or not answer.strip():
        return failed("assistant answer is empty or invalid")

    if llm is None:
        return failed("no LLM callback was supplied")

    prompt = (
        _EXTRACTION_PROMPT
        .replace("{question}", question.strip()[:4000])
        .replace("{answer}", answer.strip()[:4000])
    )

    try:
        raw = llm(prompt)
    except Exception:
        return failed("LLM provider failed during constraint extraction")

    payload = _parse_json(raw)
    if payload is None:
        return failed("LLM returned malformed JSON")

    required_keys = {
        "tasks",
        "proposed_order",
        "proposed_order_count",
        "ambiguities",
        "confidence",
    }
    missing = required_keys.difference(payload.keys())

    if missing:
        return failed(
            "LLM response is missing required keys: "
            + ", ".join(sorted(missing))
        )

    try:
        return _validate_payload(payload)
    except Exception:
        return failed("constraint payload validation failed")