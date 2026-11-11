"""Planning adapter — Step 6 of the Cognitive Engine.

**This module contains no planning algorithm.** EVA already has one in
`autopilot._make_plan`, and this is the translation layer that lets it consume
Cognitive Engine state. Autopilot stays authoritative for step budget, tool
whitelist, deadline and the LLM boundary; nothing here overrides them.

WHAT THE AUDIT FOUND, AND WHY THE ADAPTER LOOKS LIKE THIS
=========================================================
`_make_plan(goal)` takes a single goal string and returns a flat list of
`{tool, input, why}`. It has no task ids, no dependency edges, no per-task
status, no completion condition and no expected outcome — and `_run_task`
executes the list with a plain `for` loop.

So there is no dependency *mechanism* to reuse: in autopilot, sequential order
IS the dependency. This adapter therefore emits a linear `depends_on` chain,
which is not an invented scheduler but an accurate description of how autopilot
already executes. Claiming a richer graph would misrepresent the executor that
will run it.

Step 2's `PlannedTask` already carries task_id, objective, required_capability,
required_tool, input_requirements, expected_output, verification_criteria,
depends_on, status and attempts — 8 of the 9 fields Step 6 asks for. The ninth,
risk/permission, lives on the `TaskPlan` wrapper rather than per task, because
risk was already computed once by Step 4 and duplicating it onto every task
would let the copies drift. state.py is untouched.

DETERMINISTIC WHERE THE PLAN IS OBVIOUS
=======================================
`_make_plan` always calls `_llm`. For a clarification turn, or "calculate
20 x 30", spending a provider call to be told the obvious is waste — and this
project has exhausted its quota twice. Trivial strategies are built locally.
That is not a second planner: it is declining to invoke the one that exists.

NO EXECUTION. This module produces and validates a plan. It never calls a tool,
never touches the filesystem, database or network, and imports no provider. The
planner function is injected so tests run fully offline.

PLANNING IS NOT AUTHORIZATION. A task naming a tool does not grant permission
to run it; the firewall, execution policy and tool whitelist remain the
authorities at execution time (Step 8).
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Callable, List, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .assessment import AssessmentReport, RiskLevel
from .state import (
    PlannedTask,
    ProblemUnderstanding,
    ReasoningStrategy,
    TaskStatus,
    REASON_MAX,
    redact_secrets,
)
from .strategy import StrategyDecision, VerificationRequirement

# Autopilot is the authority for the step budget and the tool whitelist. Imported
# defensively so the cognitive package still imports where autopilot's optional
# dependencies are unavailable; the fallbacks mirror autopilot's own defaults.
try:
    from autopilot import MAX_STEPS as AUTOPILOT_MAX_STEPS, TOOLS as AUTOPILOT_TOOLS, _make_plan as _autopilot_make_plan
    AUTOPILOT_AVAILABLE = True
except Exception:
    try:
        from src.autopilot import MAX_STEPS as AUTOPILOT_MAX_STEPS, TOOLS as AUTOPILOT_TOOLS, _make_plan as _autopilot_make_plan
        AUTOPILOT_AVAILABLE = True
    except Exception:  # pragma: no cover - exercised only when autopilot cannot import
        AUTOPILOT_MAX_STEPS = 10
        AUTOPILOT_TOOLS = {"web_search": "", "read_url": "", "rag_query": "", "think": ""}
        _autopilot_make_plan = None
        AUTOPILOT_AVAILABLE = False


class PlanSource(str, Enum):
    DETERMINISTIC = "DETERMINISTIC"       # built locally; no model call
    AUTOPILOT_LLM = "AUTOPILOT_LLM"       # produced by autopilot._make_plan
    CLARIFICATION = "CLARIFICATION"       # no work plan; the question goes back


class PlanValidationError(ValueError):
    """A plan that must not be executed. Raised rather than returned so a bad
    plan cannot be silently half-used."""


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class TaskPlan(_Base):
    """Tasks plus the plan-level facts that do not belong on each task.

    `tasks` is a list of Step 2 PlannedTask, so it drops straight into
    CognitiveState.plan through its existing interface.
    """

    tasks: List[PlannedTask] = Field(default_factory=list)
    source: PlanSource = PlanSource.DETERMINISTIC
    # Carried from Step 4 rather than recomputed per task: one assessment, one
    # risk verdict, no copies to drift apart.
    risk_level: RiskLevel = RiskLevel.SAFE
    # True when execution would need an authorization the read-only whitelist
    # does not grant. Advisory: Step 8 and the firewall decide, not this.
    requires_authorization: bool = False
    plan_summary: str = ""

    @field_validator("plan_summary")
    @classmethod
    def _scrub(cls, v: str) -> str:
        return redact_secrets(str(v or ""))[:REASON_MAX]


def _task(objective, capability, tool=None, expected="", criteria=(), depends=(), inputs=()):
    return PlannedTask(
        objective=objective,
        required_capability=capability,
        required_tool=tool,
        input_requirements=list(inputs),
        expected_output=expected,
        verification_criteria=list(criteria),
        depends_on=list(depends),
        status=TaskStatus.PENDING,
    )


def _criteria_for(decision: StrategyDecision) -> List[str]:
    """Completion conditions, taken from the verification requirements Step 5
    already chose. Re-deriving them here would let the two disagree."""
    names = {
        VerificationRequirement.CODE_VALIDATION: "code passes validation",
        VerificationRequirement.EXECUTION_TEST: "code executes without error",
        VerificationRequirement.ARITHMETIC_RECHECK: "result reproduces on recomputation",
        VerificationRequirement.CITATION_CHECK: "claims are supported by cited sources",
        VerificationRequirement.CONSISTENCY_CHECK: "answer is consistent with stated constraints",
        VerificationRequirement.CHART_VALIDATION: "chart spec is valid",
        VerificationRequirement.DIAGRAM_VALIDATION: "diagram renders",
        VerificationRequirement.NONE: "answer addresses the stated outcome",
    }
    return [names[v] for v in decision.verification_requirements if v in names] or \
           ["answer addresses the stated outcome"]


def build_goal(
    understanding: ProblemUnderstanding,
    assessment: AssessmentReport,
    decision: StrategyDecision,
    problem: str = "",
) -> str:
    """The goal string handed to autopilot's planner.

    Targets the DESIRED OUTCOME rather than echoing the user's wording, and
    names the open information needs so the planner's first steps gather them
    instead of assuming them. Repeating "fix this" verbatim would produce a plan
    built on the ambiguity Step 3 flagged.
    """
    parts = [f"Objective: {understanding.desired_outcome or problem or 'answer the question'}"]
    if problem:
        parts.append(f"User request: {problem[:400]}")
    if understanding.constraints:
        parts.append("Constraints: " + "; ".join(understanding.constraints[:5]))
    if assessment.missing_information:
        parts.append("Unknown and must be established first: "
                     + "; ".join(assessment.missing_information[:5]))
    if assessment.evidence_conflicts:
        # Naming the conflict stops the planner producing a plan that assumes
        # one side is true.
        parts.append(f"Note {len(assessment.evidence_conflicts)} contradiction(s) in the evidence "
                     "that must be resolved rather than assumed away")
    parts.append(f"Approach: {decision.strategy.value}")
    return redact_secrets("\n".join(parts))[:1500]


# ── deterministic plans for cases where a model call buys nothing ────────────
def _clarification_plan(understanding: ProblemUnderstanding, decision: StrategyDecision) -> List[PlannedTask]:
    needed = understanding.required_information or ["the missing detail"]
    return [_task(
        objective="ask the user to supply: " + "; ".join(needed[:3]),
        capability="dialogue",
        expected="a reply that resolves the ambiguity",
        criteria=["the user has supplied the missing information"],
        inputs=list(needed[:3]),
    )]


def _direct_plan(understanding: ProblemUnderstanding, decision: StrategyDecision) -> List[PlannedTask]:
    return [_task(
        objective=f"answer directly: {understanding.desired_outcome or 'the question'}",
        capability=(decision.required_capabilities or ["general_reasoning"])[0],
        expected=understanding.desired_outcome or "a direct answer",
        criteria=_criteria_for(decision),
    )]


def _calculation_plan(understanding: ProblemUnderstanding, decision: StrategyDecision) -> List[PlannedTask]:
    a = _task("identify the input values and the operation", "arithmetic",
              expected="the operands and operator",
              criteria=["all operands are identified"])
    b = _task("compute the result", "arithmetic",
              expected="the computed value",
              criteria=["a value is produced"], depends=[a.task_id])
    c = _task("re-check the result independently", "arithmetic",
              expected="a confirmed value",
              criteria=_criteria_for(decision), depends=[b.task_id])
    return [a, b, c]


def _tool_assisted_plan(understanding: ProblemUnderstanding, decision: StrategyDecision, problem: str = "") -> List[PlannedTask]:
    """Select the minimum external tool needed for this request."""
    text = problem or understanding.desired_outcome or ""
    url_match = re.search(r"https?://[^\s]+", text, re.I)
    explicit_search = bool(re.search(r"\b(search|find|look up|latest|current|today|recent|news|price|prices|weather|newest|up[- ]to[- ]date)\b", text, re.I))
    criteria = _criteria_for(decision)
    expected = understanding.desired_outcome or "relevant evidence for the answer"
    if url_match and explicit_search:
        read_task = _task(objective="read the specific URL provided by the user", capability="tool_use", tool="read_url", expected="content from the specified URL", criteria=criteria, inputs=[url_match.group(0)])
        search_task = _task(objective="search the public web for the requested external information", capability="tool_use", tool="web_search", expected=expected, criteria=criteria, depends=(read_task.task_id,), inputs=[text])
        return [read_task, search_task]
    if url_match:
        return [_task(objective="read the specific URL provided by the user", capability="tool_use", tool="read_url", expected=expected, criteria=criteria, inputs=[url_match.group(0)])]
    if explicit_search:
        return [_task(objective="search the public web for the requested external information", capability="tool_use", tool="web_search", expected=expected, criteria=criteria, inputs=[text])]
    return [_task(objective="retrieve relevant information from EVA indexed knowledge", capability="tool_use", tool="rag_query", expected=expected, criteria=criteria, inputs=[text])]

_DETERMINISTIC = {
    ReasoningStrategy.CLARIFICATION: _clarification_plan,
    ReasoningStrategy.DIRECT: _direct_plan,
    ReasoningStrategy.CALCULATION: _calculation_plan,
}


# ── adapting autopilot's flat step list ──────────────────────────────────────
def _adapt_autopilot_steps(steps: Sequence[dict], decision: StrategyDecision) -> List[PlannedTask]:
    """Turn `{tool, input, why}` into PlannedTask with a linear dependency chain.

    The chain mirrors how `_run_task` actually behaves — one step after another
    — rather than inventing parallelism the executor does not have.
    """
    tasks: List[PlannedTask] = []
    previous: Optional[str] = None
    criteria = _criteria_for(decision)
    for index, step in enumerate(steps):
        tool = str((step or {}).get("tool", "")).strip()
        if tool not in AUTOPILOT_TOOLS:
            # Autopilot filters these too; dropping rather than raising keeps a
            # single bad step from discarding an otherwise usable plan.
            continue
        why = str((step or {}).get("why", "")).strip()
        arg = str((step or {}).get("input", "")).strip()
        task = _task(
            objective=(why or f"use {tool}")[:REASON_MAX],
            capability="tool_use",
            tool=tool,
            expected=f"output of {tool}",
            criteria=criteria if index == len(steps) - 1 else [f"{tool} returned usable output"],
            depends=[previous] if previous else [],
            inputs=[arg] if arg else [],
        )
        tasks.append(task)
        previous = task.task_id
    return tasks


def validate_plan(tasks: Sequence[PlannedTask], max_tasks: int = AUTOPILOT_MAX_STEPS) -> None:
    """Structural checks before a plan may be executed.

    Duplicate ids, self-dependency and unresolved dependencies are already
    enforced by CognitiveState's validator; those are re-checked here because a
    plan can be validated before it is ever attached to a state, and an invalid
    plan must not reach Step 8 by that route.
    """
    if not tasks:
        raise PlanValidationError("plan is empty")
    if len(tasks) > max_tasks:
        raise PlanValidationError(f"plan has {len(tasks)} tasks; autopilot MAX_STEPS is {max_tasks}")

    ids = [t.task_id for t in tasks]
    if len(ids) != len(set(ids)):
        raise PlanValidationError("duplicate task_id in plan")
    known = set(ids)

    for task in tasks:
        if not (task.objective or "").strip():
            raise PlanValidationError(f"task {task.task_id} has no objective")
        if not task.verification_criteria:
            raise PlanValidationError(f"task {task.task_id} has no completion condition")
        if task.required_tool and task.required_tool not in AUTOPILOT_TOOLS:
            raise PlanValidationError(
                f"task {task.task_id} requires tool {task.required_tool!r}, "
                f"which is not in autopilot's whitelist"
            )
        for dep in task.depends_on:
            if dep not in known:
                raise PlanValidationError(f"task {task.task_id} depends on unknown task {dep}")
            if dep == task.task_id:
                raise PlanValidationError(f"task {task.task_id} depends on itself")

    # Cycle detection over the declared edges. The linear chain this adapter
    # emits cannot cycle, but a caller-supplied or model-derived plan can.
    colour = {i: 0 for i in ids}
    by_id = {t.task_id: t for t in tasks}

    def visit(node: str) -> None:
        if colour[node] == 1:
            raise PlanValidationError(f"dependency cycle involving {node}")
        if colour[node] == 2:
            return
        colour[node] = 1
        for dep in by_id[node].depends_on:
            visit(dep)
        colour[node] = 2

    for task_id in ids:
        visit(task_id)


def plan_for(
    understanding: ProblemUnderstanding,
    assessment: AssessmentReport,
    decision: StrategyDecision,
    problem: str = "",
    make_plan: Optional[Callable[[str], List[dict]]] = None,
) -> TaskPlan:
    """Produce a validated plan.

    `make_plan` defaults to autopilot's own planner and is injectable so tests
    never reach a provider. Passing a different callable does not introduce a
    second planning algorithm — it substitutes the one boundary that calls a
    model.
    """
    planner = make_plan or _autopilot_make_plan

    requires_auth = assessment.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)

    # Clarification is not a work plan. Producing execution steps here would be
    # planning against information Step 4 said we do not have.
    if decision.strategy is ReasoningStrategy.CLARIFICATION or assessment.clarification_required:
        tasks = _clarification_plan(understanding, decision)
        validate_plan(tasks)
        return TaskPlan(tasks=tasks, source=PlanSource.CLARIFICATION,
                        risk_level=assessment.risk_level,
                        requires_authorization=requires_auth,
                        plan_summary="clarification required before any work can be planned")

    # Conflicting constraints cannot be planned around; pretending otherwise
    # produces a plan that satisfies neither.
    if assessment.constraint_status.value == "CONFLICTING":
        tasks = [_task(
            objective="resolve the conflicting constraints with the user before proceeding",
            capability="dialogue",
            expected="a single consistent set of constraints",
            criteria=["the constraints no longer conflict"],
        )]
        validate_plan(tasks)
        return TaskPlan(tasks=tasks, source=PlanSource.CLARIFICATION,
                        risk_level=assessment.risk_level,
                        requires_authorization=requires_auth,
                        plan_summary="constraints conflict; cannot plan work around them")

    if decision.strategy is ReasoningStrategy.TOOL_ASSISTED:
        tasks = _tool_assisted_plan(understanding, decision, problem)
        validate_plan(tasks)
        return TaskPlan(tasks=tasks, source=PlanSource.DETERMINISTIC, risk_level=assessment.risk_level, requires_authorization=requires_auth, plan_summary="tool-assisted plan built by deterministic tool selection")
    builder = _DETERMINISTIC.get(decision.strategy)
    if builder is not None:
        tasks = builder(understanding, decision)
        validate_plan(tasks)
        return TaskPlan(tasks=tasks, source=PlanSource.DETERMINISTIC,
                        risk_level=assessment.risk_level,
                        requires_authorization=requires_auth,
                        plan_summary=f"{decision.strategy.value.lower()} plan built without a model call")

    # Everything else goes to autopilot's planner.
    if planner is None:
        raise PlanValidationError("autopilot planner unavailable and no make_plan supplied")
    raw = planner(build_goal(understanding, assessment, decision, problem))
    if not isinstance(raw, list):
        raise PlanValidationError("planner did not return a list of steps")

    # A model-produced plan is UNTRUSTED: it is truncated to autopilot's budget,
    # filtered to the whitelist, then structurally validated before it can be
    # executed.
    tasks = _adapt_autopilot_steps(raw[:AUTOPILOT_MAX_STEPS], decision)
    if not tasks:
        raise PlanValidationError("planner produced no usable steps")
    validate_plan(tasks)
    return TaskPlan(tasks=tasks, source=PlanSource.AUTOPILOT_LLM,
                    risk_level=assessment.risk_level,
                    requires_authorization=requires_auth,
                    plan_summary=f"{len(tasks)}-step plan from autopilot planner")


