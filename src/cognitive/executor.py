"""Execution orchestration — Step 8 of the Cognitive Engine.

Runs the validated plan through EVA's EXISTING execution infrastructure. This
module contains no sandbox, no retry counter, no timeout implementation and no
tool of its own — those exist in `autopilot` and `runtime_engine`, and building
a second set would give the system two budgets that drift apart.

WHAT THIS ADDS
==============
Ordering, gating and bookkeeping:

    dependency order  -> a task waits for what it declared
    capability gate   -> a task may only use what Step 7 approved for it
    whitelist gate    -> a tool must be in autopilot's read-only whitelist
    budget gate       -> autopilot's MAX_STEPS and DEADLINE_SECONDS, unchanged
    observation       -> a sanitised, structured record of what happened
    reassessment      -> hand new evidence back to the state graph

ADAPTERS ARE INJECTED, AND THERE IS NO DEFAULT
==============================================
`run_plan` refuses to execute unless an adapter is supplied. That is a
deliberate reversal of the pattern used in Steps 3-7, where a missing optional
callable degrades quietly to a deterministic path.

Silence is the right failure mode for an assist that only improves an answer.
It is the wrong one for execution: an executor that "runs" a plan while
actually doing nothing would report success for work that never happened. The
Step 6 adapter has this weakness — it falls back to no planner when autopilot
cannot import — and it is the one thing from that step I would not repeat here.

TWO BACKEND SHAPES
==================
autopilot._run_tool(tool, arg, context) -> str        synchronous
runtime_engine.execute_code(language, code) -> dict   ASYNCHRONOUS

The adapter protocol here is synchronous. Wrapping the async one is the
caller's job at wiring time, because creating an event loop inside a library
function is how you deadlock a server that already has one running.

NO FINAL ANSWER. This produces execution evidence. Verification is Step 9,
correction Step 10, learning Step 11, and the user-facing response is none of
them.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Callable, Dict, List, Optional, Protocol, Sequence, Set

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .capabilities import Capability, CapabilitySelection
from .planning import TaskPlan
from .state import (
    ActionRecord,
    CognitiveError,
    CognitivePhase,
    CognitiveState,
    FailureCategory,
    Observation,
    PlannedTask,
    TaskStatus,
    REASON_MAX,
    redact_secrets,
)

# Limits and the whitelist come from autopilot. Imported strictly — unlike the
# Step 6 adapter, a missing autopilot here must not silently produce a
# permissive executor.
try:
    from autopilot import (
        MAX_STEPS as AUTOPILOT_MAX_STEPS,
        DEADLINE_SECONDS as AUTOPILOT_DEADLINE_SECONDS,
        TOOL_TIMEOUT as AUTOPILOT_TOOL_TIMEOUT,
        TOOLS as AUTOPILOT_TOOLS,
    )
    AUTOPILOT_AVAILABLE = True
except Exception:  # pragma: no cover
    AUTOPILOT_MAX_STEPS = 10
    AUTOPILOT_DEADLINE_SECONDS = 300
    AUTOPILOT_TOOL_TIMEOUT = 25
    AUTOPILOT_TOOLS = {"web_search": "", "read_url": "", "rag_query": "", "think": ""}
    AUTOPILOT_AVAILABLE = False


class ExecutionStatus(str, Enum):
    """Terminal state of one run. Step 9 decides what to do next."""

    EXECUTION_COMPLETE = "EXECUTION_COMPLETE"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    REASSESS_REQUIRED = "REASSESS_REQUIRED"
    CANCELLED = "CANCELLED"


# Which failure categories are EVIDENCE that the plan, its assumptions or its
# expected outcome may be wrong — and therefore justify reassessing.
#
# The distinction matters more than it looks. A tool that failed or overran its
# budget tells us something about the problem: the plan expected it to work, or
# to fit, and it did not. A policy refusal tells us nothing about the problem at
# all — reassessing cannot make a forbidden tool permitted, so treating a denial
# as evidence sends the engine round ACT -> ASSESS -> STRATEGY -> PLAN -> ACT
# into the same wall, burning transition budget. A loop that keeps re-planning
# around a security block is also exactly the shape of a bypass attempt, which
# is not a behaviour to build in at the point where execution begins.
_EVIDENCE_CATEGORIES = frozenset({
    FailureCategory.TOOL_FAILURE,
    FailureCategory.EXECUTION_FAILURE,
    FailureCategory.INVALID_INPUT,
    FailureCategory.MODEL_FAILURE,
    FailureCategory.TIMEOUT,          # the plan assumed it would fit the budget
})

# Refusals. Recorded, never treated as evidence, never retried here.
_DENIAL_CATEGORIES = frozenset({
    FailureCategory.SECURITY_BLOCK,
    FailureCategory.UNSUPPORTED_TASK,
})


class ExecutionDenied(Exception):
    """A gate refused. Raised internally, never surfaced to a user."""


class PolicyDenied(ExecutionDenied):
    """Authorization or security refused: the task must not run.

    Separate from a structural refusal (an incomplete dependency) because the
    two mean opposite things for reassessment — see _EVIDENCE_CATEGORIES.
    """


def cancellation_check(run_id: Optional[str]) -> Callable[[], bool]:
    """Cooperative cancellation, read from AUTOPILOT'S OWN registry.

    autopilot keeps a module-level `_cancelled` set of run ids, adds to it in
    its /tasks/{id}/cancel route and checks it between steps. This binds that
    same set — it is mutated in place, never rebound, so the binding sees live
    cancellations — rather than introducing a second mechanism that could
    disagree with the one the API already drives.

    Returns a predicate that is always False when no run_id is supplied or
    autopilot is unavailable: absent a cancellation channel, nothing is
    cancelled.
    """
    if not run_id or not AUTOPILOT_AVAILABLE:
        return lambda: False
    try:
        from autopilot import _cancelled
    except Exception:  # pragma: no cover
        return lambda: False
    return lambda: run_id in _cancelled


class ToolAdapter(Protocol):
    """Synchronous. Mirrors autopilot._run_tool's signature exactly so the real
    one can be passed with no wrapper."""

    def __call__(self, tool: str, arg: str, context: str) -> str: ...


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class TaskOutcome(_Base):
    """§11's per-task record. Built from Step 2's vocabulary rather than a new
    one: FailureCategory and TaskStatus already exist and are already used by
    the correction stage that will read these."""

    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_ms: Optional[int] = None
    success: bool = False
    error_category: Optional[FailureCategory] = None
    safe_summary: str = ""
    verification_required: bool = False

    @field_validator("safe_summary")
    @classmethod
    def _scrub(cls, v: str) -> str:
        return redact_secrets(str(v or ""))[:REASON_MAX]


class ExecutionResult(_Base):
    success: bool = False
    completed_tasks: List[str] = Field(default_factory=list)
    # Ran and genuinely failed. Kept apart from denied/cancelled/blocked so
    # "the plan's premise broke" cannot be confused with "policy said no".
    failed_tasks: List[str] = Field(default_factory=list)
    denied_tasks: List[str] = Field(default_factory=list)
    cancelled_tasks: List[str] = Field(default_factory=list)
    skipped_tasks: List[str] = Field(default_factory=list)
    outcomes: List[TaskOutcome] = Field(default_factory=list)
    observations: List[Observation] = Field(default_factory=list)
    actions: List[ActionRecord] = Field(default_factory=list)
    errors: List[CognitiveError] = Field(default_factory=list)
    requires_reassessment: bool = False
    requires_verification: bool = False
    final_execution_status: ExecutionStatus = ExecutionStatus.EXECUTION_FAILED

    def outcome_for(self, task_id: str) -> Optional[TaskOutcome]:
        return next((o for o in self.outcomes if o.task_id == task_id), None)


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _safe_error(exc: BaseException) -> str:
    """A category and a short message — never a traceback, never the raw
    exception text, which routinely carries paths, URLs and credentials."""
    return f"{type(exc).__name__}"


def _classify(exc: BaseException) -> FailureCategory:
    name = type(exc).__name__.lower()
    if isinstance(exc, TimeoutError) or "timeout" in name:
        return FailureCategory.TIMEOUT
    if isinstance(exc, ExecutionDenied):
        return FailureCategory.SECURITY_BLOCK
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return FailureCategory.INVALID_INPUT
    return FailureCategory.TOOL_FAILURE


def _ordered(tasks: Sequence[PlannedTask]) -> List[PlannedTask]:
    """Dependency order. The plan's own validation already rejected cycles, so
    a task whose dependencies never resolve is left for the caller to see as
    SKIPPED rather than silently dropped."""
    remaining = list(tasks)
    done: Set[str] = set()
    ordered: List[PlannedTask] = []
    while remaining:
        progressed = False
        for task in list(remaining):
            if set(task.depends_on) <= done:
                ordered.append(task)
                done.add(task.task_id)
                remaining.remove(task)
                progressed = True
        if not progressed:
            ordered.extend(remaining)     # unreachable deps; surfaced later
            break
    return ordered


def _gate(
    task: PlannedTask,
    selection: CapabilitySelection,
    completed: Set[str],
    failed: Set[str],
) -> None:
    """Every reason a task may not run.

    Two exception types, and the difference is the whole point of this fix:

      PolicyDenied     authorization/security said no. Not evidence about the
                       problem, so it must not drive reassessment.
      ExecutionDenied  a structural reason — a dependency has not completed, or
                       the task is not PENDING. Downstream of something else.
    """
    if task.status is not TaskStatus.PENDING:
        raise ExecutionDenied(f"task is {task.status.value}, not PENDING")

    for dep in task.depends_on:
        if dep in failed:
            raise ExecutionDenied("a dependency failed")
        if dep not in completed:
            raise ExecutionDenied("a dependency has not completed")

    # §7 approved capabilities per task. A task requiring something Step 7 did
    # not grant must not run — that is the whole point of the capability gate.
    approved = set(selection.for_task(task.task_id))
    if not approved:
        raise PolicyDenied("no capability was approved for this task")

    # The tool whitelist is autopilot's, enforced again here because a plan can
    # reach this function without having passed through plan validation.
    if task.required_tool and task.required_tool not in AUTOPILOT_TOOLS:
        raise PolicyDenied(f"tool {task.required_tool!r} is not whitelisted")

    # §9: a read-only requirement may not be turned into a write.
    write_caps = {c for c in approved if c is Capability.MEMORY_WRITE}
    read_only_required = all(
        c.read_only for c in selection.capabilities if task.task_id in c.task_ids
    )
    if write_caps and read_only_required:
        raise PolicyDenied("write capability requested under a read-only requirement")


def run_plan(
    state: CognitiveState,
    plan: TaskPlan,
    selection: CapabilitySelection,
    tool_adapter: Optional[ToolAdapter] = None,
    deadline_seconds: int = AUTOPILOT_DEADLINE_SECONDS,
    max_steps: int = AUTOPILOT_MAX_STEPS,
    now: Callable[[], float] = time.monotonic,
    run_id: Optional[str] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> ExecutionResult:
    """Execute the plan and return structured evidence.

    Raises ExecutionDenied when no adapter is supplied — see the module
    docstring: an executor that silently does nothing is worse than one that
    refuses, because it reports success for work that never happened.

    `deadline_seconds` and `max_steps` default to autopilot's values and are
    CLAMPED to them: a caller may tighten the budget, never loosen it.
    """
    if tool_adapter is None:
        raise ExecutionDenied("no execution adapter supplied; refusing to run")

    # §6/§7: the cognitive layer cannot raise autopilot's limits.
    max_steps = min(int(max_steps), AUTOPILOT_MAX_STEPS)
    deadline_seconds = min(int(deadline_seconds), AUTOPILOT_DEADLINE_SECONDS)

    # Cooperative cancellation, read from autopilot's registry unless the caller
    # injects a predicate (tests do; production passes run_id).
    cancelled_check = is_cancelled or cancellation_check(run_id)

    started = now()
    result = ExecutionResult()
    completed: Set[str] = set()
    failed: Set[str] = set()          # ran and genuinely failed
    denied: Set[str] = set()          # refused by policy; never ran
    blocked: Set[str] = set()         # structurally unable to run (dependency)
    context_parts: List[str] = []
    steps_used = 0
    was_cancelled = False

    for task in _ordered(plan.tasks):
        # Checked BEFORE each task, the same cooperative point autopilot uses
        # between its own steps. Once set, no further task runs.
        if cancelled_check():
            was_cancelled = True
            task.status = TaskStatus.CANCELLED
            result.cancelled_tasks.append(task.task_id)
            result.outcomes.append(TaskOutcome(
                task_id=task.task_id, status=TaskStatus.CANCELLED,
                safe_summary="cancelled before execution",
            ))
            continue

        if steps_used >= max_steps:
            result.skipped_tasks.append(task.task_id)
            result.outcomes.append(TaskOutcome(
                task_id=task.task_id, status=TaskStatus.SKIPPED,
                safe_summary=f"step budget of {max_steps} reached",
            ))
            continue

        if now() - started > deadline_seconds:
            result.skipped_tasks.append(task.task_id)
            result.outcomes.append(TaskOutcome(
                task_id=task.task_id, status=TaskStatus.SKIPPED,
                error_category=FailureCategory.TIMEOUT,
                safe_summary=f"deadline of {deadline_seconds}s reached",
            ))
            continue

        # ── gates ────────────────────────────────────────────────────────────
        # A task already marked CANCELLED is cancelled, not denied and not
        # failed — reporting it as a failure was one of the reviewed defects.
        if task.status is TaskStatus.CANCELLED:
            was_cancelled = True
            result.cancelled_tasks.append(task.task_id)
            result.outcomes.append(TaskOutcome(
                task_id=task.task_id, status=TaskStatus.CANCELLED,
                safe_summary="task was already cancelled",
            ))
            continue

        try:
            _gate(task, selection, completed, failed)
        except PolicyDenied as refusal:
            # Authorization said no. Recorded, never retried, and deliberately
            # NOT added to `failed`: a refusal is not evidence the problem was
            # misunderstood, so it must not pull the engine into ASSESS.
            task.status = TaskStatus.SKIPPED
            denied.add(task.task_id)
            result.denied_tasks.append(task.task_id)
            result.outcomes.append(TaskOutcome(
                task_id=task.task_id, status=TaskStatus.SKIPPED,
                error_category=FailureCategory.SECURITY_BLOCK,
                safe_summary=str(refusal)[:REASON_MAX],
            ))
            result.errors.append(CognitiveError(
                category=FailureCategory.SECURITY_BLOCK,
                message=str(refusal), task_id=task.task_id,
            ))
            continue
        except ExecutionDenied as blocked_reason:
            # Structural: a dependency failed or has not completed. Downstream
            # of a real failure that has already been recorded, so it does not
            # add fresh evidence of its own.
            task.status = TaskStatus.SKIPPED
            blocked.add(task.task_id)
            result.skipped_tasks.append(task.task_id)
            result.outcomes.append(TaskOutcome(
                task_id=task.task_id, status=TaskStatus.SKIPPED,
                error_category=FailureCategory.EXECUTION_FAILURE,
                safe_summary=str(blocked_reason)[:REASON_MAX],
            ))
            continue

        # ── execute ──────────────────────────────────────────────────────────
        steps_used += 1
        task.status = TaskStatus.RUNNING
        task.attempts += 1
        began, began_at = now(), _now()
        tool = task.required_tool or "think"
        arg = (task.input_requirements or [task.objective])[0]

        try:
            raw = tool_adapter(tool, arg, "\n\n".join(context_parts)[-6000:])
            output = redact_secrets(str(raw or ""))
            ok, error_category, summary = True, None, output[:REASON_MAX]
        except BaseException as exc:                    # noqa: BLE001 - classified below
            ok = False
            error_category = _classify(exc)
            # §12: raw internal exceptions are never exposed.
            summary = f"{tool} failed ({_safe_error(exc)})"
            output = ""

        duration_ms = int((now() - began) * 1000)
        task.status = TaskStatus.COMPLETED if ok else TaskStatus.FAILED
        (completed if ok else failed).add(task.task_id)

        result.actions.append(ActionRecord(
            task_id=task.task_id, tool=tool, authorized=True,
            started_at=began_at, duration_ms=duration_ms, ok=ok,
            result_summary=summary, error=None if ok else summary,
        ))
        # §3: operational facts only. The observation carries what happened,
        # never why the model thought it would.
        result.observations.append(Observation(
            task_id=task.task_id,
            summary=summary,
            evidence=output,
            evidence_refs=[tool],
        ))
        result.outcomes.append(TaskOutcome(
            task_id=task.task_id,
            status=task.status,
            started_at=began_at,
            completed_at=_now(),
            duration_ms=duration_ms,
            success=ok,
            error_category=error_category,
            safe_summary=summary,
            verification_required=bool(task.verification_criteria),
        ))
        if not ok:
            result.errors.append(CognitiveError(
                category=error_category or FailureCategory.EXECUTION_FAILURE,
                message=summary, task_id=task.task_id,
            ))
        if output:
            context_parts.append(output[:2000])

        result.completed_tasks = sorted(completed)
        result.failed_tasks = sorted(failed)

    # ── outcome ──────────────────────────────────────────────────────────────
    result.completed_tasks = sorted(completed)
    result.failed_tasks = sorted(failed)
    result.denied_tasks = sorted(denied)
    result.requires_verification = any(o.verification_required for o in result.outcomes)

    # Reassessment is driven by EVIDENCE, not by anything that merely went
    # wrong. A task that ran and failed, or overran its budget, tells us the
    # plan expected something untrue. A refusal and a cancellation tell us
    # nothing about the problem, so neither may set this flag — that was the
    # defect the review caught.
    evidence = [o for o in result.outcomes
                if o.error_category in _EVIDENCE_CATEGORIES]
    result.requires_reassessment = bool(evidence) and not was_cancelled

    # Status precedence, most decisive first:
    #   CANCELLED           the user stopped it; nothing else is interesting
    #   REASSESS_REQUIRED   real failure AND something worked, so there is both
    #                       evidence and a foothold to re-plan from
    #   EXECUTION_FAILED    real failure with no progress, or work refused
    #   EXECUTION_COMPLETE  everything asked for actually ran
    if was_cancelled:
        result.final_execution_status = ExecutionStatus.CANCELLED
    elif evidence and completed:
        result.final_execution_status = ExecutionStatus.REASSESS_REQUIRED
    elif evidence:
        result.final_execution_status = ExecutionStatus.EXECUTION_FAILED
    elif denied or blocked:
        # Nothing failed on its merits; work was refused or never became
        # runnable. Not complete, but there is nothing to reassess either.
        result.final_execution_status = ExecutionStatus.EXECUTION_FAILED
    elif completed:
        result.final_execution_status = ExecutionStatus.EXECUTION_COMPLETE
    else:
        result.final_execution_status = ExecutionStatus.EXECUTION_FAILED

    result.success = (result.final_execution_status is ExecutionStatus.EXECUTION_COMPLETE)
    return result


def apply_to_state(state: CognitiveState, result: ExecutionResult) -> CognitiveState:
    """Record the run on the state and move the phase.

    Uses transition_to() rather than assigning `phase`, so the Step 2 graph and
    its transition budget stay in force — including refusing a move once the
    budget is spent.

    On reassessment this goes ACT -> ASSESS, which is the edge added in Step 2
    precisely so execution can feed evidence back instead of driving an
    obsolete plan to completion.
    """
    state.observations.extend(result.observations)
    state.actions.extend(result.actions)
    state.errors.extend(result.errors)

    if state.phase is not CognitivePhase.ACT and state.can_transition_to(CognitivePhase.ACT):
        state.transition_to(CognitivePhase.ACT)

    # A cancellation ends the session; it is not a reason to think again.
    if result.final_execution_status is ExecutionStatus.CANCELLED:
        if state.can_transition_to(CognitivePhase.ABORTED):
            state.transition_to(CognitivePhase.ABORTED)
        return state

    # ASSESS only on evidence. Routing a policy refusal here is what produced
    # the ACT -> ASSESS -> STRATEGY -> PLAN -> ACT loop around the same
    # forbidden action that the review rejected.
    target = (CognitivePhase.ASSESS if result.requires_reassessment
              else CognitivePhase.VERIFY)
    if state.can_transition_to(target):
        state.transition_to(target)
    return state
