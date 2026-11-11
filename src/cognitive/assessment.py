"""Assessment — Step 4 of the Cognitive Engine.

Answers one question: **how ready is EVA to solve this problem?**

It does not solve it, does not choose a strategy, and does not fetch anything.
The boundary matters and is easy to blur:

    Step 3 asks  "what would reduce my uncertainty?"
    Step 4 asks  "is that missing thing important enough to get first?"
    Step 5 asks  "how should we solve it?"

So Assessment identifies the NEED for exploration; it never explores. There is
no RAG call, no tool call, no file, database, network or subprocess access in
this module — it is a pure function of (understanding, evidence, context).

WHY A SEPARATE REPORT TYPE
==========================
Step 2 already defines KnowledgeAssessment, and CognitiveState.assessment is
typed to it. But that model is a thin four-flag summary, while Step 4 has to
express sufficiency as a four-value judgement, plus risk, constraint status,
conflicts and three separate readiness decisions.

Rather than widen the Step 2 model — which the brief explicitly puts
off-limits — AssessmentReport is the full Step 4 output, and
to_knowledge_assessment() projects it down to the shape CognitiveState already
accepts. Step 2 stays untouched, and the state is still populated through its
existing public interface.

DETERMINISTIC FIRST
===================
Same policy as Step 3, for the same reason: this runs on every message and the
project has exhausted its provider quota twice. Everything here is computed
locally. An `llm` parameter exists so a future model-assisted assessment can be
injected, but it is optional, never imported, and the deterministic result
stands if it is absent, raises, or returns junk.

NO CHAIN OF THOUGHT. `assessment_summary` is one short operational sentence
("evidence is incomplete because the error condition is unspecified"), capped
in length, and there is no field anywhere for a reasoning trace.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Callable, List, Optional, Sequence, Set, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .state import (
    KnowledgeAssessment,
    ProblemUnderstanding,
    REASON_MAX,
    redact_secrets,
)

SUMMARY_MAX = 300

# Requests whose answer depends on information that can change over time.
# Assessment only marks the need for exploration; it never fetches anything.
_EXTERNAL_FRESHNESS_RE = re.compile(
    r"\b(latest|current|today|recent|recently|news|price|prices|weather|"
    r"release|released|newest|up[- ]to[- ]date)\b",
    re.IGNORECASE,
)



# ── vocabularies ─────────────────────────────────────────────────────────────
class EvidenceSufficiency(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"
    UNKNOWN = "UNKNOWN"


class InformationCompleteness(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    INCOMPLETE = "INCOMPLETE"
    UNKNOWN = "UNKNOWN"


class RiskLevel(str, Enum):
    """Reuses the severity vocabulary already used throughout src/security/
    (ai_firewall, aws_iam_guard, bedrock_guard, behavior_analyzer) rather than
    introducing a parallel scale that would have to be mapped at every
    boundary. SAFE is EVA's existing baseline, not an invention here.

    ADVISORY ONLY. A HIGH here does not block anything; the firewall owns
    enforcement and runs ahead of the engine.
    """

    SAFE = "SAFE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ConstraintStatus(str, Enum):
    NONE = "NONE"                 # no constraints were stated
    SATISFIED = "SATISFIED"
    PARTIAL = "PARTIAL"
    CONFLICTING = "CONFLICTING"
    UNKNOWN = "UNKNOWN"


class AmbiguityStatus(str, Enum):
    RESOLVED = "RESOLVED"         # Step 3 flagged none, or evidence answers them
    TOLERABLE = "TOLERABLE"       # unresolved but we can proceed and check later
    BLOCKING = "BLOCKING"         # cannot proceed without asking
    UNKNOWN = "UNKNOWN"


class EvidenceKind(str, Enum):
    DIRECT = "DIRECT"             # observed fact, e.g. a captured stack trace
    USER_CLAIM = "USER_CLAIM"     # asserted by the user, not verified
    RETRIEVED = "RETRIEVED"       # from RAG/documents
    CONTEXTUAL = "CONTEXTUAL"     # earlier in this conversation
    INFERRED = "INFERRED"         # derived, not observed


# Deliberately ordered: how much weight a kind carries toward sufficiency.
# An inference is not evidence that something is true, so it cannot on its own
# make a body of evidence sufficient — treating assumptions as facts is the
# specific failure this ordering exists to prevent.
_KIND_WEIGHT = {
    EvidenceKind.DIRECT: 1.0,
    EvidenceKind.RETRIEVED: 0.9,
    EvidenceKind.CONTEXTUAL: 0.7,
    EvidenceKind.USER_CLAIM: 0.6,
    EvidenceKind.INFERRED: 0.3,
}


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class EvidenceItem(_Base):
    """One piece of evidence supplied BY THE CALLER. Assessment never gathers
    these itself — that is exploration, and belongs to a later stage."""

    ref: str = ""
    kind: EvidenceKind = EvidenceKind.USER_CLAIM
    claim: str = ""
    confidence: float = 0.5
    stale: bool = False

    @field_validator("ref", "claim")
    @classmethod
    def _scrub(cls, v: str) -> str:
        return redact_secrets(str(v or ""))[:REASON_MAX]

    @field_validator("confidence")
    @classmethod
    def _bounded(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))


class EvidenceConflict(_Base):
    """A contradiction between two pieces of evidence.

    Recorded, never silently resolved: choosing a side here would be reasoning,
    and reasoning belongs to Strategy.
    """

    left_ref: str = ""
    right_ref: str = ""
    description: str = ""

    @field_validator("left_ref", "right_ref", "description")
    @classmethod
    def _scrub(cls, v: str) -> str:
        return redact_secrets(str(v or ""))[:REASON_MAX]


class AssessmentReport(_Base):
    evidence_sufficiency: EvidenceSufficiency = EvidenceSufficiency.UNKNOWN
    information_completeness: InformationCompleteness = InformationCompleteness.UNKNOWN
    confidence: float = 0.0
    risk_level: RiskLevel = RiskLevel.SAFE
    constraint_status: ConstraintStatus = ConstraintStatus.NONE
    ambiguity_status: AmbiguityStatus = AmbiguityStatus.UNKNOWN

    evidence_conflicts: List[EvidenceConflict] = Field(default_factory=list)
    known_information: List[str] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)
    # Phase 1: things taken as true WITHOUT evidence, kept apart from
    # known_information so an assumption is never counted as an established fact.
    assumptions: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    # Known, but not relevant to anything the problem actually needs. Kept
    # separate so completeness is never inflated by material that does not help.
    irrelevant_information: List[str] = Field(default_factory=list)

    exploration_required: bool = False
    clarification_required: bool = False
    ready_for_strategy: bool = False
    assessment_summary: str = ""

    @field_validator("known_information", "missing_information", "assumptions", "evidence_refs", "irrelevant_information")
    @classmethod
    def _scrub_list(cls, v: List[str]) -> List[str]:
        return [redact_secrets(str(i or ""))[:REASON_MAX] for i in v]

    @field_validator("assessment_summary")
    @classmethod
    def _scrub_summary(cls, v: str) -> str:
        return redact_secrets(str(v or ""))[:SUMMARY_MAX]

    @field_validator("confidence")
    @classmethod
    def _bounded(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    def to_knowledge_assessment(self) -> KnowledgeAssessment:
        """Project into the Step 2 model so CognitiveState.assessment can hold
        it without widening that model."""
        return KnowledgeAssessment(
            known_information=list(self.known_information),
            missing_information=list(self.missing_information),
            assumptions=list(self.assumptions),
            evidence_refs=list(self.evidence_refs),
            retrieval_required=self.exploration_required,
            tools_required=[],
            evidence_sufficient=self.evidence_sufficiency is EvidenceSufficiency.SUFFICIENT,
            confidence=self.confidence,
        )


# ── deterministic helpers ────────────────────────────────────────────────────
_STOP = set("""a an the and or but if then than that this these those of in on at to for from by with
is are was were be been being do does did have has had it its as not no so such can could will would
what which who when where why how all any both each more most other some only same too very i you we
my your our their there here about into out up down over under again once""".split())


def _terms(text: str) -> Set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) > 2 and w not in _STOP}


def _addresses(need: str, evidence_text: str) -> bool:
    """Does this evidence speak to that information need?

    Overlap of distinctive terms. Deliberately not a count of fields: a body of
    evidence can be large and still address none of what the problem requires,
    which is exactly the 'known but irrelevant' case the brief calls out.
    """
    need_terms = _terms(need)
    if not need_terms:
        return False
    evidence_terms = _terms(evidence_text)

    hit = set(need_terms & evidence_terms)

    # Exact intersection alone is too brittle for real evidence: the need
    # "error message" scores zero against "TypeError: cannot read property
    # 'loaded'", because `error` and `typeerror` are different strings. A stack
    # trace plainly IS an error message, and reporting it as missing would send
    # the engine exploring for something it already has.
    #
    # Containment covers the common morphology (typeerror/error,
    # reproduction/reproduce, latency/latencies) without a stemmer. The length
    # floor keeps short fragments from matching everything.
    for need_term in need_terms - hit:
        if len(need_term) < 4:
            continue
        if any(need_term in ev_term or (len(ev_term) >= 4 and ev_term in need_term)
               for ev_term in evidence_terms):
            hit.add(need_term)

    # One distinctive term is enough for a short need ("error message"), but
    # longer needs must match more than a single incidental word.
    required = 1 if len(need_terms) <= 2 else 2
    return len(hit) >= required


# Opposing polarity pairs for conflict detection. Each entry is a pair of
# families; evidence sharing a subject but drawn from opposite families is a
# candidate contradiction.
_POLARITY = [
    ({"success", "successful", "successfully", "completed", "complete", "passed", "works", "working", "ok", "healthy"},
     {"fail", "failed", "failure", "error", "errors", "broken", "crash", "crashed", "missing", "lost", "corrupt"}),
    ({"present", "found", "exists", "available"},
     {"absent", "missing", "notfound", "unavailable", "gone"}),
    ({"increased", "higher", "faster", "up"},
     {"decreased", "lower", "slower", "down"}),
    ({"enabled", "active", "on"},
     {"disabled", "inactive", "off"}),
]


def _detect_conflicts(evidence: Sequence[EvidenceItem]) -> List[EvidenceConflict]:
    """Pairwise polarity clash on a shared subject.

    Conservative on purpose: two statements about different things are not a
    conflict, so a shared subject term is required before opposing polarity
    counts. Reporting phantom conflicts would push the engine into needless
    exploration loops.
    """
    conflicts: List[EvidenceConflict] = []
    items = list(evidence)
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            a_terms, b_terms = _terms(a.claim), _terms(b.claim)
            shared = (a_terms & b_terms) - set().union(*[p | n for p, n in _POLARITY])
            if not shared:
                continue
            for positive, negative in _POLARITY:
                a_pos, a_neg = bool(a_terms & positive), bool(a_terms & negative)
                b_pos, b_neg = bool(b_terms & positive), bool(b_terms & negative)
                if (a_pos and b_neg) or (a_neg and b_pos):
                    subject = sorted(shared)[0]
                    conflicts.append(EvidenceConflict(
                        left_ref=a.ref or f"evidence[{i}]",
                        right_ref=b.ref or f"evidence[{j}]",
                        description=f"conflicting statements about '{subject}'",
                    ))
                    break
    return conflicts


# Operations that carry consequence if acted on with poor evidence. Advisory
# only — this raises the reported risk, it never blocks anything.
_RISKY_OPERATION_RE = re.compile(
    r"\b(delete|drop|truncate|wipe|erase|destroy|revoke|shut ?down|rm\s+-rf|"
    r"force[- ]?push|production|prod\b|live database|customer data|payroll|invoice)\b",
    re.I,
)
_SENSITIVE_MARKER_RE = re.compile(r"sensitive|security-restricted|restricted", re.I)


def _assess_risk(
    understanding: ProblemUnderstanding,
    evidence: Sequence[EvidenceItem],
    problem: str = "",
) -> RiskLevel:
    # `problem` is the user's own words. ProblemUnderstanding deliberately does
    # not carry them — it holds a category and a desired outcome — so without
    # this argument "delete the production database" assesses as SAFE: none of
    # intent, desired_outcome or constraints contains "delete" or "production".
    # Under-reporting risk on a destructive request is the worst direction to
    # be wrong in, so the raw text is passed in rather than inferred.
    text = " ".join([problem or "", understanding.intent, understanding.desired_outcome,
                     " ".join(understanding.constraints)])
    flagged = any(_SENSITIVE_MARKER_RE.search(c) for c in understanding.constraints)
    risky_op = bool(_RISKY_OPERATION_RE.search(text)) or any(
        _RISKY_OPERATION_RE.search(e.claim) for e in evidence
    )
    if flagged and risky_op:
        return RiskLevel.CRITICAL
    if flagged:
        return RiskLevel.HIGH
    if risky_op:
        # A consequential operation with thin evidence is riskier than one that
        # is well established.
        strong = any(e.kind in (EvidenceKind.DIRECT, EvidenceKind.RETRIEVED) for e in evidence)
        return RiskLevel.MEDIUM if strong else RiskLevel.HIGH
    return RiskLevel.SAFE


# Constraint phrasing that opposes another constraint, e.g. "must use Python"
# alongside "must use Rust".
_MUST_RE = re.compile(r"\b(must|need|require[sd]?|only|has to|should)\b", re.I)


def _assess_constraints(
    understanding: ProblemUnderstanding, evidence: Sequence[EvidenceItem]
) -> Tuple[ConstraintStatus, List[str]]:
    stated = [c for c in understanding.constraints if c and not _SENSITIVE_MARKER_RE.search(c)]
    if not stated:
        return ConstraintStatus.NONE, []

    # Two hard constraints naming different values for the same dimension.
    unmet: List[str] = []
    conflicting = False
    for i in range(len(stated)):
        for j in range(i + 1, len(stated)):
            a, b = stated[i], stated[j]
            if _MUST_RE.search(a) and _MUST_RE.search(b):
                a_terms, b_terms = _terms(a), _terms(b)
                shared = a_terms & b_terms
                distinct = (a_terms ^ b_terms)
                # same dimension (shared noun) but different required values
                if shared and distinct:
                    conflicting = True
    if conflicting:
        return ConstraintStatus.CONFLICTING, stated

    evidence_text = " ".join(e.claim for e in evidence)
    for c in stated:
        if not _addresses(c, evidence_text):
            unmet.append(c)
    if not unmet:
        return ConstraintStatus.SATISFIED, []
    if len(unmet) < len(stated):
        return ConstraintStatus.PARTIAL, unmet
    return ConstraintStatus.UNKNOWN, unmet


def _summarise(
    sufficiency: EvidenceSufficiency,
    missing: Sequence[str],
    conflicts: Sequence[EvidenceConflict],
    ambiguity: AmbiguityStatus,
    risk: RiskLevel,
) -> str:
    """One short operational sentence. Not a reasoning trace — it states the
    conclusion and its immediate cause, nothing about how it was reached."""
    if conflicts:
        return f"evidence conflicts on {len(conflicts)} point(s); resolve before proceeding"
    if ambiguity is AmbiguityStatus.BLOCKING:
        return "the request is ambiguous in a way available evidence cannot resolve"
    if sufficiency is EvidenceSufficiency.INSUFFICIENT:
        first = missing[0] if missing else "required detail"
        return f"evidence is incomplete because {first} is unspecified"
    if sufficiency is EvidenceSufficiency.PARTIAL:
        return f"partial evidence; {len(missing)} information need(s) still open"
    if risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
        return f"evidence is sufficient but the request carries {risk.value.lower()} risk"
    return "evidence is sufficient for strategy selection"


# ── main entry point ─────────────────────────────────────────────────────────
def assess(
    understanding: ProblemUnderstanding,
    evidence: Optional[Sequence[EvidenceItem]] = None,
    context: Optional[Sequence[str]] = None,
    problem: str = "",
    llm: Optional[Callable[[str], str]] = None,
) -> AssessmentReport:
    """Judge readiness. Pure, deterministic, repeatable.

    Repeatable is load-bearing: the engine is expected to call this again after
    ACT gathers something, and the later call must be free to reach a different
    verdict. Nothing is cached and no prior result is consulted, so a stale
    assessment cannot outlive the evidence it was based on.

    `problem` is the user's original wording, used only for risk detection —
    ProblemUnderstanding holds a category, not the raw request, and destructive
    verbs live in the raw request. Callers already have it as
    CognitiveState.problem.

    `llm` is accepted for a future model-assisted pass and is currently unused
    by the deterministic path; it is never imported, only injected.
    """
    evidence = list(evidence or [])
    context = [c for c in (context or []) if str(c).strip()]

    needs = [n for n in (understanding.required_information or []) if str(n).strip()]
    evidence_text = " ".join([e.claim for e in evidence] + list(context))

    # Which needs does the available material actually address?
    addressed, still_missing = [], []
    for need in needs:
        (addressed if _addresses(need, evidence_text) else still_missing).append(need)

    # Evidence that addresses nothing the problem needs is known, but does not
    # count toward completeness.
    relevant_refs, irrelevant = [], []
    for item in evidence:
        ref = item.ref or item.claim[:60]
        if needs and not any(_addresses(n, item.claim) for n in needs):
            irrelevant.append(ref)
        else:
            relevant_refs.append(ref)

    conflicts = _detect_conflicts(evidence)

    # ── sufficiency ──────────────────────────────────────────────────────────
    usable = [e for e in evidence if not e.stale]
    weight = sum(_KIND_WEIGHT.get(e.kind, 0.3) * e.confidence for e in usable)
    if conflicts:
        # Contradictory evidence cannot be sufficient however much there is.
        sufficiency = EvidenceSufficiency.PARTIAL
    elif not needs:
        # Nothing was required. Sufficient if the problem itself was understood.
        sufficiency = (EvidenceSufficiency.SUFFICIENT if understanding.confidence >= 0.5
                       else EvidenceSufficiency.UNKNOWN)
    elif not still_missing:
        sufficiency = EvidenceSufficiency.SUFFICIENT
    elif addressed or weight >= 0.6:
        sufficiency = EvidenceSufficiency.PARTIAL
    else:
        sufficiency = EvidenceSufficiency.INSUFFICIENT

    # ── completeness ─────────────────────────────────────────────────────────
    if not needs:
        completeness = (InformationCompleteness.COMPLETE if understanding.confidence >= 0.5
                        else InformationCompleteness.UNKNOWN)
    elif not still_missing:
        completeness = InformationCompleteness.COMPLETE
    elif addressed:
        completeness = InformationCompleteness.PARTIAL
    else:
        completeness = InformationCompleteness.INCOMPLETE

    # ── ambiguity consequences (Step 3 detects; Step 4 judges the impact) ────
    open_ambiguities = list(understanding.ambiguities or [])
    if not open_ambiguities:
        ambiguity_status = AmbiguityStatus.RESOLVED
    elif all(_addresses(a, evidence_text) for a in open_ambiguities):
        ambiguity_status = AmbiguityStatus.RESOLVED
    elif understanding.needs_clarification or understanding.confidence < 0.25:
        ambiguity_status = AmbiguityStatus.BLOCKING
    else:
        ambiguity_status = AmbiguityStatus.TOLERABLE

    risk = _assess_risk(understanding, evidence, problem=problem)
    constraint_status, unmet = _assess_constraints(understanding, evidence)

    # ── decisions ────────────────────────────────────────────────────────────
    freshness_requested = bool(
        _EXTERNAL_FRESHNESS_RE.search(problem or "")
    )
    exploration_required = (
        bool(still_missing)
        or bool(conflicts)
        or freshness_requested
    )
    clarification_required = ambiguity_status is AmbiguityStatus.BLOCKING

    ready_for_strategy = (
        sufficiency in (EvidenceSufficiency.SUFFICIENT, EvidenceSufficiency.PARTIAL)
        and not clarification_required
        and not conflicts
        and constraint_status is not ConstraintStatus.CONFLICTING
        and risk is not RiskLevel.CRITICAL
    )
    # PARTIAL only qualifies when the remaining gaps are tolerable, i.e. nothing
    # is blocking and the problem itself was understood.
    if sufficiency is EvidenceSufficiency.PARTIAL and understanding.confidence < 0.4:
        ready_for_strategy = False

    confidence = round(min(1.0, max(0.0,
        0.5 * understanding.confidence
        + 0.3 * (1.0 if sufficiency is EvidenceSufficiency.SUFFICIENT
                 else 0.5 if sufficiency is EvidenceSufficiency.PARTIAL else 0.0)
        + 0.2 * (1.0 if completeness is InformationCompleteness.COMPLETE
                 else 0.5 if completeness is InformationCompleteness.PARTIAL else 0.0)
        - 0.15 * len(conflicts)
    )), 3)

    return AssessmentReport(
        evidence_sufficiency=sufficiency,
        information_completeness=completeness,
        confidence=confidence,
        risk_level=risk,
        constraint_status=constraint_status,
        ambiguity_status=ambiguity_status,
        evidence_conflicts=conflicts,
        known_information=addressed + [e.claim[:REASON_MAX] for e in evidence if e.claim],
        missing_information=still_missing + unmet,
        evidence_refs=relevant_refs,
        irrelevant_information=irrelevant,
        exploration_required=exploration_required,
        clarification_required=clarification_required,
        ready_for_strategy=ready_for_strategy,
        assessment_summary=_summarise(sufficiency, still_missing, conflicts, ambiguity_status, risk),
    )
