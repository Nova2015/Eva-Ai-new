"""CognitiveState — the typed record of one problem-solving session.

Step 2 of the Cognitive Engine. This module is DATA ONLY: it defines the shape
that Understanding, Assessment, Strategy, Planning, Execution, Verification,
Correction and Learning will read and write. It performs no I/O, calls no
model, and is not imported by src/app.py, so nothing about chat behaviour
changes by adding it.

Three vocabularies already exist in this codebase and are deliberately reused
rather than re-invented:

  * TaskStatus extends autopilot.py's RUNNING/COMPLETED/FAILED with the
    PENDING/SKIPPED/RETRY the planner needs. CANCELLED is kept because
    autopilot already supports cooperative cancellation and the executor will
    inherit it.
  * VerificationStatus maps onto review_engine's existing fatal/warn/clean
    verdicts rather than introducing a parallel notion of "valid".
  * LearningCandidate mirrors learning_loop.py's capture model, including the
    principle that nothing reaches a dataset without human approval.

TWO HARD RULES, enforced in code rather than documented and hoped for:

1. No hidden chain-of-thought is stored. There is no field for free-form model
   reasoning anywhere in this model. Every explanatory field is a short,
   loggable rationale (`reason`, `summary`) with a length cap that makes it
   unsuitable for smuggling a reasoning trace. This is a storage-shape
   decision: a field that does not exist cannot be filled in later by accident.

2. Secrets are redacted on write. Every free-text field passes through
   redact_secrets(). Redaction rather than rejection is a deliberate choice:
   once this is wired into chat, raising on a key-shaped string would turn a
   security control into an availability bug — a user pasting a token into a
   question would get an error instead of an answer. Redaction satisfies "no
   secrets stored in state" while degrading gracefully.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator

# Bounds. Defaults, not hard limits — the engine may lower them per request,
# but never raise them past these ceilings (enforced in CognitiveState).
DEFAULT_MAX_RETRIES = 2
DEFAULT_MAX_TASKS = 12
MAX_RETRIES_CEILING = 5
MAX_TASKS_CEILING = 25

# Hard bound on total phase moves in one session. The transition graph is
# cyclic by design (see _ALLOWED_TRANSITIONS), so this — not the graph — is
# what guarantees a session ends. Sized to allow several genuine
# explore/reassess/re-strategise rounds while still terminating a runaway loop
# quickly enough to matter to a waiting user.
DEFAULT_MAX_TRANSITIONS = 40
MAX_TRANSITIONS_CEILING = 100

# Length caps. These are what stop `reason`/`summary` from becoming a
# chain-of-thought dumping ground.
REASON_MAX = 400
TEXT_MAX = 4000
EVIDENCE_MAX = 12000


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Secret redaction ─────────────────────────────────────────────────────────
# Patterns are intentionally conservative: each targets a shape that is almost
# never legitimate prose. A false positive costs one redacted substring; a
# false negative writes a live credential into persisted state.
_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b"),                 # OpenAI-style
    re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{16,}\b"),       # Stripe-style
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                        # AWS access key id
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),              # GitHub tokens
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"),           # Slack tokens
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),  # JWT
    re.compile(r"(?i)\b(?:api[_\-]?key|secret|password|passwd|token)\s*[:=]\s*\S{6,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{20,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
)

REDACTED = "[REDACTED]"


def redact_secrets(value: str) -> str:
    """Replace credential-shaped substrings. Never raises."""
    if not value:
        return value
    out = value
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub(REDACTED, out)
    return out


def _clean(value: Optional[str], limit: int = TEXT_MAX) -> Optional[str]:
    if value is None:
        return None
    return redact_secrets(str(value))[:limit]


# ── Enumerations ─────────────────────────────────────────────────────────────
class CognitivePhase(str, Enum):
    """Lifecycle position. RESPOND and ABORTED are the only terminal phases."""

    UNDERSTAND = "UNDERSTAND"
    ASSESS = "ASSESS"
    STRATEGY = "STRATEGY"
    PLAN = "PLAN"
    ACT = "ACT"
    VERIFY = "VERIFY"
    CORRECT = "CORRECT"
    LEARN = "LEARN"
    RESPOND = "RESPOND"
    ABORTED = "ABORTED"


class ReasoningStrategy(str, Enum):
    DIRECT = "DIRECT"
    RETRIEVAL = "RETRIEVAL"
    CALCULATION = "CALCULATION"
    CODE = "CODE"
    ANALYSIS = "ANALYSIS"
    MULTI_STEP = "MULTI_STEP"
    TOOL_ASSISTED = "TOOL_ASSISTED"
    CLARIFICATION = "CLARIFICATION"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    RETRY = "RETRY"
    CANCELLED = "CANCELLED"   # matches autopilot's cooperative cancellation


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"
    NOT_REQUIRED = "NOT_REQUIRED"


class FailureCategory(str, Enum):
    MISSING_INFORMATION = "MISSING_INFORMATION"
    TOOL_FAILURE = "TOOL_FAILURE"
    INVALID_INPUT = "INVALID_INPUT"
    EXECUTION_FAILURE = "EXECUTION_FAILURE"
    VERIFICATION_FAILURE = "VERIFICATION_FAILURE"
    MODEL_FAILURE = "MODEL_FAILURE"
    TIMEOUT = "TIMEOUT"
    SECURITY_BLOCK = "SECURITY_BLOCK"
    UNSUPPORTED_TASK = "UNSUPPORTED_TASK"


# Legal transitions.
#
# This graph is deliberately CYCLIC. EVA is meant to be an adaptive
# problem-solver, not a one-pass pipeline: it must be able to act, discover
# something, reassess with the new evidence, switch strategy, try a different
# capability, verify, and go round again. An earlier version of this map only
# allowed forward motion plus CORRECT -> PLAN/ACT, which silently locked the
# engine into whatever strategy it picked on the first pass — acting could
# never feed back into assessment.
#
# The edges that make adaptation possible, and why each exists:
#   ACT     -> ASSESS     evidence gathered; re-evaluate what is now known
#   VERIFY  -> ASSESS     verification exposed a gap rather than a wrong answer
#   CORRECT -> ASSESS     rethink the evidence before retrying
#   CORRECT -> STRATEGY   the approach itself was wrong, not the execution
#   CORRECT -> UNDERSTAND the problem was misread; start from the question
#
# Because the graph now contains genuine cycles, the GRAPH CANNOT GUARANTEE
# TERMINATION. Two independent bounds do:
#   * the retry budget (register_retry), which the engine consumes deliberately;
#   * max_transitions, enforced inside transition_to() on EVERY move.
# The second exists because the first depends on callers remembering to call
# it. A buggy engine looping ACT -> ASSESS -> STRATEGY -> ACT would never touch
# the retry budget, so a structural bound is the only thing that actually stops
# it. RESPOND and ABORTED stay reachable even when the bound is spent —
# otherwise a state that ran out of moves could not terminate cleanly.
_ALLOWED_TRANSITIONS: Dict[CognitivePhase, set] = {
    CognitivePhase.UNDERSTAND: {CognitivePhase.ASSESS},
    CognitivePhase.ASSESS: {CognitivePhase.STRATEGY, CognitivePhase.UNDERSTAND},
    CognitivePhase.STRATEGY: {CognitivePhase.PLAN, CognitivePhase.ACT, CognitivePhase.ASSESS},
    CognitivePhase.PLAN: {CognitivePhase.ACT, CognitivePhase.STRATEGY},
    CognitivePhase.ACT: {CognitivePhase.VERIFY, CognitivePhase.ACT, CognitivePhase.ASSESS},
    CognitivePhase.VERIFY: {CognitivePhase.CORRECT, CognitivePhase.LEARN, CognitivePhase.ASSESS},
    CognitivePhase.CORRECT: {
        CognitivePhase.PLAN, CognitivePhase.ACT, CognitivePhase.ASSESS,
        CognitivePhase.STRATEGY, CognitivePhase.UNDERSTAND,
    },
    CognitivePhase.LEARN: set(),
    CognitivePhase.RESPOND: set(),
    CognitivePhase.ABORTED: set(),
}

_UNIVERSAL_TARGETS = {CognitivePhase.RESPOND, CognitivePhase.ABORTED}


class _Base(BaseModel):
    """Shared config. extra='forbid' turns a typo into a test failure rather
    than a silently ignored field — these objects cross stage boundaries, so a
    misspelled key would otherwise vanish without trace."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# ── Stage payloads ───────────────────────────────────────────────────────────
class ProblemUnderstanding(_Base):
    """Output of Step 3."""

    intent: str = ""
    problem_category: str = ""
    desired_outcome: str = ""
    constraints: List[str] = Field(default_factory=list)
    ambiguities: List[str] = Field(default_factory=list)
    required_information: List[str] = Field(default_factory=list)
    needs_clarification: bool = False
    confidence: float = 0.0

    @field_validator("intent", "problem_category", "desired_outcome")
    @classmethod
    def _scrub(cls, v: str) -> str:
        return _clean(v, REASON_MAX) or ""

    @field_validator("constraints", "ambiguities", "required_information")
    @classmethod
    def _scrub_list(cls, v: List[str]) -> List[str]:
        return [_clean(item, REASON_MAX) or "" for item in v]

    @field_validator("confidence")
    @classmethod
    def _bounded(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))


class KnowledgeAssessment(_Base):
    """Output of Step 4. Evidence is referenced, never inlined: source ids and
    scores, not document text. Copying retrieved content in would duplicate the
    RAG payload and drag document contents into anything that persists state."""

    known_information: List[str] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)
    # Phase 1: things EVA is proceeding on WITHOUT evidence, held apart from
    # known_information (facts) so an assumption can never be counted as a fact —
    # the Assumption != Fact rule, enforced by being a different list.
    assumptions: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    retrieval_required: bool = False
    tools_required: List[str] = Field(default_factory=list)
    evidence_sufficient: bool = False
    confidence: float = 0.0

    @field_validator("known_information", "missing_information", "assumptions", "evidence_refs", "tools_required")
    @classmethod
    def _scrub_list(cls, v: List[str]) -> List[str]:
        return [_clean(item, REASON_MAX) or "" for item in v]

    @field_validator("confidence")
    @classmethod
    def _bounded(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))


class StrategySelection(_Base):
    """Output of Step 5. `reason` is capped at REASON_MAX because it is written
    to logs — it is a one-line justification, not a reasoning trace."""

    strategy: ReasoningStrategy = ReasoningStrategy.DIRECT
    reason: str = ""
    required_capabilities: List[str] = Field(default_factory=list)
    required_tools: List[str] = Field(default_factory=list)
    verification_required: bool = False
    deterministic: bool = True

    @field_validator("reason")
    @classmethod
    def _scrub(cls, v: str) -> str:
        return _clean(v, REASON_MAX) or ""

    @field_validator("required_capabilities", "required_tools")
    @classmethod
    def _scrub_list(cls, v):
        return [_clean(item, REASON_MAX) or "" for item in v]


# ── Phase 1: Decision Gate + domain-independent safety ───────────────────────
# Data only, like everything else here. The LOGIC lives in cognitive/safety.py
# (assess_safety) and cognitive/decision_gate.py (decide); these are the shapes
# they read and write. Telemetry() on each returns ENUMS AND COUNTS ONLY — never
# a prompt, an answer, facts, assumptions or a clarification question.

class HarmTarget(str, Enum):
    HUMAN = "HUMAN"
    SOCIETY = "SOCIETY"
    AI_SYSTEM = "AI_SYSTEM"
    ENVIRONMENT = "ENVIRONMENT"


class HarmSeverity(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    SEVERE = "SEVERE"


class SafetyVerdict(str, Enum):
    ALLOW = "ALLOW"        # answer normally
    CAUTION = "CAUTION"    # answerable, but the topic carries risk (observed; no block in P1)
    STOP = "STOP"          # serious/irreversible harmful assistance — refuse + redirect


class SafetyReason(str, Enum):
    NONE = "NONE"
    WEAPON_OR_EXPLOSIVE = "WEAPON_OR_EXPLOSIVE"
    UNAUTHORIZED_INTRUSION = "UNAUTHORIZED_INTRUSION"
    MALWARE_CREATION = "MALWARE_CREATION"
    BIO_CHEM_RADIOLOGICAL = "BIO_CHEM_RADIOLOGICAL"
    VIOLENCE_OR_HARM_TO_PERSON = "VIOLENCE_OR_HARM_TO_PERSON"
    SELF_HARM = "SELF_HARM"
    SOCIETAL_MASS_HARM = "SOCIETAL_MASS_HARM"
    ENVIRONMENTAL_DESTRUCTION = "ENVIRONMENTAL_DESTRUCTION"
    OTHER_SERIOUS_HARM = "OTHER_SERIOUS_HARM"


class GateAction(str, Enum):
    PROCEED = "PROCEED"
    CLARIFY = "CLARIFY"
    SAFETY_STOP = "SAFETY_STOP"


class SolutionPaths(str, Enum):
    # COARSE Phase-1 signal only. Fixed/Two/Multi/Open path intelligence is a
    # later phase — this just says how settled the approach looks.
    OBVIOUS = "OBVIOUS"
    UNCERTAIN = "UNCERTAIN"
    MULTIPLE = "MULTIPLE"


class SafetyAssessment(_Base):
    verdict: SafetyVerdict = SafetyVerdict.ALLOW
    severity: HarmSeverity = HarmSeverity.NONE
    targets: List[HarmTarget] = Field(default_factory=list)
    irreversible: bool = False
    reason: SafetyReason = SafetyReason.NONE

    def telemetry(self) -> Dict[str, object]:
        return {
            "verdict": self.verdict.value,
            "severity": self.severity.value,
            "targets": [t.value for t in self.targets],
            "irreversible": self.irreversible,
            "reason": self.reason.value,
        }


class GateDecision(_Base):
    """What the Phase-1 gate concluded, BEFORE any answer is produced."""

    action: GateAction = GateAction.PROCEED
    safety: SafetyAssessment = Field(default_factory=SafetyAssessment)
    solution_paths: SolutionPaths = SolutionPaths.OBVIOUS
    strategy: ReasoningStrategy = ReasoningStrategy.DIRECT
    confidence: float = 0.0
    needs_clarification: bool = False
    # User-facing text — used to build a reply. NEVER placed in telemetry().
    clarification_question: str = ""
    facts: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    unknowns: List[str] = Field(default_factory=list)


    # Internal preparation objects are runtime-only and never serialized/telemetried.
    _understanding: Any = PrivateAttr(default=None)
    _assessment: Any = PrivateAttr(default=None)
    _strategy_decision: Any = PrivateAttr(default=None)
    @field_validator("clarification_question")
    @classmethod
    def _scrub_q(cls, v: str) -> str:
        return _clean(v, TEXT_MAX) or ""

    @field_validator("facts", "assumptions", "unknowns")
    @classmethod
    def _scrub_lists(cls, v: List[str]) -> List[str]:
        return [_clean(item, REASON_MAX) or "" for item in v]

    @field_validator("confidence")
    @classmethod
    def _bounded(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    def telemetry(self) -> Dict[str, object]:
        """The record for shadow mode: enums, codes and counts ONLY. No prompt,
        no answer, no facts/assumptions text, no clarification question."""
        out: Dict[str, object] = {
            "action": self.action.value,
            "solution_paths": self.solution_paths.value,
            "confidence": round(self.confidence, 3),
            "n_facts": len(self.facts),
            "n_assumptions": len(self.assumptions),
            "n_unknowns": len(self.unknowns),
        }
        out.update({f"safety_{k}": v for k, v in self.safety.telemetry().items()})
        return out


class PlannedTask(_Base):
    task_id: str = Field(default_factory=lambda: f"task_{uuid.uuid4().hex[:10]}")
    objective: str = ""
    required_capability: str = ""
    required_tool: Optional[str] = None
    input_requirements: List[str] = Field(default_factory=list)
    expected_output: str = ""
    verification_criteria: List[str] = Field(default_factory=list)
    depends_on: List[str] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = 0

    @field_validator("objective", "expected_output", "required_capability")
    @classmethod
    def _scrub(cls, v: str) -> str:
        return _clean(v, REASON_MAX) or ""

    @field_validator("required_tool")
    @classmethod
    def _scrub_opt(cls, v):
        return _clean(v, REASON_MAX)

    # These are model-populated free text, not just identifiers: a planner can
    # write "verify that key sk-... is valid" straight into a criterion, so they
    # need the same scrubbing as prose.
    @field_validator("input_requirements", "verification_criteria")
    @classmethod
    def _scrub_list(cls, v):
        return [_clean(item, REASON_MAX) or "" for item in v]

    @model_validator(mode="after")
    def _no_self_dependency(self):
        if self.task_id in self.depends_on:
            raise ValueError(f"task {self.task_id} cannot depend on itself")
        return self


class ActionRecord(_Base):
    """One executed capability/tool call. Records that it happened and whether
    it worked — not the full payload, which can be large and can contain
    document or user content."""

    action_id: str = Field(default_factory=lambda: f"act_{uuid.uuid4().hex[:10]}")
    task_id: Optional[str] = None
    tool: str = ""
    authorized: bool = False
    started_at: str = Field(default_factory=_utcnow)
    duration_ms: Optional[int] = None
    ok: bool = False
    result_summary: str = ""
    error: Optional[str] = None

    @field_validator("tool", "result_summary")
    @classmethod
    def _scrub(cls, v: str) -> str:
        return _clean(v, REASON_MAX) or ""

    @field_validator("error")
    @classmethod
    def _scrub_opt(cls, v: Optional[str]) -> Optional[str]:
        return _clean(v, REASON_MAX)


class Observation(_Base):
    observation_id: str = Field(default_factory=lambda: f"obs_{uuid.uuid4().hex[:10]}")
    task_id: Optional[str] = None
    summary: str = ""
    evidence: str = ""
    evidence_refs: List[str] = Field(default_factory=list)
    recorded_at: str = Field(default_factory=_utcnow)

    @field_validator("summary")
    @classmethod
    def _scrub(cls, v: str) -> str:
        return _clean(v, REASON_MAX) or ""

    @field_validator("evidence")
    @classmethod
    def _scrub_evidence(cls, v: str) -> str:
        return _clean(v, EVIDENCE_MAX) or ""

    @field_validator("evidence_refs")
    @classmethod
    def _scrub_list(cls, v):
        return [_clean(item, REASON_MAX) or "" for item in v]


class VerificationResult(_Base):
    task_id: Optional[str] = None
    status: VerificationStatus = VerificationStatus.NOT_REQUIRED
    verification_type: str = ""
    criteria: List[str] = Field(default_factory=list)
    failure_reason: Optional[str] = None
    confidence: float = 0.0

    @field_validator("verification_type")
    @classmethod
    def _scrub(cls, v: str) -> str:
        return _clean(v, REASON_MAX) or ""

    @field_validator("criteria")
    @classmethod
    def _scrub_list(cls, v):
        return [_clean(item, REASON_MAX) or "" for item in v]

    @field_validator("failure_reason")
    @classmethod
    def _scrub_opt(cls, v: Optional[str]) -> Optional[str]:
        return _clean(v, REASON_MAX)

    @field_validator("confidence")
    @classmethod
    def _bounded(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))


class CognitiveError(_Base):
    category: FailureCategory
    message: str = ""
    task_id: Optional[str] = None
    occurred_at: str = Field(default_factory=_utcnow)

    @field_validator("message")
    @classmethod
    def _scrub(cls, v: str) -> str:
        return _clean(v, REASON_MAX) or ""


class LearningCandidate(_Base):
    """Proposed, never auto-committed. `approved` exists so the field cannot
    default to true anywhere — learning_loop already requires a human
    transition before anything reaches a dataset, and this preserves that."""

    candidate_id: str = Field(default_factory=lambda: f"cand_{uuid.uuid4().hex[:10]}")
    category: str = ""
    summary: str = ""
    confidence: float = 0.0
    approved: bool = False

    @field_validator("category", "summary")
    @classmethod
    def _scrub(cls, v: str) -> str:
        return _clean(v, REASON_MAX) or ""

    @field_validator("confidence")
    @classmethod
    def _bounded(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))


# ── Root state ───────────────────────────────────────────────────────────────
class CognitiveState(_Base):
    """One problem-solving session.

    Serializable via model_dump()/model_validate() so it can be logged, shadow-
    compared against the existing path, or persisted, without a custom codec.
    """

    session_id: str = Field(default_factory=lambda: f"cog_{uuid.uuid4().hex[:12]}")
    created_at: str = Field(default_factory=_utcnow)
    updated_at: str = Field(default_factory=_utcnow)

    problem: str = ""
    context: List[str] = Field(default_factory=list)

    phase: CognitivePhase = CognitivePhase.UNDERSTAND
    understanding: Optional[ProblemUnderstanding] = None
    assessment: Optional[KnowledgeAssessment] = None
    strategy: Optional[StrategySelection] = None

    plan: List[PlannedTask] = Field(default_factory=list)
    current_task_id: Optional[str] = None

    actions: List[ActionRecord] = Field(default_factory=list)
    observations: List[Observation] = Field(default_factory=list)
    verifications: List[VerificationResult] = Field(default_factory=list)
    errors: List[CognitiveError] = Field(default_factory=list)
    learning_candidates: List[LearningCandidate] = Field(default_factory=list)

    retry_count: int = 0
    max_retries: int = DEFAULT_MAX_RETRIES
    max_tasks: int = DEFAULT_MAX_TASKS
    # Counts every phase move. Independent of retry_count: adaptive loops that
    # are not retries (act -> reassess -> re-strategise) still consume it.
    transition_count: int = 0
    max_transitions: int = DEFAULT_MAX_TRANSITIONS

    confidence: float = 0.0
    final_result: Optional[str] = None
    limitations: List[str] = Field(default_factory=list)

    @field_validator("problem", "final_result")
    @classmethod
    def _scrub_opt(cls, v):
        return _clean(v, TEXT_MAX)

    @field_validator("context", "limitations")
    @classmethod
    def _scrub_list(cls, v: List[str]) -> List[str]:
        return [_clean(item, TEXT_MAX) or "" for item in v]

    @field_validator("confidence")
    @classmethod
    def _bounded(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    @field_validator("max_retries")
    @classmethod
    def _retry_ceiling(cls, v: int) -> int:
        if v < 0:
            raise ValueError("max_retries cannot be negative")
        if v > MAX_RETRIES_CEILING:
            raise ValueError(f"max_retries exceeds ceiling {MAX_RETRIES_CEILING}")
        return v

    @field_validator("max_tasks")
    @classmethod
    def _task_ceiling(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_tasks must be at least 1")
        if v > MAX_TASKS_CEILING:
            raise ValueError(f"max_tasks exceeds ceiling {MAX_TASKS_CEILING}")
        return v

    @field_validator("max_transitions")
    @classmethod
    def _transition_ceiling(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_transitions must be at least 1")
        if v > MAX_TRANSITIONS_CEILING:
            raise ValueError(f"max_transitions exceeds ceiling {MAX_TRANSITIONS_CEILING}")
        return v

    # High-water marks backing the termination guarantee.
    #
    # max_transitions and transition_count are ordinary validated fields, which
    # means validate_assignment only checks their TYPE and ceiling — it does not
    # stop a caller writing `state.transition_count = 0` or raising
    # `state.max_transitions` mid-session. Either move re-opens the unbounded
    # loop the budget exists to prevent, so the budget has to be ratcheted, not
    # merely range-checked. These private attrs are excluded from serialization
    # and are re-derived on load, so a restored state cannot smuggle a loosened
    # budget back in either.
    _budget_ceiling: int = PrivateAttr(default=DEFAULT_MAX_TRANSITIONS)
    _count_floor: int = PrivateAttr(default=0)
    _ratchet_ready: bool = PrivateAttr(default=False)

    def model_post_init(self, __context) -> None:
        # Whatever the state was constructed (or deserialised) with becomes the
        # ceiling and floor from this point on.
        self._budget_ceiling = self.max_transitions
        self._count_floor = self.transition_count
        self._ratchet_ready = True

    @model_validator(mode="after")
    def _ratchet(self):
        if getattr(self, "_ratchet_ready", False):
            if self.max_transitions > self._budget_ceiling:
                raise ValueError(
                    f"max_transitions cannot be raised after creation "
                    f"({self._budget_ceiling} -> {self.max_transitions})"
                )
            if self.transition_count < self._count_floor:
                raise ValueError(
                    f"transition_count cannot decrease "
                    f"({self._count_floor} -> {self.transition_count})"
                )
            self._count_floor = self.transition_count
        return self

    @model_validator(mode="after")
    def _consistent(self):
        if len(self.plan) > self.max_tasks:
            raise ValueError(f"plan has {len(self.plan)} tasks, max_tasks is {self.max_tasks}")
        ids = [t.task_id for t in self.plan]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate task_id in plan")
        if self.current_task_id and self.current_task_id not in ids:
            raise ValueError(f"current_task_id {self.current_task_id} is not in the plan")
        # Dependencies must resolve, or the executor would wait on a task that
        # never runs.
        known = set(ids)
        for task in self.plan:
            for dep in task.depends_on:
                if dep not in known:
                    raise ValueError(f"task {task.task_id} depends on unknown task {dep}")
        return self

    # ── transitions ──────────────────────────────────────────────────────────
    def transitions_remaining(self) -> int:
        return max(0, self.max_transitions - self.transition_count)

    def can_transition_to(self, target: CognitivePhase) -> bool:
        if self.is_terminal():
            return False
        # Terminating must always be possible, including after the move budget
        # is spent — otherwise an exhausted session has no legal way to stop.
        if target in _UNIVERSAL_TARGETS:
            return True
        if self.transitions_remaining() <= 0:
            return False
        return target in _ALLOWED_TRANSITIONS.get(self.phase, set())

    def transition_to(self, target: CognitivePhase) -> "CognitiveState":
        if not self.can_transition_to(target):
            if self.transitions_remaining() <= 0 and target not in _UNIVERSAL_TARGETS:
                raise ValueError(
                    f"transition budget exhausted ({self.max_transitions}); "
                    f"only RESPOND or ABORTED remain reachable"
                )
            raise ValueError(f"illegal transition {self.phase.value} -> {target.value}")
        self.phase = target
        self.transition_count += 1
        self.updated_at = _utcnow()
        return self

    # ── retry budget ─────────────────────────────────────────────────────────
    def retries_remaining(self) -> int:
        return max(0, self.max_retries - self.retry_count)

    def register_retry(self) -> bool:
        """Consume one retry. Returns False when the budget is spent — the
        caller is expected to stop, not to keep asking. Returning a bool rather
        than raising keeps the exhausted case an ordinary branch, because
        running out of retries is a normal outcome, not an error."""
        if self.retries_remaining() <= 0:
            return False
        self.retry_count += 1
        self.updated_at = _utcnow()
        return True

    # ── convenience ──────────────────────────────────────────────────────────
    def record_error(self, category: FailureCategory, message: str = "", task_id: Optional[str] = None) -> CognitiveError:
        err = CognitiveError(category=category, message=message, task_id=task_id)
        self.errors.append(err)
        self.updated_at = _utcnow()
        return err

    def verification_status(self) -> VerificationStatus:
        """Worst-case verdict across all verifications. FAILED dominates, then
        INCONCLUSIVE — an overall 'verified' must not be reportable while any
        check failed."""
        if not self.verifications:
            return VerificationStatus.NOT_REQUIRED
        statuses = {v.status for v in self.verifications}
        if VerificationStatus.FAILED in statuses:
            return VerificationStatus.FAILED
        if VerificationStatus.INCONCLUSIVE in statuses:
            return VerificationStatus.INCONCLUSIVE
        if VerificationStatus.VERIFIED in statuses:
            return VerificationStatus.VERIFIED
        return VerificationStatus.NOT_REQUIRED

    def is_terminal(self) -> bool:
        return self.phase in {CognitivePhase.RESPOND, CognitivePhase.ABORTED}

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "CognitiveState":
        return cls.model_validate(payload)

