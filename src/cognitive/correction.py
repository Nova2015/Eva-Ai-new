"""Correction â€” Step 10 of the Cognitive Engine.

Answers: **given what verification actually proved, what may legitimately be
changed?**

This is not a second verifier. It re-checks nothing, re-runs nothing, and
forms no opinion of its own about whether an artefact is correct: Step 9 has
already said so, and disagreeing with it here would give the engine two
verdicts that drift apart. Step 10 reads that verdict and decides what action
the evidence justifies.

IT PROPOSES. IT DOES NOT APPLY.
==============================
Every output is an advisory `CorrectionAction`. Nothing here writes a file,
touches a database, edits configuration, or calls a tool â€” the module imports
no I/O at all, and a test asserts that from the parsed source rather than from
this sentence. A future ACT stage applies corrections; that is where the tool
whitelist and the approval gate already live, and routing changes through it
keeps one set of controls instead of two.

The consequence is a shape worth stating plainly: **correction can never
return VERIFIED.** A proposed change is unproven by construction, so anything
it touches goes back through VERIFY before it counts.

CORRECT -> VERIFY IS NOT ONE EDGE
=================================
Step 2's graph has no CORRECT -> VERIFY transition, and that is correct, not an
oversight. A proposal cannot be verified â€” only an applied change can. The real
route is CORRECT -> ACT -> VERIFY, and both of those edges already exist. No
change to state.py is needed, and none is made.

WHAT JUSTIFIES A CORRECTION
===========================
Only a FAILED verification carrying an issue code this module knows how to act
on. Everything else is deliberately inert:

  VERIFIED       nothing to do
  NOT_REQUIRED   nothing was checked, so nothing is claimed
  INCONCLUSIVE   evidence is missing; the answer is to obtain it, not to guess
  FAILED, code unknown    the defect is real but its remedy is not derivable
                          from the evidence, so reassessment - never a guess
  policy denial  not a defect at all; see below

A warning is not a correction trigger either. Step 9 reports non-fatal issues
as INCONCLUSIVE, and rewriting an artefact on the strength of a warning is a
change made without proof that anything is wrong.

A DENIAL IS NOT A DEFECT
========================
When the executor refused a task, nothing malfunctioned â€” the policy worked.
Denials are recorded as blocking issues, never as correction targets, and no
proposed change may name a denied task. Reassessment is not triggered by them
either: re-planning around a refusal is the shape of a bypass attempt, which is
the same reasoning that fixed the Step 8 review defect.

Cancellation is treated the same way. The user stopped the work; retrying it
uninvited would undo their decision.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Step 4's severity vocabulary, which is EVA's existing one from src/security/.
# A second risk scale would be a second thing to keep in agreement.
from .assessment import RiskLevel
# Step 8 already decided which failure categories are evidence and which are
# refusals, and that distinction was the fix its review demanded. Reused, not
# restated, so the two stages cannot disagree about what a denial is.
from .executor import ExecutionResult, ExecutionStatus, _DENIAL_CATEGORIES
from .state import (
    CognitiveError,
    CognitivePhase,
    CognitiveState,
    FailureCategory,
    REASON_MAX,
    VerificationResult,
    VerificationStatus,
    redact_secrets,
)
from .verification import VerificationReport


class CorrectionStatus(str, Enum):
    """Outcome of one correction pass. Step 11 decides what to do about it."""

    NO_CORRECTION_NEEDED = "NO_CORRECTION_NEEDED"
    CORRECTIONS_PROPOSED = "CORRECTIONS_PROPOSED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    BLOCKED = "BLOCKED"                     # policy refused; not a defect
    REASSESS_REQUIRED = "REASSESS_REQUIRED"
    CANCELLED = "CANCELLED"


# What each review_engine issue code means for the artefact, and nothing more.
#
# This is a remedy map, not a severity map: whether a code is fatal remains
# review_engine's call, and Step 9 has already applied it. Every entry
# describes re-emitting the artefact that failed. None of them names a tool, a
# path, a command or a system, because a correction is not allowed to reach
# outside the artefact it is about.
#
# A code absent from this table is not a licence to improvise. It produces no
# action at all â€” see _corrections_for.
_REMEDY: Dict[str, str] = {
    # code_validator
    "python_syntax_error":
        "re-emit the Python block so it parses; the current block does not",
    "json_parse_error":
        "re-emit the JSON block as parseable JSON",
    "unclosed_fence":
        "close the code fence; the block is opened and never terminated",
    # mermaid_validator
    "missing_diagram_type":
        "begin the mermaid block with a diagram type (flowchart, sequenceDiagram, ...)",
    "empty_diagram":
        "give the mermaid block at least one node or edge, or remove the block",
    "unbalanced_brackets":
        "balance the brackets in the mermaid block",
    "prose_not_diagram":
        "replace the prose in the mermaid block with diagram syntax, or unfence it",
    # chart_validator
    "malformed_block":
        "re-emit the chart block in the expected structure",
    "empty_data":
        "give the chart block a non-empty data series, or remove the block",
    "arithmetic_result_mismatch":
        "re-emit the arithmetic result using the independently recomputed value",
}

# Applying a correction means re-emitting an artefact, which is why every
# action carries the same low risk: no tool runs, no state outside the artefact
# is touched, and the result is verified again before it counts.
_ARTEFACT_RISK = RiskLevel.LOW

_CANCELLED = "execution was cancelled; no correction is attempted"
_DENIED = "policy refused this task; not a correctness defect"
_NO_REMEDY = "no remedy is derivable from this evidence"
_CONFLICT = "verification both passed and failed for the same check"


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class CorrectionAction(_Base):
    """One proposed change, carrying enough for a later ACT stage to apply it.

    `proposed_change` always comes from _REMEDY â€” never from the artefact, the
    model, or the failure text â€” so an action cannot smuggle content out of a
    response or an instruction in from one.
    """

    action_id: str = Field(default_factory=lambda: f"fix_{uuid.uuid4().hex[:10]}")
    target: str = ""                   # the task whose artefact failed
    issue: str = ""                    # review_engine's issue code
    evidence: List[str] = Field(default_factory=list)
    proposed_change: str = ""
    confidence: float = 0.0
    risk: RiskLevel = _ARTEFACT_RISK
    # Structural, not a default someone can forget: a change is unproven until
    # it has been applied and verified again.
    requires_reverification: bool = True

    @field_validator("target", "issue", "proposed_change")
    @classmethod
    def _scrub(cls, v: str) -> str:
        return redact_secrets(str(v or ""))[:REASON_MAX]

    @field_validator("evidence")
    @classmethod
    def _scrub_list(cls, v: List[str]) -> List[str]:
        return [redact_secrets(str(i or ""))[:REASON_MAX] for i in v]

    @field_validator("confidence")
    @classmethod
    def _bounded(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    @field_validator("requires_reverification")
    @classmethod
    def _always(cls, v: bool) -> bool:
        return True


class CorrectionReport(_Base):
    status: CorrectionStatus = CorrectionStatus.NO_CORRECTION_NEEDED
    corrections: List[CorrectionAction] = Field(default_factory=list)
    # Denials, cancellation â€” things no correction may route around.
    blocking_issues: List[str] = Field(default_factory=list)
    # Targets a correction was proposed for. Nothing has been changed yet.
    corrected_items: List[str] = Field(default_factory=list)
    # Real problems with no justified correction.
    unresolved_items: List[str] = Field(default_factory=list)
    evidence_used: List[str] = Field(default_factory=list)
    requires_reverification: bool = False
    requires_reassessment: bool = False
    safe_to_apply: bool = False
    reason: str = ""

    @field_validator("reason")
    @classmethod
    def _scrub(cls, v: str) -> str:
        return redact_secrets(str(v or ""))[:REASON_MAX]

    @field_validator("blocking_issues", "corrected_items", "unresolved_items",
                     "evidence_used")
    @classmethod
    def _scrub_list(cls, v: List[str]) -> List[str]:
        return [redact_secrets(str(i or ""))[:REASON_MAX] for i in v]

    def actions_for(self, target: str) -> List[CorrectionAction]:
        return [a for a in self.corrections if a.target == target]


def _codes(result: VerificationResult) -> List[str]:
    """The issue codes Step 9 recorded, in order, without duplicates."""
    raw = (result.failure_reason or "").split(",")
    out: List[str] = []
    for code in (c.strip() for c in raw):
        if code and code not in out:
            out.append(code)
    return out


def _evidence_ref(result: VerificationResult) -> str:
    """A pointer to the verification that justified a decision.

    Names the check and its verdict, never the artefact â€” quoting the content
    would put response text into a structure meant to be logged.
    """
    where = "/".join([result.verification_type or "?"] + list(result.criteria or []))
    return f"{where}@{result.task_id or '-'}: {result.status.value}"


def _corrections_for(
    result: VerificationResult,
    remedy_lookup: Optional[Callable[[str], Optional[str]]],
) -> Tuple[List[CorrectionAction], List[str]]:
    """Actions justified by one FAILED verification, plus codes with no remedy.

    Confidence is the share of that check's issue codes this module actually
    understands. It is a claim about the diagnosis, not a promise about the
    fix: two codes of which one is unrecognised means the picture is half
    understood, and the report should say so rather than round up.
    """
    codes = _codes(result)
    if not codes:
        return [], [_NO_REMEDY]

    known = [c for c in codes if c in _REMEDY]
    unknown = [c for c in codes if c not in _REMEDY]

    # An injected lookup may only fill gaps. It cannot override a known remedy
    # and cannot reach a code review_engine did not emit, so supplying one can
    # never weaken a verdict or redirect an existing action.
    if remedy_lookup is not None:
        still_unknown: List[str] = []
        for code in unknown:
            try:
                extra = remedy_lookup(code)
            except Exception:
                extra = None
            if extra:
                known.append(code)
            else:
                still_unknown.append(code)
        unknown = still_unknown

    if not known:
        return [], unknown

    confidence = len(known) / len(codes)
    ref = _evidence_ref(result)
    actions = [
        CorrectionAction(
            target=result.task_id or "",
            issue=code,
            evidence=[ref, *result.criteria],
            proposed_change=_REMEDY.get(code) or (
                remedy_lookup(code) if remedy_lookup else ""),
            confidence=confidence,
            risk=_ARTEFACT_RISK,
        )
        for code in known
    ]
    return actions, unknown


def _conflicts(results: Sequence[VerificationResult]) -> List[str]:
    """Checks that both passed and failed for the same task.

    Picking a side here would be choosing arbitrarily between two pieces of
    evidence that cannot both be right. The engine reassesses instead.
    """
    seen: Dict[Tuple[str, str], set] = {}
    for r in results:
        if r.status in (VerificationStatus.VERIFIED, VerificationStatus.FAILED):
            key = (r.task_id or "-", r.verification_type or "?")
            seen.setdefault(key, set()).add(r.status)
    return [f"{tid}/{vtype}: {_CONFLICT}"
            for (tid, vtype), statuses in seen.items() if len(statuses) > 1]


def correct(
    state: CognitiveState,
    result: ExecutionResult,
    report: VerificationReport,
    remedy_lookup: Optional[Callable[[str], Optional[str]]] = None,
) -> CorrectionReport:
    """Decide what correction the verified evidence justifies.

    Deterministic and side-effect free: `state` is read, never written, and the
    same three inputs always yield the same report. apply_to_state() is where
    anything changes, and it is a separate call so a caller can inspect the
    decision before letting it move the engine.
    """
    blocking: List[str] = []
    evidence_used: List[str] = []

    # â”€â”€ cancellation ends it, before anything else is considered â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if result.final_execution_status is ExecutionStatus.CANCELLED:
        return CorrectionReport(
            status=CorrectionStatus.CANCELLED,
            blocking_issues=[_CANCELLED],
            reason=_CANCELLED,
            requires_reverification=False,
            requires_reassessment=False,
            safe_to_apply=False,
        )

    # â”€â”€ refusals are recorded, never corrected â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    denied = set(result.denied_tasks)
    for task_id in result.denied_tasks:
        blocking.append(f"{task_id}: {_DENIED}")
    for error in result.errors:
        if error.category in _DENIAL_CATEGORIES:
            entry = f"{error.task_id or '-'}: {error.category.value}"
            if entry not in blocking:
                blocking.append(entry)

    corrections: List[CorrectionAction] = []
    unresolved: List[str] = []
    unjustified_failure = False

    for vr in report.results:
        if vr.status is VerificationStatus.VERIFIED:
            continue
        if vr.status is VerificationStatus.NOT_REQUIRED:
            continue

        if vr.status is VerificationStatus.INCONCLUSIVE:
            # Missing evidence is answered by obtaining evidence. Guessing a
            # change here would be a modification made without proof.
            evidence_used.append(_evidence_ref(vr))
            unresolved.append(
                f"{vr.task_id or '-'}/{vr.verification_type or '?'}: "
                f"{vr.failure_reason or 'not asserted'}")
            continue

        # FAILED.
        if vr.task_id and vr.task_id in denied:
            # Belt and braces: a denied task should not have been verified at
            # all, and must never become a correction target if it was.
            continue

        evidence_used.append(_evidence_ref(vr))
        actions, unknown = _corrections_for(vr, remedy_lookup)
        corrections.extend(actions)
        for code in unknown:
            unjustified_failure = True
            unresolved.append(f"{vr.task_id or '-'}/{code}: {_NO_REMEDY}")

    conflicts = _conflicts(report.results)
    unresolved.extend(conflicts)

    # â”€â”€ reassessment â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Step 8 already computed whether execution produced evidence that the plan
    # was wrong, with denials and cancellations excluded. Trusting that instead
    # of recomputing it keeps one definition of "evidence" in the engine.
    requires_reassessment = bool(
        result.requires_reassessment or conflicts or unjustified_failure)

    corrected_items: List[str] = []
    for action in corrections:
        if action.target and action.target not in corrected_items:
            corrected_items.append(action.target)

    # A correction nobody can apply is not safe to apply. The budget is read
    # here and consumed in apply_to_state, so this stays side-effect free.
    if corrections and state.retries_remaining() <= 0:
        blocking.append("retry budget spent; no correction can be applied")

    # â”€â”€ status, most decisive first â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if requires_reassessment:
        status = CorrectionStatus.REASSESS_REQUIRED
    elif corrections:
        status = CorrectionStatus.CORRECTIONS_PROPOSED
    elif blocking:
        status = CorrectionStatus.BLOCKED
    elif unresolved:
        status = CorrectionStatus.INSUFFICIENT_EVIDENCE
    else:
        status = CorrectionStatus.NO_CORRECTION_NEEDED

    # A change is unproven until it has been applied and verified again. This
    # is the only thing that sets the flag: an INCONCLUSIVE result never does,
    # because nothing was changed on its account.
    requires_reverification = bool(corrections)

    # Not "apply this automatically" â€” only "nothing in this report forbids a
    # future ACT stage from applying it". A refusal, a contradiction in the
    # evidence, or an exhausted budget each withdraw that.
    safe_to_apply = bool(
        corrections and not blocking and not requires_reassessment
        and all(a.risk in (RiskLevel.SAFE, RiskLevel.LOW) for a in corrections))

    reasons = {
        CorrectionStatus.CANCELLED: _CANCELLED,
        CorrectionStatus.REASSESS_REQUIRED:
            "evidence does not justify a correction on its own",
        CorrectionStatus.CORRECTIONS_PROPOSED:
            f"{len(corrections)} correction(s) proposed; re-verification required",
        CorrectionStatus.BLOCKED:
            "policy refused the work; no correction may route around it",
        CorrectionStatus.INSUFFICIENT_EVIDENCE:
            "verification could not be asserted; evidence is missing",
        CorrectionStatus.NO_CORRECTION_NEEDED:
            "verification found nothing to correct",
    }

    return CorrectionReport(
        status=status,
        corrections=corrections,
        blocking_issues=blocking,
        corrected_items=corrected_items,
        unresolved_items=unresolved,
        evidence_used=evidence_used,
        requires_reverification=requires_reverification,
        requires_reassessment=requires_reassessment,
        safe_to_apply=safe_to_apply,
        reason=reasons[status],
    )


def apply_to_state(state: CognitiveState, report: CorrectionReport) -> CognitiveState:
    """Record the decision on the state and move the phase.

    Moves go through transition_to(), so Step 2's graph and its transition
    budget stay in force. Nothing is corrected here either â€” this only routes
    the engine to whichever stage is entitled to act next.

    A proposed correction consumes one retry from Step 2's existing budget.
    That budget was written for exactly this and had no consumer until now; a
    private counter here would be a second bound that drifts from the first.
    When it is spent the engine stays in CORRECT rather than looping back to
    ACT, because running out of retries is an ordinary outcome, not an error.
    """
    if report.status is CorrectionStatus.CANCELLED:
        if state.can_transition_to(CognitivePhase.ABORTED):
            state.transition_to(CognitivePhase.ABORTED)
        return state

    # Nothing to correct: the session has whatever it is going to have, and the
    # next useful stage is LEARN. CORRECT is not entered at all â€” a phase the
    # engine had no business in would burn a transition and misreport history.
    if report.status in (CorrectionStatus.NO_CORRECTION_NEEDED,
                         CorrectionStatus.BLOCKED,
                         CorrectionStatus.INSUFFICIENT_EVIDENCE):
        if state.can_transition_to(CognitivePhase.LEARN):
            state.transition_to(CognitivePhase.LEARN)
        return state

    if state.phase is not CognitivePhase.CORRECT and \
            state.can_transition_to(CognitivePhase.CORRECT):
        state.transition_to(CognitivePhase.CORRECT)

    if report.status is CorrectionStatus.REASSESS_REQUIRED:
        if state.can_transition_to(CognitivePhase.ASSESS):
            state.transition_to(CognitivePhase.ASSESS)
        return state

    # CORRECTIONS_PROPOSED. CORRECT -> ACT -> VERIFY: the proposal is applied
    # by ACT and proven by VERIFY. There is no edge that would let a proposal
    # be treated as verified.
    if not state.register_retry():
        state.errors.append(CognitiveError(
            category=FailureCategory.VERIFICATION_FAILURE,
            message="retry budget spent; correction not attempted again",
        ))
        return state

    if state.can_transition_to(CognitivePhase.ACT):
        state.transition_to(CognitivePhase.ACT)
    return state

