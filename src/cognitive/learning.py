"""Learning — Step 12 of the Cognitive Engine.

Answers: **what, if anything, did this session prove that is worth keeping?**

It learns about the reasoning process, not about the answer. EVA already has a
place where answers become training data: learning_loop captures a chat
exchange as a PENDING candidate, and an admin approves it before it reaches a
dataset. Duplicating that here would give the product two training stores with
two review workflows. This stage produces a different kind of record — which
strategy verified, which capability failed, which verification could not be
run — and it produces it in the same shape and under the same rule.

PROPOSED, NEVER APPROVED
========================
`LearningCandidate.approved` is pinned False by a validator that survives both
construction and assignment. Step 2 created that field precisely so it could
not default true anywhere, and this stage is the first thing that could have
broken that. A human transition remains the only path to a dataset.

NOTHING IS LEARNED FROM AN UNVERIFIED OUTCOME
=============================================
This is the property the stage rests on, and it is the direct descendant of
Step 9's. "The strategy worked" is a claim, and a claim needs the same evidence
here as anywhere else:

    VERIFIED       may teach that the approach worked
    FAILED         may teach that it did not, when the failure is evidence
    INCONCLUSIVE   teaches nothing - it is the absence of a result, not a result
    NOT_REQUIRED   nothing was checked, so nothing is known

Learning from an inconclusive run is how a system convinces itself of something
no one ever established. It is worse than not learning, because the false
lesson is then reinforced by everything built on it.

WHICH VERIFICATION IS THE OUTCOME
=================================
Once Step 11 exists, a cycle produces TWO verifications: the one that found the
defect, and the one that judged the correction. They routinely disagree - that
is the entire point of correcting - so "the outcome" is ambiguous unless the
relationship is stated.

Handed the stale pre-correction report, this stage produced `outcome=FAILED`
for a cycle whose corrected artefact verified clean. Same code path, opposite
lesson, no error. So a bare VerificationReport is no longer accepted as a final
outcome when a correction was proposed. A CorrectionCycle must be supplied, and
it binds the ActResult to the verification that judged ITS output - the two
arrive together or not at all, and the pairing is checked rather than trusted.

Without that pairing every outcome-dependent lesson is withheld. Gap lessons
survive: what EVA cannot check does not depend on whether a correction worked.

The binding is as strong as the current architecture allows. VerificationReport
does not record which artefact it read, so this cannot prove a report came from
the corrected bytes; it can prove ACT and the verification concern the same
tasks, and reject the same object being passed twice. Closing the remainder
means recording artefact provenance in Step 9, which is not this stage's to
change.

NOT_REQUIRED IS NOT THE SAME AS "NOTHING CAME BACK"
===================================================
After a remedy, three post-states are possible and only two used to be told
apart. INCONCLUSIVE is the absence of evidence. NOT_REQUIRED is evidence of
absence: it is only reachable when an artefact WAS read and held no construct
of that kind, because an artefact that went missing or empty yields
INCONCLUSIVE instead. Collapsing them meant every REMOVAL remedy was judged to
have failed - the block it deleted was exactly what the check looked for, so
the check afterwards found nothing and that read as "no verdict".

Whether an absent construct is success depends on what the remedy set out to
do, and only the remedy knows: ACT declares it per entry (removes_construct).
A removal remedy deleting its block IS the repair; a repair-in-place remedy
whose block vanished has failed in a way that must not be read as success.

A DENIAL IS NOT A LESSON
========================
When the policy refused a task, that is withheld entirely — not recorded as a
candidate under any category. A training record encoding which tools get
refused is a map of the boundary, and the thing most likely to learn from it is
a model being taught where the edges are. Denials are already visible to an
operator through Step 10's blocking_issues, which is the right surface for
them: reviewed by a person, not fed back into weights.

Cancellation is withheld for a plainer reason: the work never finished, so
there is no outcome to draw a lesson from.

NO FREE TEXT
============
Every candidate summary is assembled from fixed enum values, integer counts and
review_engine issue codes. No problem text, response text, artefact content,
model-generated phrase or exception message can reach one. This is the same
rule the security work applied to reason_code, for the same reason: a field
built from a prompt is a field an attacker writes.

NO I/O. Nothing here opens a file, touches a database or calls a service.
`emit` hands candidates to an injected sink and is the only place anything
leaves this module; without a sink, nothing leaves at all.
"""

from __future__ import annotations

from enum import Enum
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .act import ActResult, remedy_removes_construct
from .correction import CorrectionReport, CorrectionStatus
from .executor import ExecutionResult, ExecutionStatus
from .state import (
    CognitivePhase,
    CognitiveState,
    FailureCategory,
    LearningCandidate,
    REASON_MAX,
    ReasoningStrategy,
    VerificationStatus,
    redact_secrets,
)
from .verification import VerificationReport, artifact_digest


class LearningCategory(str, Enum):
    """The kinds of lesson this stage can draw.

    There is deliberately no category for a policy refusal. Adding one would
    make the withholding rule a matter of which branch ran rather than a shape
    the type system enforces.
    """

    STRATEGY_OUTCOME = "STRATEGY_OUTCOME"
    CAPABILITY_RELIABILITY = "CAPABILITY_RELIABILITY"
    VERIFICATION_GAP = "VERIFICATION_GAP"
    RECURRING_DEFECT = "RECURRING_DEFECT"
    # Whether a remedy actually worked. Only recordable since Step 11: before
    # ACT existed nothing could be applied, so there was no efficacy to observe.
    REMEDY_EFFICACY = "REMEDY_EFFICACY"


class LearningStatus(str, Enum):
    CANDIDATES_PROPOSED = "CANDIDATES_PROPOSED"
    NOTHING_LEARNED = "NOTHING_LEARNED"
    WITHHELD = "WITHHELD"


# Step 3's documented category vocabulary. Its hybrid path takes
# problem_category from the model's JSON and accepts whatever comes back, so an
# arbitrary string can reach ProblemUnderstanding. Anything outside this set
# becomes _UNCLASSIFIED rather than being written into a persisted record.
_KNOWN_CATEGORIES = frozenset({
    "greeting", "identity", "mathematics", "coding", "document",
    "comparison", "procedure", "image_generation", "vision", "general",
    "machine_learning", "security",
})
_UNCLASSIFIED = "unclassified"

# Failures that say something about the approach. Mirrors Step 8's evidence
# rule: a refused or cancelled task teaches nothing about whether the strategy
# was sound, because the strategy was never tested.
_INSTRUCTIVE_FAILURES = frozenset({
    FailureCategory.TOOL_FAILURE,
    FailureCategory.EXECUTION_FAILURE,
    FailureCategory.MODEL_FAILURE,
    FailureCategory.TIMEOUT,
    FailureCategory.INVALID_INPUT,
})

class CorrectionOutcome(str, Enum):
    """What became of one proposed correction.

    RESOLVED is the only value that asserts success, and it is never derived
    from ActStatus.APPLIED. ACT reports that a transformation ran; only Step 9
    can say the defect is gone.
    """

    PROPOSED_UNAPPLIED = "PROPOSED_UNAPPLIED"   # ACT did not apply it
    APPLIED_UNRESOLVED = "APPLIED_UNRESOLVED"   # applied, defect not shown gone
    APPLIED_RESOLVED = "APPLIED_RESOLVED"       # applied, and VERIFY agrees


_W_CANCELLED = "execution was cancelled; there is no outcome to learn from"
_W_DENIAL = "policy refusals are not recorded as lessons"
_W_UNVERIFIED = "outcome was not verified; a lesson would be unfounded"
_W_NO_STRATEGY = "no strategy was recorded for this session"
_W_NOT_INSTRUCTIVE = "failure category says nothing about the approach"
_W_NO_CYCLE = ("a correction was proposed but no ACT/verification cycle was "
               "supplied; the outcome cannot be established")
_W_STALE = ("the cycle carries the pre-correction verification; it cannot "
            "judge the correction that came after it")


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class CorrectionCycle(_Base):
    """One ACT pass bound to the verification that judged its output.

    The two travel together so that a caller cannot pair an ActResult with a
    verification from a different moment without the mismatch being visible.
    Constructing this is the only way to declare "a correction happened and
    here is how it turned out".
    """

    act: ActResult
    # Run AFTER act, over act.artifacts. Not the report that found the defect.
    verification: VerificationReport

    @model_validator(mode="after")
    def _must_concern_the_same_work(self) -> "CorrectionCycle":
        """Reject a pair that is not about the same tasks, or not the same bytes.

        Task coverage alone was never enough: a stale pre-correction report is
        also about the right task, and only the CONTENT differs. Step 9 now
        records a fingerprint of the artefact it actually read, so a report
        describing the uncorrected artefact is caught here rather than being
        argued about downstream.
        """
        judged = {r.task_id for r in self.verification.results if r.task_id}
        applied = set(self.act.applied_tasks)
        if applied - judged:
            raise ValueError(
                "post-ACT verification does not cover every corrected task")

        for task_id in sorted(applied):
            recorded = self.verification.artifact_digests.get(task_id)
            if recorded is None:
                # Step 9 read no artefact for this task, so it settled nothing
                # about content. Not proof of staleness - _outcome_of declines
                # to call that resolved.
                continue
            if recorded != artifact_digest(self.act.artifacts.get(task_id, "")):
                raise ValueError(
                    "post-ACT verification describes a different artefact than "
                    "ACT produced")
        return self

    def proves_content_for(self, task_id: str) -> bool:
        """Whether the verification is known to describe ACT's own output.

        False when Step 9 recorded no fingerprint for the task. The constructor
        has already rejected any mismatch, so False means unproven, never wrong.
        """
        return task_id in self.verification.artifact_digests


class LearningReport(_Base):
    status: LearningStatus = LearningStatus.NOTHING_LEARNED
    candidates: List[LearningCandidate] = Field(default_factory=list)
    # What was deliberately not learned, and why. A stage that silently drops
    # things is indistinguishable from one that has nothing to say.
    withheld: List[str] = Field(default_factory=list)
    evidence_used: List[str] = Field(default_factory=list)
    # Always true when there are candidates. Nothing here is self-approving.
    requires_human_review: bool = False
    reason: str = ""

    @field_validator("reason")
    @classmethod
    def _scrub(cls, v: str) -> str:
        return redact_secrets(str(v or ""))[:REASON_MAX]

    @field_validator("withheld", "evidence_used")
    @classmethod
    def _scrub_list(cls, v: List[str]) -> List[str]:
        return [redact_secrets(str(i or ""))[:REASON_MAX] for i in v]

    @field_validator("candidates")
    @classmethod
    def _never_approved(cls, v: List[LearningCandidate]) -> List[LearningCandidate]:
        """Belt and braces over LearningCandidate's own default.

        Approval is the one thing in this pipeline that must come from a
        person, so it is checked at every layer that could set it.
        """
        for candidate in v:
            if candidate.approved:
                candidate.approved = False
        return v

    def by_category(self, category: LearningCategory) -> List[LearningCandidate]:
        return [c for c in self.candidates if c.category == category.value]


def _category_of(state: CognitiveState) -> str:
    understanding = state.understanding
    raw = (understanding.problem_category if understanding else "") or ""
    return raw if raw in _KNOWN_CATEGORIES else _UNCLASSIFIED


def _candidate(category: LearningCategory, summary: str,
               confidence: float) -> LearningCandidate:
    """Every candidate is built here, so the vocabulary rule has one gate.

    `summary` is assembled by the caller from enum values, counts and issue
    codes only. Nothing derived from a prompt or a response is ever passed in.
    """
    return LearningCandidate(
        category=category.value,
        summary=summary[:REASON_MAX],
        confidence=max(0.0, min(1.0, float(confidence))),
        approved=False,
    )


def _strategy_lesson(
    state: CognitiveState,
    verification: VerificationReport,
    withheld: List[str],
) -> Optional[LearningCandidate]:
    """Whether the chosen approach is known to have worked."""
    strategy: Optional[ReasoningStrategy] = (
        state.strategy.strategy if state.strategy else None)
    if strategy is None:
        withheld.append(_W_NO_STRATEGY)
        return None

    category = _category_of(state)

    if verification.status is VerificationStatus.VERIFIED:
        confidence = (verification.verified_count /
                      max(1, verification.verified_count + verification.failed_count))
        return _candidate(
            LearningCategory.STRATEGY_OUTCOME,
            f"strategy={strategy.value} category={category} "
            f"outcome=VERIFIED checks_passed={verification.verified_count}",
            confidence)

    if verification.status is VerificationStatus.FAILED:
        return _candidate(
            LearningCategory.STRATEGY_OUTCOME,
            f"strategy={strategy.value} category={category} "
            f"outcome=FAILED checks_failed={verification.failed_count}",
            1.0)

    # INCONCLUSIVE and NOT_REQUIRED both mean the approach was never tested.
    withheld.append(_W_UNVERIFIED)
    return None


def _capability_lessons(
    result: ExecutionResult,
    denied: Sequence[str],
    withheld: List[str],
) -> List[LearningCandidate]:
    """Which capabilities failed in a way that says something about them."""
    counts: Dict[FailureCategory, int] = {}
    for outcome in result.outcomes:
        if outcome.task_id in denied:
            continue
        category = outcome.error_category
        if category is None:
            continue
        if category not in _INSTRUCTIVE_FAILURES:
            if f"{_W_NOT_INSTRUCTIVE} ({category.value})" not in withheld:
                withheld.append(f"{_W_NOT_INSTRUCTIVE} ({category.value})")
            continue
        counts[category] = counts.get(category, 0) + 1

    return [
        _candidate(LearningCategory.CAPABILITY_RELIABILITY,
                   f"failure_category={category.value} occurrences={count}",
                   1.0)
        for category, count in sorted(counts.items(), key=lambda kv: kv[0].value)
    ]


def _gap_lessons(verification: VerificationReport) -> List[LearningCandidate]:
    """Requirements the engine was asked for and could not answer.

    The most useful thing this stage produces: it is the only record of what
    EVA cannot currently check, and unlike the others it needs no verified
    outcome, because the gap IS the observation.
    """
    requirements: List[str] = []
    for entry in verification.unverifiable:
        requirement = entry.split(":", 1)[0].strip()
        if requirement and requirement not in requirements:
            requirements.append(requirement)
    return [
        _candidate(LearningCategory.VERIFICATION_GAP,
                   f"requirement={requirement} outcome=UNVERIFIABLE", 1.0)
        for requirement in sorted(requirements)
    ]


def _final_verification(
    initial: VerificationReport,
    correction: CorrectionReport,
    cycle: Optional[CorrectionCycle],
    withheld: List[str],
) -> Optional[VerificationReport]:
    """The verification that actually settles this cycle, or None.

    When a correction was proposed, the report that found the defect is by
    definition not the one that judges the fix. Returning None is what stops a
    stale FAILED becoming the final lesson.
    """
    if correction.status is not CorrectionStatus.CORRECTIONS_PROPOSED:
        # No correction, so nothing came after: the initial report is final.
        return initial

    if cycle is None:
        withheld.append(_W_NO_CYCLE)
        return None

    if cycle.verification is initial:
        # The same object handed back as though it judged the correction.
        withheld.append(_W_STALE)
        return None

    return cycle.verification


class _CheckState(str, Enum):
    """What a post-remedy verification says about the artefact.

    Three states, because the previous two collapsed a real distinction.
    NOT_REQUIRED was treated as "nothing came back", the same as INCONCLUSIVE —
    but they are opposites. INCONCLUSIVE is the absence of evidence;
    NOT_REQUIRED is evidence of absence, and it is only reachable when an
    artefact WAS read and held no construct of that kind. An artefact that went
    missing or empty yields INCONCLUSIVE instead, which is what stops a remedy
    that destroyed the answer from passing as a repair.
    """

    SETTLED = "SETTLED"     # the check ran: VERIFIED or FAILED
    ABSENT = "ABSENT"       # the artefact was read; nothing of that kind is in it
    UNKNOWN = "UNKNOWN"     # nothing came back at all


def _check_state(verification: VerificationReport,
                 task_id: str) -> Tuple[_CheckState, set]:
    """The post-remedy state for a task, and any issue codes still reported.

    A settled verdict outranks an absent one: with several requirements on a
    task, one check reporting FAILED is decisive even while another finds
    nothing of its kind.
    """
    settled = False
    absent = False
    codes: set = set()
    for result in verification.results:
        if result.task_id != task_id:
            continue
        if result.status is VerificationStatus.VERIFIED:
            settled = True
        elif result.status is VerificationStatus.FAILED:
            settled = True
            codes.update(c.strip() for c in (result.failure_reason or "").split(",")
                         if c.strip())
        elif result.status is VerificationStatus.NOT_REQUIRED:
            absent = True
    if settled:
        return _CheckState.SETTLED, codes
    if absent:
        return _CheckState.ABSENT, codes
    return _CheckState.UNKNOWN, codes


def _outcome_of(action, cycle: Optional[CorrectionCycle]) -> CorrectionOutcome:
    """What became of one action. RESOLVED requires Step 9, never ActStatus."""
    if cycle is None or action.action_id not in cycle.act.applied_actions:
        return CorrectionOutcome.PROPOSED_UNAPPLIED

    target = action.target or ""
    if not cycle.proves_content_for(target):
        # A verdict exists, but nothing ties it to the bytes ACT produced.
        # Unproven provenance is not proof, so this cannot be RESOLVED.
        return CorrectionOutcome.APPLIED_UNRESOLVED

    state, still = _check_state(cycle.verification, target)

    if state is _CheckState.SETTLED:
        # The check ran. It is proof either way.
        if action.issue in still:
            return CorrectionOutcome.APPLIED_UNRESOLVED
        return CorrectionOutcome.APPLIED_RESOLVED

    if state is _CheckState.ABSENT:
        # The artefact was read and holds no construct of that kind. Whether
        # that is success depends on what the remedy set out to do, which only
        # the remedy knows: a removal remedy deleting its block IS the repair,
        # while a repair-in-place remedy whose block vanished has failed in a
        # way that must not be mistaken for success.
        if remedy_removes_construct(action.issue):
            return CorrectionOutcome.APPLIED_RESOLVED
        return CorrectionOutcome.APPLIED_UNRESOLVED

    # UNKNOWN: nothing came back. Absence of evidence is not evidence.
    return CorrectionOutcome.APPLIED_UNRESOLVED


def _by_outcome(correction: CorrectionReport,
                cycle: Optional[CorrectionCycle]) -> Dict[tuple, int]:
    """(issue, outcome) -> count. The shared basis for B2 and B3."""
    counts: Dict[tuple, int] = {}
    for action in correction.corrections:
        if not action.issue:
            continue
        key = (action.issue, _outcome_of(action, cycle))
        counts[key] = counts.get(key, 0) + 1
    return counts


# A lesson drawn from a settled verdict is worth more than one drawn from a
# proposal nobody applied. Fixed values, so the report stays deterministic.
_CONFIDENCE_BY_OUTCOME = {
    CorrectionOutcome.APPLIED_RESOLVED: 1.0,
    CorrectionOutcome.APPLIED_UNRESOLVED: 1.0,
    CorrectionOutcome.PROPOSED_UNAPPLIED: 0.5,
}


def _defect_lessons(counts: Dict[tuple, int]) -> List[LearningCandidate]:
    """Which defects occurred, and what became of the correction for each.

    Issue codes are review_engine's fixed vocabulary and outcomes are this
    module's enum, so nothing free-form reaches a candidate.
    """
    return [
        _candidate(LearningCategory.RECURRING_DEFECT,
                   f"issue={issue} occurrences={count} status={outcome.value}",
                   _CONFIDENCE_BY_OUTCOME[outcome])
        for (issue, outcome), count in sorted(counts.items(),
                                              key=lambda kv: (kv[0][0], kv[0][1].value))
    ]


def _efficacy_lessons(counts: Dict[tuple, int]) -> List[LearningCandidate]:
    """Whether the remedy for an issue code actually worked.

    The one thing the loop could not record before Step 11: a defect, the
    remedy applied to it, and an independent verdict on whether that helped.
    Nothing here is inferred from ACT alone.
    """
    return [
        _candidate(
            LearningCategory.REMEDY_EFFICACY,
            f"issue={issue} remedy=deterministic "
            f"applied={'no' if outcome is CorrectionOutcome.PROPOSED_UNAPPLIED else 'yes'} "
            f"outcome={outcome.value} occurrences={count}",
            _CONFIDENCE_BY_OUTCOME[outcome])
        for (issue, outcome), count in sorted(counts.items(),
                                              key=lambda kv: (kv[0][0], kv[0][1].value))
    ]


def learn(
    state: CognitiveState,
    result: ExecutionResult,
    verification: VerificationReport,
    correction: CorrectionReport,
    cycle: Optional[CorrectionCycle] = None,
) -> LearningReport:
    """Draw whatever lessons the evidence supports, and say what it withheld.

    `verification` is the report that judged the original work. When a
    correction was proposed, it is NOT the outcome - `cycle` carries the ACT
    pass and the verification that judged it, and without one every
    outcome-dependent lesson is withheld.

    Deterministic and side-effect free: `state` is read, never written, and the
    same inputs always give the same report. emit() and apply_to_state() are
    separate calls so a caller can inspect the lessons before any of them go
    anywhere.
    """
    withheld: List[str] = []
    evidence_used: List[str] = []

    # ── cancellation: the work never finished ───────────────────────────────
    if (result.final_execution_status is ExecutionStatus.CANCELLED
            or correction.status is CorrectionStatus.CANCELLED):
        return LearningReport(
            status=LearningStatus.WITHHELD,
            withheld=[_W_CANCELLED],
            reason=_W_CANCELLED,
            requires_human_review=False,
        )

    denied = list(result.denied_tasks)
    if denied:
        withheld.append(f"{_W_DENIAL} ({len(denied)} refused)")

    candidates: List[LearningCandidate] = []

    # Which report settles this cycle. None means the outcome is unestablished,
    # and every lesson that depends on one is withheld rather than guessed.
    final = _final_verification(verification, correction, cycle, withheld)

    if final is not None:
        strategy_lesson = _strategy_lesson(state, final, withheld)
        if strategy_lesson is not None:
            candidates.append(strategy_lesson)
            evidence_used.append(f"final_verification={final.status.value}")
            evidence_used.append(f"cycle={'yes' if cycle else 'no'}")

    capability_lessons = _capability_lessons(result, denied, withheld)
    if capability_lessons:
        candidates.extend(capability_lessons)
        evidence_used.append(f"outcomes={len(result.outcomes)}")

    # Gaps are what EVA cannot check. That does not depend on whether a
    # correction worked, so it survives an unestablished outcome. Both reports
    # contribute; identical requirements collapse in the dedupe below.
    gap_reports = [verification] + ([cycle.verification] if cycle else [])
    gap_lessons = [lesson for r in gap_reports for lesson in _gap_lessons(r)]
    if gap_lessons:
        candidates.extend(gap_lessons)
        evidence_used.append(
            f"unverifiable={sum(len(r.unverifiable) for r in gap_reports)}")

    # Defect and efficacy lessons share one basis so the two can never disagree
    # about what became of a correction.
    outcomes = _by_outcome(correction, cycle if final is not None else None)
    if outcomes:
        candidates.extend(_defect_lessons(outcomes))
        candidates.extend(_efficacy_lessons(outcomes))
        evidence_used.append(f"corrections={len(correction.corrections)}")

    # Two lessons with the same text are one lesson observed twice.
    seen: List[str] = []
    deduped: List[LearningCandidate] = []
    for candidate in candidates:
        key = f"{candidate.category}|{candidate.summary}"
        if key not in seen:
            seen.append(key)
            deduped.append(candidate)

    if deduped:
        status = LearningStatus.CANDIDATES_PROPOSED
        reason = f"{len(deduped)} candidate(s) proposed; human approval required"
    elif withheld:
        status = LearningStatus.WITHHELD
        reason = "nothing could be learned from this session"
    else:
        status = LearningStatus.NOTHING_LEARNED
        reason = "the session produced no observation worth keeping"

    return LearningReport(
        status=status,
        candidates=deduped,
        withheld=withheld,
        evidence_used=evidence_used,
        requires_human_review=bool(deduped),
        reason=reason,
    )


def emit(report: LearningReport,
         sink: Optional[Callable[[LearningCandidate], bool]] = None) -> int:
    """Hand candidates to an injected sink. The only exit from this module.

    There is no default sink, and that is deliberate rather than an omission:
    a default would decide on the caller's behalf where training data goes.
    Without one, nothing leaves — which is the safe direction for a stage whose
    output is destined for a review queue.

    A sink that raises is treated as having rejected the candidate. Learning is
    the least important thing happening in a request, and it must never be the
    reason one fails.
    """
    if sink is None:
        return 0
    accepted = 0
    for candidate in report.candidates:
        if candidate.approved:      # unreachable; asserted rather than assumed
            continue
        try:
            if sink(candidate):
                accepted += 1
        except Exception:
            continue
    return accepted


def apply_to_state(state: CognitiveState, report: LearningReport) -> CognitiveState:
    """Record the candidates on the state and close the session.

    LEARN has no outgoing edges in Step 2's graph, so RESPOND is reached as a
    universal target — the same route that lets a session out when its
    transition budget is spent. Nothing here can send the engine round again:
    learning is an observation, not a reason to act.
    """
    for candidate in report.candidates:
        candidate.approved = False   # validator-pinned; kept explicit at the boundary
        state.learning_candidates.append(candidate)

    if state.phase is not CognitivePhase.LEARN and \
            state.can_transition_to(CognitivePhase.LEARN):
        state.transition_to(CognitivePhase.LEARN)

    if state.can_transition_to(CognitivePhase.RESPOND):
        state.transition_to(CognitivePhase.RESPOND)
    return state
