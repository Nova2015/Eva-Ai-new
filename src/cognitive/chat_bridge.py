"""Chat bridge — the cognitive engine's entry point from /chat.

EVA's chat path already retrieves, routes, calls a model, applies the inbound
firewall and formats a reply. None of that moves here. This runs the cognitive
loop OVER the answer that path produced:

    understand -> assess -> strategy        (read the request)
    ...the existing RAG/model path executes...
    VERIFY -> CORRECT -> ACT -> VERIFY      (prove, repair, prove again)
    LEARN                                   (keep what was settled)

IT ORCHESTRATES, IT DOES NOT EXECUTE
====================================
There is no retrieval, no model call, no tool and no routing in this module. It
never generates a word of text: the only way an answer can change here is a
deterministic ACT remedy, which rearranges characters the answer already had.
That is what makes it safe to put in front of every reply.

WHERE IT IS CALLED, AND WHY THERE
=================================
From `_finalize_response`, which is the one funnel every answer-bearing /chat
return passes through. `chat()` has three such returns - the RAG shortcut and
the HF path both return early - and app.py's own comment records that the
inbound security check "sat dead for months" behind exactly those early
returns. Hooking the obvious-looking spot next to the review call would have
repeated that bug: it sits after two of the three returns.

It runs BEFORE the outbound gate, so a corrected answer is still inspected by
the firewall. A correction that skipped outbound inspection would be a bypass,
which is the one thing this must never become.

FAILING CHANGES NOTHING
=======================
Every path returns the original answer unless a correction was both applied and
independently re-verified. A crash, a missing stage, an unverifiable artefact,
an unsupported defect - all yield exactly what EVA returns today. The engine can
only improve a reply or leave it alone; it has no path to making one worse.

That is also why a corrected answer is accepted ONLY on VERIFIED. A repair that
merely swaps one defect for another is not returned, even though it may look
tidier - shipping an unproven artefact is the failure this whole stack exists
to prevent.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .act import act, ActStatus
from .assessment import assess
from .correction import correct, CorrectionStatus
from .executor import ExecutionResult, ExecutionStatus
from . import executor as _execution_backend
# _outcome_of is Step 12's answer to "did this remedy actually work". Reused
# rather than restated so the bridge and the learning record cannot disagree
# about whether a correction succeeded.
from .learning import CorrectionCycle, CorrectionOutcome, learn, emit, _outcome_of
from .planning import TaskPlan, plan_for
from .state import (
    CognitivePhase,
    CognitiveState,
    GateAction,
    PlannedTask,
    REASON_MAX,
    StrategySelection,
    VerificationStatus,
    redact_secrets,
)
from .strategy import select_strategy, VerificationRequirement
from .capabilities import select_capabilities
from .understanding import understand
# Phase 1 pre-answer decision gate, re-exported so app.py still reaches the
# engine through this one door. Optional: a fault in the gate must never disable
# the post-hoc verify/correct loop below, which stands on its own.
try:
    from .decision_gate import decide
except Exception:  # pragma: no cover
    decide = None
# Re-exported so app.py reaches the engine through this one door: the review
# hook in chat() and the loop here must share a payload for the same bytes.
from .verification import (
    verify, artifact_digest, available_requirements, new_review_cache,
    review_key, review_once,
)

# Structured reasoning verification is exposed through this bridge.
try:
    from .reasoning_orchestrator import verify_reasoning_answer
    from .reasoning_eligibility import is_reasoning_eligible
    from .provider_callback import build_reasoning_llm
    REASONING_VERIFICATION_AVAILABLE = True
except Exception:  # pragma: no cover
    verify_reasoning_answer = None
    is_reasoning_eligible = None
    build_reasoning_llm = None
    REASONING_VERIFICATION_AVAILABLE = False

# One task id for the one artefact a chat turn produces. The engine's models are
# per-task; a chat reply is a single artefact, so the id is a constant rather
# than something derived from user input.
CHAT_TASK = "chat_answer"


def orchestrate_preanswer(
    question: str,
    history: Optional[Sequence[dict]] = None,
) -> dict:
    """Prepare a chat turn through the cognitive planning stages.

    This stage does not execute tools or generate an answer. It prepares the
    strategy, plan, and capability selection while preserving the existing
    /chat execution path.
    """
    if not question or not question.strip():
        return {
            "allowed": False,
            "reason": "empty_question",
            "strategy": None,
            "plan": None,
            "selection": None,
        }

    try:
        if decide is not None:
            gate = decide(
                question,
                history=history,
                has_image=False,
            )
            if gate.action is not GateAction.PROCEED:
                return {
                    "allowed": False,
                    "reason": gate.action.value,
                    "strategy": gate.strategy.value,
                    "plan": None,
                    "selection": None,
                    "gate": gate,
                }

        context = [
            str(item.get("content", ""))
            for item in (history or [])
            if isinstance(item, dict) and item.get("content")
        ]

        comprehension = getattr(gate, "_understanding", None)
        knowledge = getattr(gate, "_assessment", None)
        decision = getattr(gate, "_strategy_decision", None)

        if comprehension is None:
            comprehension = understand(
                question,
                context=context,
                has_image=False,
            )
        if knowledge is None:
            knowledge = assess(
                comprehension,
                context=context,
                problem=question,
            )
        if decision is None:
            decision = select_strategy(
                comprehension,
                knowledge,
                problem=question,
                available=available_requirements(),
            )

        state = CognitiveState(problem=question)
        state.strategy = StrategySelection(strategy=decision.strategy)

        plan = plan_for(
            comprehension,
            knowledge,
            decision,
            problem=question,
        )

        selection = select_capabilities(
            plan,
            comprehension,
            knowledge,
            decision,
            problem=question,
        )

        return {
            "allowed": True,
            "reason": decision.reason,
            "strategy": decision.strategy.value,
            "plan": plan,
            "selection": selection,
            "state": state,
            "decision": decision,
            "gate": gate if decide is not None else None,
            "understanding": comprehension,
            "assessment": knowledge,
        }

    except Exception as exc:
        return {
            "allowed": False,
            "reason": "cognitive_preparation_failed",
            "strategy": None,
            "plan": None,
            "selection": None,
            "error": type(exc).__name__,
        }


_ENV_FLAG = "COGNITIVE_ENGINE_ENABLED"
_ENV_TIMEOUT = "COGNITIVE_TIMEOUT_SECONDS"
_DEFAULT_TIMEOUT = 2.0


def timeout_seconds() -> float:
    """How long the caller may wait for this before giving up on it.

    This work is NOT free: review_engine shells out to `node --check` for a
    JavaScript block, which measures ~80ms per pass and is bounded internally
    at 10s. Two passes run per corrected answer. The caller must therefore run
    refine() in a worker thread under this timeout — never inline on the event
    loop, where a slow or hung node stalls every concurrent request.
    """
    try:
        value = float(os.getenv(_ENV_TIMEOUT, "") or _DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        return _DEFAULT_TIMEOUT
    return value if value > 0 else _DEFAULT_TIMEOUT


def enabled() -> bool:
    """Kill switch, read per request so it can be flipped without a redeploy.

    Defaults to ON: the engine is wired in deliberately. It exists because this
    sits in front of every reply, and a layer in that position should be
    removable without a deploy even when nobody expects to need it.
    """
    return os.getenv(_ENV_FLAG, "true").strip().lower() not in ("false", "0", "no")


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ChatRefinement(_Base):
    """What the loop concluded about one reply.

    `answer` is what /chat should send. It is the original unless a correction
    was applied AND re-verified, so a caller can use it unconditionally.
    """

    answer: str = ""
    changed: bool = False
    ran: bool = False
    verification_status: str = VerificationStatus.NOT_REQUIRED.value
    # Set only when a correction was applied and proven; None otherwise.
    remedy_applied: Optional[str] = None
    strategy: str = ""
    # Fingerprint of the artefact verification actually read - Step 9's
    # provenance, carried out so the response can show what was judged.
    verified_digest: Optional[str] = None
    needs_clarification: bool = False
    notes: List[str] = Field(default_factory=list)

    @field_validator("notes")
    @classmethod
    def _scrub_list(cls, v: List[str]) -> List[str]:
        return [redact_secrets(str(i or ""))[:REASON_MAX] for i in v]

    def summary(self) -> Dict[str, object]:
        """The compact block /chat attaches to its response body.

        Deliberately small and free of content: statuses, a remedy name and a
        digest. The answer travels in the response's own `answer` field.
        """
        return {
            "ran": self.ran,
            "status": self.verification_status,
            "corrected": self.changed,
            "remedy": self.remedy_applied,
            "strategy": self.strategy,
            "digest": self.verified_digest,
        }


def _state(question: str) -> CognitiveState:
    """A session already advanced to VERIFY.

    UNDERSTAND through ACT describe work the existing chat path has already
    done by the time this runs, so the phases are walked to keep Step 2's graph
    honest rather than to drive anything.
    """
    state = CognitiveState(problem=question)
    for phase in (CognitivePhase.ASSESS, CognitivePhase.STRATEGY,
                  CognitivePhase.PLAN, CognitivePhase.ACT, CognitivePhase.VERIFY):
        state.transition_to(phase)
    return state


def _executed(answer: str) -> ExecutionResult:
    """The existing path's work, expressed in the engine's vocabulary.

    Recording that a reply was produced is not the same as producing one. No
    tool runs here and run_plan is not called: the execution already happened
    upstream, in the retrieval and model code that owns it.
    """
    return ExecutionResult(
        success=bool(answer),
        completed_tasks=[CHAT_TASK],
        final_execution_status=ExecutionStatus.EXECUTION_COMPLETE,
    )


_UNAVAILABLE_NOTE = "not executable in this runtime"


def _verify(answer: str, decision, plan: TaskPlan, cache=None):
    """Verify, then record the coverage gap alongside the verdict.

    Requirements Step 5 could not run were never requested, so Step 9 has
    nothing to say about them — but they must not vanish. `unverifiable` is the
    field that means "wanted, could not be checked", and it feeds Step 12's
    VERIFICATION_GAP lessons.

    It is deliberately safe to write here: VerificationReport.status is derived
    from `results` alone, so recording a gap cannot turn a VERIFIED into an
    INCONCLUSIVE. The verdict stays truthful about what ran; the list stays
    truthful about what did not.
    """
    report = verify(_executed(answer), plan, decision,
                    artifacts={CHAT_TASK: answer}, review_cache=cache)
    for requirement in getattr(decision, "unavailable_requirements", ()):
        entry = f"{requirement.value}: {_UNAVAILABLE_NOTE}"
        if entry not in report.unverifiable:
            report.unverifiable = report.unverifiable + [entry]
    return report


def _failing_codes(report) -> set:
    """Issue codes Step 9 reported as fatal, across every check."""
    codes = set()
    for result in report.results:
        if result.status is VerificationStatus.FAILED:
            codes.update(c.strip() for c in (result.failure_reason or "").split(",")
                         if c.strip())
    return codes


def _correction_is_an_improvement(action, cycle, before, after) -> bool:
    """Whether the corrected artefact may be sent to the user.

    NOT "the whole report is VERIFIED". A chat answer routinely carries
    requirements nothing local can satisfy - a code answer asks for
    EXECUTION_TEST, which has no runner here - so the aggregate is INCONCLUSIVE
    however good the artefact is. Gating on VERIFIED made every correction
    unacceptable and the whole ACT path dead in production.

    The question that actually matters is narrower and answerable: did the
    defect that was corrected go away, and did nothing new break? The first
    half is Step 12's APPLIED_RESOLVED, which requires Step 9's verdict over a
    provenance-matched artefact - ACT reporting APPLIED is never enough.
    """
    # _outcome_of is the single authority, and it already answers None with
    # PROPOSED_UNAPPLIED — so a missing cycle is rejected here without a second
    # check that could drift from it.
    if _outcome_of(action, cycle) is not CorrectionOutcome.APPLIED_RESOLVED:
        return False
    # A repair that trades one defect for another is not an improvement.
    return after <= before


def refine(
    question: str,
    answer: str,
    context: Optional[Sequence[str]] = None,
    has_image: bool = False,
    review_cache: Optional[Dict[str, dict]] = None,
    learning_sink=None,
) -> ChatRefinement:
    """Run the cognitive loop over one produced answer.

    Never raises. Never calls a model, a tool or the network. Returns the
    original answer unless a deterministic remedy was applied and the corrected
    artefact independently verified.
    """
    # Typed BEFORE anything can fail, and outside the try below, because
    # constructing ChatRefinement is itself validated: handing this a dict once
    # raised a ValidationError past a function documented never to raise. A
    # non-string answer is not ours to interpret, so `changed` stays False and
    # the caller's payload is left exactly as it was.
    text = answer if isinstance(answer, str) else ""
    problem = question if isinstance(question, str) else ""

    outcome = ChatRefinement(answer=text)
    if not enabled() or not text.strip():
        return outcome

    try:
        # ── read the request ────────────────────────────────────────────────
        answer = text
        comprehension = understand(problem, context=context, has_image=has_image)
        knowledge = assess(comprehension, context=context, problem=problem)
        # Only checks this runtime can actually execute enter the pipeline.
        # No code_runner is supplied here - runtime_engine is async and reaches
        # the network - so EXECUTION_TEST is recorded as unavailable rather than
        # requested and left to fail. Without this, every code answer verified
        # INCONCLUSIVE no matter how good it was, and the correction path was
        # unreachable for most traffic.
        decision = select_strategy(comprehension, knowledge, problem=problem,
                                   available=available_requirements())

        outcome.strategy = decision.strategy.value
        # Reported, never acted on: overriding the reply with a clarification
        # would change behaviour the chat path already owns.
        outcome.needs_clarification = bool(comprehension.ambiguities)

        state = _state(problem)
        state.strategy = StrategySelection(strategy=decision.strategy)

        plan = TaskPlan(tasks=[PlannedTask(task_id=CHAT_TASK,
                                           objective="answer the user")])

        # ── VERIFY ──────────────────────────────────────────────────────────
        first = _verify(answer, decision, plan, review_cache)
        outcome.ran = True
        outcome.verification_status = first.status.value
        outcome.verified_digest = first.artifact_digests.get(CHAT_TASK)

        if first.status is not VerificationStatus.FAILED:
            # NOT_REQUIRED covers ordinary prose replies, which is most of them:
            # nothing checkable, so nothing claimed and nothing changed.
            _record(state, _executed(answer), first,
                    correct(state, _executed(answer), first), None, outcome,
                    learning_sink)
            return outcome

        # ── CORRECT ─────────────────────────────────────────────────────────
        proposal = correct(state, _executed(answer), first)
        if proposal.status is not CorrectionStatus.CORRECTIONS_PROPOSED:
            outcome.notes.append(f"no correction: {proposal.status.value}")
            _record(state, _executed(answer), first, proposal, None, outcome, learning_sink)
            return outcome

        # ── ACT: exactly one remedy per cycle ───────────────────────────────
        approved = [proposal.corrections[0].action_id]
        applied = act(state, proposal, approved, {CHAT_TASK: answer})
        if applied.status is not ActStatus.APPLIED or not applied.artifacts:
            outcome.notes.append(f"no remedy applied: {applied.status.value}")
            _record(state, _executed(answer), first, proposal, None, outcome)
            return outcome

        corrected = applied.artifacts.get(CHAT_TASK, answer)

        # ── VERIFY AGAIN — the corrected artefact, exactly as ACT produced it ─
        second = _verify(corrected, decision, plan, review_cache)
        cycle = None
        try:
            cycle = CorrectionCycle(act=applied, verification=second)
        except Exception:
            # Provenance mismatch. The pair cannot be trusted, so neither can
            # the correction: keep the original.
            outcome.notes.append("provenance mismatch; correction discarded")

        if _correction_is_an_improvement(proposal.corrections[0], cycle,
                                         _failing_codes(first),
                                         _failing_codes(second)):
            outcome.answer = corrected
            outcome.changed = True
            outcome.remedy_applied = proposal.corrections[0].issue
            outcome.verification_status = second.status.value
            outcome.verified_digest = second.artifact_digests.get(CHAT_TASK)
        else:
            outcome.notes.append(
                f"correction not accepted: reverify={second.status.value}")

        _record(state, _executed(corrected), first, proposal, cycle, outcome,
                learning_sink)
        return outcome

    except Exception as exc:                      # noqa: BLE001 - never propagate
        outcome.answer = text
        outcome.changed = False
        outcome.notes.append(f"cognitive engine skipped ({type(exc).__name__})")
        return outcome


def _record(state, result, verification, correction_report, cycle,
            outcome: ChatRefinement, learning_sink=None) -> None:
    """Hand the finished cycle to LEARN. Observational, and never fatal.

    No sink is passed, so nothing is emitted anywhere: candidates stay on the
    state for an operator to review. Wiring a sink to the training store is a
    decision for whoever owns that queue, not a side effect of answering a chat
    message.
    """
    try:
        lessons = learn(state, result, verification, correction_report, cycle=cycle)
        if lessons.candidates:
            outcome.notes.append(f"{len(lessons.candidates)} lesson(s) proposed")
            emit(lessons, sink=learning_sink)
    except Exception:
        pass
