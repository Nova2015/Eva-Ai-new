"""Capability selection â€” Step 7 of the Cognitive Engine.

Answers: **what capabilities are needed to execute this plan?**

Four decisions that are easy to collapse into one, kept apart:

    STRATEGY    how should we reason about this?      (Step 5)
    CAPABILITY  what ability is needed?               (here)
    PROVIDER    which model answers?                  (model_router â€” NOT here)
    TOOL        what concrete mechanism runs?         (Step 8 â€” NOT here)

So this module names CALCULATION, never "python"; RETRIEVAL, never "groq". It
selects nothing, calls nothing, and executes nothing.

EVERY CAPABILITY IS BACKED BY SOMETHING REAL
============================================
Â§4 of the brief lists candidate capabilities but says to create only those the
architecture actually supports. Each member of `Capability` below names the
system that implements it, and CAPABILITY_BACKING records that mapping. A
capability with nothing behind it is a promise the executor cannot keep â€” it
would pass validation here and fail at Step 8, which is the worst place to
discover it.

MEMORY_WRITE exists in the enum but is never selected deterministically. It is
defined so that a proposal to write can be *named and rejected* under a
read-only constraint; without the identifier there would be no way to express
the refusal.

DETERMINISTIC FIRST, with an injected assist for genuinely complex plans. The
assist is a callable, never an import: no provider SDK, no HTTP, no network.
Its output is untrusted and fully validated before use.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Callable, Dict, List, Optional, Sequence, Set

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .assessment import AssessmentReport, RiskLevel
from .planning import TaskPlan
from .state import PlannedTask, ProblemUnderstanding, ReasoningStrategy, REASON_MAX, redact_secrets
from .strategy import StrategyDecision


class Capability(str, Enum):
    """Only capabilities EVA can actually deliver. See CAPABILITY_BACKING."""

    GENERAL_REASONING = "GENERAL_REASONING"
    RETRIEVAL = "RETRIEVAL"
    DOCUMENT_ANALYSIS = "DOCUMENT_ANALYSIS"
    CODE_GENERATION = "CODE_GENERATION"
    CODE_ANALYSIS = "CODE_ANALYSIS"
    CALCULATION = "CALCULATION"
    TEXT_ANALYSIS = "TEXT_ANALYSIS"
    CLASSIFICATION = "CLASSIFICATION"
    IMAGE_ANALYSIS = "IMAGE_ANALYSIS"
    MECHANICAL_ANALYSIS = "MECHANICAL_ANALYSIS"
    RESEARCH = "RESEARCH"
    VERIFICATION = "VERIFICATION"
    STRUCTURED_ANALYSIS = "STRUCTURED_ANALYSIS"
    DIALOGUE = "DIALOGUE"
    PLANNING = "PLANNING"
    MEMORY_READ = "MEMORY_READ"
    MEMORY_WRITE = "MEMORY_WRITE"          # nameable so it can be refused


# What implements each capability today. Used by validation, and the reason the
# enum stops where it does â€” there is no DATA_ANALYSIS member because nothing
# in this repository backs one.
CAPABILITY_BACKING: Dict[Capability, str] = {
    Capability.GENERAL_REASONING: "agents/chat_agent",
    Capability.RETRIEVAL: "autopilot rag_query tool / ML service /rag/query",
    Capability.DOCUMENT_ANALYSIS: "agents/rag_agent / ML service /rag/upload",
    Capability.CODE_GENERATION: "agents/code_agent",
    Capability.CODE_ANALYSIS: "review_engine.validate_code",
    Capability.CALCULATION: "general model arithmetic",
    Capability.TEXT_ANALYSIS: "ML service /ml/sentiment, /ml/toxic",
    Capability.CLASSIFICATION: "ML service /ml/classify",
    Capability.IMAGE_ANALYSIS: "agents/vision_agent",
    Capability.MECHANICAL_ANALYSIS: "modes/registry: mechanical",
    Capability.RESEARCH: "external research tools",
    Capability.VERIFICATION: "review_engine",
    Capability.STRUCTURED_ANALYSIS: "agents/chat_agent",
    Capability.DIALOGUE: "chat response path",
    Capability.PLANNING: "autopilot._make_plan",
    Capability.MEMORY_READ: "memory_manager (read)",
    Capability.MEMORY_WRITE: "memory_manager (write) â€” never auto-selected",
}

# Capabilities that change state. Everything else is read-only.
_WRITE_CAPABILITIES = {Capability.MEMORY_WRITE}


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class CapabilityRequirement(_Base):
    capability_id: Capability
    purpose: str = ""
    required: bool = True
    confidence: float = 0.0
    task_ids: List[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.SAFE
    read_only: bool = True
    verification_required: bool = False

    @field_validator("purpose")
    @classmethod
    def _scrub(cls, v: str) -> str:
        return redact_secrets(str(v or ""))[:REASON_MAX]

    @field_validator("confidence")
    @classmethod
    def _bounded(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))


class CapabilitySelection(_Base):
    capabilities: List[CapabilityRequirement] = Field(default_factory=list)
    selection_confidence: float = 0.0
    selection_reason: str = ""
    # Named requirements the engine cannot satisfy â€” an unsupported capability,
    # or a write blocked by a read-only constraint. Surfaced rather than
    # dropped: silently omitting a needed capability produces a plan that fails
    # at execution with no explanation.
    unresolved_capabilities: List[str] = Field(default_factory=list)
    requires_dynamic_resolution: bool = False

    @field_validator("selection_reason")
    @classmethod
    def _scrub(cls, v: str) -> str:
        return redact_secrets(str(v or ""))[:REASON_MAX]

    @field_validator("unresolved_capabilities")
    @classmethod
    def _scrub_list(cls, v: List[str]) -> List[str]:
        return [redact_secrets(str(i or ""))[:REASON_MAX] for i in v]

    @field_validator("selection_confidence")
    @classmethod
    def _bounded(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    def capability_ids(self) -> List[Capability]:
        return [c.capability_id for c in self.capabilities]

    def for_task(self, task_id: str) -> List[Capability]:
        return [c.capability_id for c in self.capabilities if task_id in c.task_ids]


# â”€â”€ deterministic signals â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Step 5/6 already emit capability strings; map them rather than re-deriving.
_STRING_TO_CAPABILITY: Dict[str, Capability] = {
    "general_reasoning": Capability.GENERAL_REASONING,
    "arithmetic": Capability.CALCULATION,
    "code_generation": Capability.CODE_GENERATION,
    "retrieval": Capability.RETRIEVAL,
    "structured_analysis": Capability.STRUCTURED_ANALYSIS,
    "planning": Capability.PLANNING,
    "dialogue": Capability.DIALOGUE,
    # tool_use is not a capability â€” it is how a capability is delivered. The
    # actual capability comes from which tool the task names.
}

# autopilot's whitelist -> what using that tool actually requires.
_TOOL_TO_CAPABILITY: Dict[str, Capability] = {
    "rag_query": Capability.RETRIEVAL,
    "web_search": Capability.RESEARCH,
    "read_url": Capability.RESEARCH,
    "think": Capability.GENERAL_REASONING,
}

# Step 3 problem categories -> capability.
_CATEGORY_TO_CAPABILITY: Dict[str, Capability] = {
    "mathematics": Capability.CALCULATION,
    "coding": Capability.CODE_GENERATION,
    "document": Capability.DOCUMENT_ANALYSIS,
    "comparison": Capability.STRUCTURED_ANALYSIS,
    "vision": Capability.IMAGE_ANALYSIS,
    "greeting": Capability.DIALOGUE,
    "identity": Capability.DIALOGUE,
}

# Objective wording that implies a capability the tool/category signals miss.
_OBJECTIVE_SIGNALS = (
    (re.compile(r"\b(debug|traceback|exception|stack ?trace|error output|lint)\b", re.I),
     Capability.CODE_ANALYSIS),
    (re.compile(r"\b(sentiment|tone|toxic|readability)\b", re.I), Capability.TEXT_ANALYSIS),
    (re.compile(r"\b(classify|categori[sz]e|label)\b", re.I), Capability.CLASSIFICATION),
    (re.compile(r"\b(stress|load|torque|tolerance|cad|mechanical|structural)\b", re.I),
     Capability.MECHANICAL_ANALYSIS),
    (re.compile(r"\b(recall|remember|previously (said|told)|earlier you)\b", re.I),
     Capability.MEMORY_READ),
)

# A user constraint that forbids changing anything.
_READ_ONLY_RE = re.compile(r"\bread[- ]?only|do not (write|modify|change)|without (writing|modifying)\b", re.I)


def _capabilities_for_task(task: PlannedTask) -> Set[Capability]:
    found: Set[Capability] = set()

    declared = (task.required_capability or "").strip().lower()
    if declared in _STRING_TO_CAPABILITY:
        found.add(_STRING_TO_CAPABILITY[declared])

    if task.required_tool:
        mapped = _TOOL_TO_CAPABILITY.get(task.required_tool.strip().lower())
        if mapped:
            found.add(mapped)

    text = " ".join([task.objective or "", " ".join(task.input_requirements or [])])
    for pattern, capability in _OBJECTIVE_SIGNALS:
        if pattern.search(text):
            found.add(capability)

    if not found:
        found.add(Capability.GENERAL_REASONING)
    return found


def _verification_tasks(plan: TaskPlan) -> Set[str]:
    """Tasks whose completion condition is a real check rather than a
    restatement of the objective. Step 6 already recorded these."""
    trivial = {"answer addresses the stated outcome"}
    return {
        t.task_id for t in plan.tasks
        if [c for c in (t.verification_criteria or []) if c not in trivial]
    }


def select_capabilities(
    plan: TaskPlan,
    understanding: ProblemUnderstanding,
    assessment: AssessmentReport,
    decision: StrategyDecision,
    problem: str = "",
    assist: Optional[Callable[[str], object]] = None,
) -> CapabilitySelection:
    """Determine required capabilities for a validated plan.

    Pure and repeatable: nothing is cached, so a replan after new evidence
    yields a fresh selection rather than an obsolete one.

    `assist` is an optional injected callable for plans the deterministic map
    cannot resolve. It is never imported and its output is treated as
    untrusted.
    """
    read_only_required = any(_READ_ONLY_RE.search(c or "") for c in (understanding.constraints or []))
    verification_task_ids = _verification_tasks(plan)

    by_capability: Dict[Capability, Set[str]] = {}
    for task in plan.tasks:
        for capability in _capabilities_for_task(task):
            by_capability.setdefault(capability, set()).add(task.task_id)

    # Category and strategy add capabilities the per-task view can miss â€” a
    # document question whose tasks all use `think`, for instance.
    category_capability = _CATEGORY_TO_CAPABILITY.get((understanding.problem_category or "").lower())
    if category_capability and plan.tasks:
        by_capability.setdefault(category_capability, set()).add(plan.tasks[0].task_id)

    # The user's own words carry signals the derived fields do not. "Debug this
    # Python traceback" needs CODE_ANALYSIS, but by the time it becomes a task
    # objective it reads "working code or a diagnosis" â€” the words `debug` and
    # `traceback` are gone. Scanning only objectives silently dropped the
    # capability; this is the same blind spot Step 4 had with risk.
    if problem and plan.tasks:
        for pattern, capability in _OBJECTIVE_SIGNALS:
            if pattern.search(problem):
                by_capability.setdefault(capability, set()).add(plan.tasks[0].task_id)
    if decision.strategy is ReasoningStrategy.MULTI_STEP and plan.tasks:
        by_capability.setdefault(Capability.PLANNING, set()).add(plan.tasks[0].task_id)

    # Â§15: verification is a capability, but performing it belongs to
    # review_engine. Naming it here is the whole contribution.
    if verification_task_ids:
        by_capability.setdefault(Capability.VERIFICATION, set()).update(verification_task_ids)

    unresolved: List[str] = []
    requirements: List[CapabilityRequirement] = []

    for capability, task_ids in sorted(by_capability.items(), key=lambda kv: kv[0].value):
        is_write = capability in _WRITE_CAPABILITIES

        # Â§14: a write under an explicit read-only constraint is refused, not
        # silently downgraded or silently granted.
        if is_write and read_only_required:
            unresolved.append(
                f"{capability.value} conflicts with the user's read-only constraint"
            )
            continue

        # Â§13: a capability that changes state under CRITICAL risk is left
        # unresolved for a human/authorised path rather than requested here.
        if is_write and assessment.risk_level is RiskLevel.CRITICAL:
            unresolved.append(f"{capability.value} withheld: request assessed CRITICAL risk")
            continue

        requirements.append(CapabilityRequirement(
            capability_id=capability,
            purpose=CAPABILITY_BACKING.get(capability, ""),
            required=True,
            confidence=round(min(1.0, 0.55 + 0.15 * len(task_ids)), 3),
            task_ids=sorted(task_ids),
            risk_level=assessment.risk_level,
            read_only=not is_write,
            verification_required=bool(task_ids & verification_task_ids),
        ))

    selection = CapabilitySelection(
        capabilities=requirements,
        selection_confidence=round(
            min(1.0, 0.4 + 0.1 * len(requirements)) * (0.5 if unresolved else 1.0), 3
        ),
        selection_reason=(
            f"{len(requirements)} capability requirement(s) mapped from {len(plan.tasks)} task(s)"
            + (f"; {len(unresolved)} unresolved" if unresolved else "")
        ),
        unresolved_capabilities=unresolved,
        requires_dynamic_resolution=bool(unresolved),
    )

    if assist is None or not selection.requires_dynamic_resolution:
        return selection
    return _apply_assist(selection, plan, assist)


def _apply_assist(
    selection: CapabilitySelection,
    plan: TaskPlan,
    assist: Callable[[str], object],
) -> CapabilitySelection:
    """Merge an injected suggestion after full validation.

    Untrusted by construction: unknown capability ids, unknown task ids,
    duplicates and write capabilities are all rejected. Any failure leaves the
    deterministic selection exactly as it was â€” an assist that misbehaves must
    never widen what the engine is allowed to do.
    """
    try:
        raw = assist("\n".join(t.objective for t in plan.tasks)[:1500])
    except Exception:
        return selection
    if not isinstance(raw, (list, tuple)):
        return selection

    known_tasks = {t.task_id for t in plan.tasks}
    already = set(selection.capability_ids())
    added: List[CapabilityRequirement] = []

    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("capability_id") or entry.get("capability") or "").strip().upper()
        if name not in Capability.__members__:
            continue                                   # unknown capability
        capability = Capability[name]
        if capability in already or capability in {a.capability_id for a in added}:
            continue                                   # duplicate
        if capability in _WRITE_CAPABILITIES:
            continue                                   # never granted by assist
        task_ids = [t for t in (entry.get("task_ids") or []) if t in known_tasks]
        if not task_ids:
            continue                                   # unknown / missing task
        added.append(CapabilityRequirement(
            capability_id=capability,
            purpose=CAPABILITY_BACKING.get(capability, ""),
            required=False,                            # suggested, not established
            confidence=0.5,
            task_ids=sorted(task_ids),
            risk_level=selection.capabilities[0].risk_level if selection.capabilities else RiskLevel.SAFE,
            read_only=True,
            verification_required=False,
        ))

    if not added:
        return selection
    return CapabilitySelection(
        capabilities=selection.capabilities + added,
        selection_confidence=selection.selection_confidence,
        selection_reason=selection.selection_reason + f"; {len(added)} added by assist",
        unresolved_capabilities=selection.unresolved_capabilities,
        requires_dynamic_resolution=selection.requires_dynamic_resolution,
    )

