"""Strategy Selector â€” Step 5 of the Cognitive Engine.

Answers: **how should EVA approach this problem?**

It does not solve it, does not plan the tasks, and does not execute anything.
The boundary against the neighbouring stages:

    Step 3  what is the problem, and what is unclear?
    Step 4  are we ready to choose an approach?
    Step 5  which approach â€” and what would prove it worked?
    Step 6  what are the concrete tasks?  (not here)

FULLY DETERMINISTIC â€” AND NO llm HOOK
=====================================
Steps 3 and 4 both take an optional injected `llm`. This one deliberately does
not. Strategy selection is a rule problem: given a category, a complexity
signal and a readiness verdict, the right approach follows. A model call here
would add latency and provider spend to every message and make the choice
non-reproducible, in exchange for a decision the rules already make correctly.

If a future case genuinely needs judgement, the honest fix is a new rule with a
test â€” not an escape hatch that quietly turns a deterministic selector into a
model call. That is why there is no parameter to pass one.

REUSES EXISTING VOCABULARY
==========================
  ReasoningStrategy   Step 2's enum, unchanged â€” all eight members already existed.
  required_tools      autopilot's actual whitelist (web_search, read_url,
                      rag_query, think). Naming a tool that does not exist would
                      hand Step 7 an unroutable capability.
  verification        review_engine's real validators (validate_code,
                      validate_charts, validate_mermaid) plus runtime_engine
                      execution, so Step 9 has something concrete to call.

WHY A SEPARATE DECISION TYPE
============================
Step 2's StrategySelection carries strategy, reason, required_capabilities,
required_tools, verification_required (a bool) and deterministic. Step 5 must
also return required_context and a *list* of verification requirements. Rather
than widen the Step 2 model â€” off-limits â€” StrategyDecision is the full output
and to_strategy_selection() projects it down, exactly as Step 4 does with
AssessmentReport. Step 2 stays untouched.

NO CHAIN OF THOUGHT. `reason` is one short logged sentence stating the rule
that fired, capped in length. There is no field for a reasoning trace.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .assessment import AssessmentReport, EvidenceSufficiency, RiskLevel
from .state import ProblemUnderstanding, ReasoningStrategy, StrategySelection, REASON_MAX, redact_secrets


class VerificationRequirement(str, Enum):
    """What would demonstrate the answer is right. Each maps to something that
    already exists, so Step 9 has a real check to run rather than a label."""

    CODE_VALIDATION = "CODE_VALIDATION"          # review_engine.validate_code
    CHART_VALIDATION = "CHART_VALIDATION"        # review_engine.validate_charts
    DIAGRAM_VALIDATION = "DIAGRAM_VALIDATION"    # review_engine.validate_mermaid
    EXECUTION_TEST = "EXECUTION_TEST"            # runtime_engine.execute_code
    ARITHMETIC_RECHECK = "ARITHMETIC_RECHECK"    # recompute independently
    CITATION_CHECK = "CITATION_CHECK"            # grounded_sources on the ML service
    CONSISTENCY_CHECK = "CONSISTENCY_CHECK"      # answer vs. stated constraints
    NONE = "NONE"


class RequiredContext(str, Enum):
    """What the strategy needs in front of it before it can run."""

    NONE = "NONE"
    CONVERSATION_HISTORY = "CONVERSATION_HISTORY"
    USER_DOCUMENTS = "USER_DOCUMENTS"
    PRIOR_OBSERVATIONS = "PRIOR_OBSERVATIONS"
    USER_CLARIFICATION = "USER_CLARIFICATION"
    EXTERNAL_SOURCES = "EXTERNAL_SOURCES"


# autopilot's whitelist verbatim. Every tool named here is one that exists.
TOOL_WEB_SEARCH = "web_search"
TOOL_READ_URL = "read_url"
TOOL_RAG_QUERY = "rag_query"
TOOL_THINK = "think"


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class StrategyDecision(_Base):
    strategy: ReasoningStrategy = ReasoningStrategy.DIRECT
    reason: str = ""
    required_capabilities: List[str] = Field(default_factory=list)
    required_tools: List[str] = Field(default_factory=list)
    required_context: List[RequiredContext] = Field(default_factory=list)
    # What will actually be executed. When a capability set is supplied this
    # holds only runnable checks, so an unrunnable one cannot sit in the
    # pipeline producing INCONCLUSIVE for work that was never attempted.
    verification_requirements: List[VerificationRequirement] = Field(default_factory=list)
    # What would have proven this answer right but cannot be run here. Recorded
    # rather than dropped: this is the only trace of where EVA's verification
    # coverage stops, and Step 12 learns its VERIFICATION_GAP lessons from it.
    # A requirement listed here was NEVER executed â€” VERIFIED alongside a
    # non-empty list means "verified to the extent this runtime can verify".
    unavailable_requirements: List[VerificationRequirement] = Field(default_factory=list)
    deterministic: bool = True
    # Where to go if the chosen approach cannot proceed. Step 10 (correction)
    # needs somewhere to fall back to that is not "try the same thing again".
    fallback_strategy: Optional[ReasoningStrategy] = None

    @field_validator("reason")
    @classmethod
    def _scrub(cls, v: str) -> str:
        return redact_secrets(str(v or ""))[:REASON_MAX]

    @field_validator("required_capabilities", "required_tools")
    @classmethod
    def _scrub_list(cls, v: List[str]) -> List[str]:
        return [redact_secrets(str(i or ""))[:REASON_MAX] for i in v]

    def to_strategy_selection(self) -> StrategySelection:
        """Project into the Step 2 model without widening it."""
        return StrategySelection(
            strategy=self.strategy,
            reason=self.reason,
            required_capabilities=list(self.required_capabilities),
            required_tools=list(self.required_tools),
            verification_required=bool(
                [v for v in self.verification_requirements if v is not VerificationRequirement.NONE]
            ),
            deterministic=self.deterministic,
        )


# â”€â”€ complexity â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Multi-part requests need a plan rather than a single answer. Counted from
# structure, not guessed: conjunctions joining clauses, enumerated parts, and
# how many distinct information needs are still open.
# Two kinds of connective, and they are not equally good evidence.
#
# SEQUENCING marks ordered work: "set up X and then migrate Y" is two tasks
# whoever reads it. One of these already means two parts.
#
# ADDITIVE is frequently conversational filler - "can you also explain how
# oauth works?" is one question, not two. On its own it is weak evidence and
# needs a second signal before it moves anything.
#
# Both used to sit in one pattern whose matches were counted as though each
# match were a part. It counted JOINS while the threshold read as PARTS, and n
# joins separate n+1 clauses - so a plainly two-part request scored 1, stayed
# below the threshold, and was answered as a single task.
_SEQUENCE_RE = re.compile(
    r"\b(and then|after that|followed by|first.*then|step \d)\b", re.I,
)
_ADDITIVE_RE = re.compile(r"\b(also|additionally|as well as)\b", re.I)
_ENUMERATION_RE = re.compile(r"(\b\d\s*[).]\s+|\n\s*[-*]\s+)")


def _complexity(understanding: ProblemUnderstanding, assessment: AssessmentReport, problem: str) -> int:
    """0-3. Higher means the request has more independent parts to satisfy."""
    score = 0
    text = " ".join([problem or "", understanding.desired_outcome])
    # Count the joins, do not just note that one exists. "set up X and then
    # migrate Y and also seed Z" has three parts and must outrank a two-part
    # request; a boolean scored them identically and left the three-part case
    # below the MULTI_STEP threshold, so it was answered as a single task.
    #
    # The +1 is the joins-to-parts conversion: one sequencing connective
    # separates two clauses, so it is already a two-part request and reaches
    # the threshold on its own.
    sequenced = len(_SEQUENCE_RE.findall(text))
    if sequenced:
        score += min(2, sequenced) + 1
    # Additive connectives contribute at most one point however many appear:
    # "also" repeated is a speech habit, not a count of tasks.
    if _ADDITIVE_RE.search(text):
        score += 1
    if _ENUMERATION_RE.search(problem or ""):
        score += 1
    if len(assessment.missing_information) >= 3:
        score += 1
    if len(understanding.constraints) >= 2:
        score += 1
    return min(3, score)


# Verbs that ask for code to be PRODUCED or REPAIRED, as opposed to a question
# whose subject happens to be code. "write a react component" wants code;
# "what is react?" and "the latest react version" do not.
_PRODUCE_CODE_RE = re.compile(
    r"\b(write|create|make|build|implement|generate|code|program|script|"
    r"regex|snippet|query|function for|command|"
    r"refactor|rewrite|port|convert|translate|add|extend|complete|"
    r"fix|debug|repair|solve|optimi[sz]e|improve|update|modify|change)\b",
    re.I,
)

_DOC_CATEGORIES = {"document"}
_MATH_CATEGORIES = {"mathematics"}
_CODE_CATEGORIES = {"coding"}
_COMPARE_CATEGORIES = {"comparison"}
_PROCEDURE_CATEGORIES = {"procedure"}
_TRIVIAL_CATEGORIES = {"greeting", "identity"}

# Needs that can only be met by going outside EVA's own knowledge.
_URL_NEED_RE = re.compile(r"https?://[^\s]+", re.I)

_EXTERNAL_NEED_RE = re.compile(
    r"\b(latest|current|today|recent|news|price|weather|release|version|"
    r"documentation|changelog|upstream)\b", re.I,
)


def _verification_for(strategy: ReasoningStrategy,
                      understanding: ProblemUnderstanding,
                      problem: str = "") -> List[VerificationRequirement]:
    """What would actually demonstrate this answer is right.

    Deliberately concrete: every value maps to an existing validator or runner,
    so Step 9 can execute the check instead of interpreting a label.
    """
    if strategy is ReasoningStrategy.CODE:
        return [VerificationRequirement.CODE_VALIDATION, VerificationRequirement.EXECUTION_TEST]
    if strategy is ReasoningStrategy.CALCULATION:
        return [VerificationRequirement.ARITHMETIC_RECHECK]
    if strategy is ReasoningStrategy.RETRIEVAL:
        return [VerificationRequirement.CITATION_CHECK]
    if strategy is ReasoningStrategy.ANALYSIS:
        return [VerificationRequirement.CONSISTENCY_CHECK]
    if strategy is ReasoningStrategy.MULTI_STEP:
        return [VerificationRequirement.CONSISTENCY_CHECK]
    if strategy is ReasoningStrategy.TOOL_ASSISTED:
        return [VerificationRequirement.CITATION_CHECK, VerificationRequirement.CONSISTENCY_CHECK]
    if strategy is ReasoningStrategy.CLARIFICATION:
        return [VerificationRequirement.NONE]
    # DIRECT: a diagram or chart answer still has a real validator available.
    #
    # Matched against the REQUEST as well as the derived outcome. Step 3's
    # deterministic path never writes "diagram" into desired_outcome â€” it emits
    # "a direct answer to the question" or "a generated image" â€” so keying on
    # that alone made both validators unreachable from /chat however plainly
    # the user asked. This is the same blindness Steps 4 and 7 each had to fix
    # by reading the raw words.
    text = f"{understanding.desired_outcome or ''} {problem or ''}".lower()
    if "diagram" in text or "flowchart" in text:
        return [VerificationRequirement.DIAGRAM_VALIDATION]
    if "chart" in text or "graph" in text:
        return [VerificationRequirement.CHART_VALIDATION]
    return [VerificationRequirement.NONE]


def _split(requested: List[VerificationRequirement],
           available) -> Tuple[List[VerificationRequirement],
                               List[VerificationRequirement]]:
    """Separate what can be run here from what cannot, preserving order.

    `available is None` means "assume everything" - the pre-Update-14
    behaviour, kept exactly so every existing caller and test is unaffected.
    NONE is never split off: it is the absence of a requirement, not one.
    """
    if available is None:
        return list(requested), []
    runnable, unavailable = [], []
    for requirement in requested:
        if requirement is VerificationRequirement.NONE or requirement in available:
            runnable.append(requirement)
        else:
            unavailable.append(requirement)
    return runnable, unavailable


def select_strategy(
    understanding: ProblemUnderstanding,
    assessment: AssessmentReport,
    problem: str = "",
    available=None,
) -> StrategyDecision:
    """Choose an approach. Deterministic, pure, and repeatable.

    Repeatable matters for the same reason it did in Step 4: the engine may
    re-enter STRATEGY after ACT gathers something (the Step 2 CORRECT->STRATEGY
    and PLAN->STRATEGY edges), and the second call must be free to choose
    differently. Nothing is cached and no previous decision is consulted.

    `available` is the set of verification requirements the caller can actually
    execute - see verification.available_requirements(). Supplying it splits
    what would prove the answer right from what can be run here: the runnable
    ones enter the pipeline, the rest are RECORDED in unavailable_requirements
    and never executed. Omitting it preserves the previous behaviour exactly.
    """
    category = (understanding.problem_category or "general").lower()
    complexity = _complexity(understanding, assessment, problem)

    def decide(strategy, reason, capabilities=(), tools=(), context=(), fallback=None):
        runnable, unavailable = _split(
            _verification_for(strategy, understanding, problem), available)
        return StrategyDecision(
            strategy=strategy,
            reason=reason,
            required_capabilities=list(capabilities),
            required_tools=list(tools),
            required_context=list(context) or [RequiredContext.NONE],
            verification_requirements=runnable,
            unavailable_requirements=unavailable,
            deterministic=True,
            fallback_strategy=fallback,
        )

    # 1. Cannot choose an approach for a question we do not understand. This
    #    outranks everything, including category: picking CODE for an
    #    unintelligible request would produce confident nonsense.
    if assessment.clarification_required:
        return decide(
            ReasoningStrategy.CLARIFICATION,
            "the request is ambiguous in a way the available evidence cannot resolve",
            capabilities=["dialogue"],
            context=[RequiredContext.USER_CLARIFICATION],
        )

    # 2. Safety. A CRITICAL assessment must not be answered with a strategy
    #    that runs code or reaches outside â€” not as enforcement (the firewall
    #    owns that and has already run), but because selecting an executing
    #    approach for a request flagged critical is the wrong recommendation to
    #    hand the next stage.
    if assessment.risk_level is RiskLevel.CRITICAL:
        return decide(
            ReasoningStrategy.DIRECT,
            "request assessed CRITICAL risk; answering directly without tools or execution",
            capabilities=["general_reasoning"],
            context=[RequiredContext.NONE],
        )

    # 3. Trivial conversational turns need nothing.
    if category in _TRIVIAL_CATEGORIES:
        return decide(
            ReasoningStrategy.DIRECT,
            f"{category} needs no retrieval, tools or planning",
            capabilities=["general_reasoning"],
        )

    # 4. External evidence takes deterministic tool routing before generic
    # multi-step planning, so compound research requests never fall into the
    # model-backed autopilot planner.
    url_requested = bool(_URL_NEED_RE.search(problem or ""))
    needs_external = any(_EXTERNAL_NEED_RE.search(m) for m in assessment.missing_information) \
        or bool(_EXTERNAL_NEED_RE.search(problem or ""))
    if url_requested:
        tools = [TOOL_READ_URL]
        if needs_external:
            tools.append(TOOL_WEB_SEARCH)
        return decide(
            ReasoningStrategy.TOOL_ASSISTED,
            "external evidence requested; use deterministic external tools before answering",
            capabilities=["tool_use", "retrieval"],
            tools=tools,
            context=[RequiredContext.EXTERNAL_SOURCES],
            fallback=ReasoningStrategy.DIRECT,
        )
    if needs_external:
        return decide(
            ReasoningStrategy.TOOL_ASSISTED,
            "external evidence requested; search the public web before answering",
            capabilities=["tool_use", "retrieval"],
            tools=[TOOL_WEB_SEARCH],
            context=[RequiredContext.EXTERNAL_SOURCES],
            fallback=ReasoningStrategy.DIRECT,
        )
    # 4. Multi-part work needs a plan before an answer, whatever its subject.
    #    Checked before the subject rules so a compound coding request becomes
    #    MULTI_STEP rather than a single CODE answer that addresses one part.
    if complexity >= 2:
        return decide(
            ReasoningStrategy.MULTI_STEP,
            f"request has {complexity} independent parts; sequencing required",
            capabilities=["planning", "general_reasoning"],
            tools=[TOOL_THINK],
            context=[RequiredContext.PRIOR_OBSERVATIONS],
            fallback=ReasoningStrategy.ANALYSIS,
        )

    # 5. Subject-driven selection.
    if category in _MATH_CATEGORIES:
        return decide(
            ReasoningStrategy.CALCULATION,
            "quantitative request; compute and re-check the result",
            capabilities=["arithmetic"],
            fallback=ReasoningStrategy.DIRECT,
        )

    # The category says the SUBJECT is programming. CODE says the user wants
    # code produced, and those are not the same request.
    #
    # "what is react?" and "search the web for the latest react version" were
    # both CODE, because Step 3 falls back to the production router when its own
    # regex does not fire, and that router answers "the code agent handles
    # this" â€” a routing decision, which understanding.py itself flags as "a
    # routing heuristic, not an understanding". Reading it as "the user wants
    # code" attributed every question ABOUT programming to a strategy for
    # WRITING it, and Step 12 then recorded the outcome under strategy=CODE.
    #
    # The test is whether the request asks for a code ARTEFACT â€” written,
    # repaired, or named as the thing wanted ("code", "script", "regex",
    # "query"). That covers diagnosis too, since "my code throws an exception"
    # names one. A question that merely mentions programming does not.
    if category in _CODE_CATEGORIES and _PRODUCE_CODE_RE.search(problem or ""):
        return decide(
            ReasoningStrategy.CODE,
            "programming request; produce code and validate it",
            capabilities=["code_generation"],
            context=[RequiredContext.CONVERSATION_HISTORY],
            fallback=ReasoningStrategy.DIRECT,
        )

    if category in _DOC_CATEGORIES:
        return decide(
            ReasoningStrategy.RETRIEVAL,
            "question targets the user's documents; ground the answer in them",
            capabilities=["retrieval"],
            tools=[TOOL_RAG_QUERY],
            context=[RequiredContext.USER_DOCUMENTS],
            fallback=ReasoningStrategy.DIRECT,
        )

    if category in _COMPARE_CATEGORIES:
        return decide(
            ReasoningStrategy.ANALYSIS,
            "comparison across attributes; structure before answering",
            capabilities=["structured_analysis"],
            fallback=ReasoningStrategy.DIRECT,
        )

    if category in _PROCEDURE_CATEGORIES:
        return decide(
            ReasoningStrategy.MULTI_STEP,
            "procedural request; produce ordered steps",
            capabilities=["planning"],
            fallback=ReasoningStrategy.DIRECT,
        )

    # 6. Evidence gaps that EVA's own knowledge cannot close.
    # 7. Gaps that EVA's own corpus might close.
    if assessment.exploration_required and assessment.evidence_sufficiency in (
        EvidenceSufficiency.INSUFFICIENT, EvidenceSufficiency.PARTIAL
    ):
        return decide(
            ReasoningStrategy.RETRIEVAL,
            "evidence is incomplete; retrieve before answering",
            capabilities=["retrieval"],
            tools=[TOOL_RAG_QUERY],
            context=[RequiredContext.USER_DOCUMENTS],
            fallback=ReasoningStrategy.DIRECT,
        )

    # 8. Nothing outstanding.
    return decide(
        ReasoningStrategy.DIRECT,
        "understanding and evidence are sufficient to answer directly",
        capabilities=["general_reasoning"],
    )





