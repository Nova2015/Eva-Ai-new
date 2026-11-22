"""ACT â€” Step 11 of the Cognitive Engine: correction execution.

Step 10 decides WHAT should change. This performs an approved change. Step 9
decides whether it worked. Those three jobs stay in three modules, and this one
is deliberately the smallest.

    CORRECT  ->  ACT  ->  VERIFY
    propose      apply     prove

NOTHING IS CORRECTED UNTIL VERIFY SAYS SO
=========================================
There is no VERIFIED anywhere in this module's vocabulary, and no way to
produce one. `ActStatus.APPLIED` means a transformation ran â€” not that it
helped. The corrected artefact goes back through Step 9, which may well return
FAILED for a different reason than the one that was corrected, and that is the
loop working rather than a defect in it.

V1 IS DETERMINISTIC ONLY
========================
An action executes only if its issue code is in _DETERMINISTIC: a pure text
transformation with a precondition, no model, no tool, no network, no
subprocess, no filesystem. Everything else is refused.

Exactly ONE of Step 10's nine mapped codes qualifies. `unclosed_fence` has a
single correct repair - close the fence. The other eight do not: nothing can
determine which diagram type was meant, what data an empty chart should hold,
or where a missing bracket belonged. A transformation that guesses is a change
made without evidence, which is the thing Step 10 refuses to do and this must
not do on its behalf.

EVERY REMEDY CARRIES A PRECONDITION
===================================
Appending a closing fence to text that is already closed CREATES the very
defect it repairs - verified against review_engine, not assumed. So a remedy
must first confirm the defect is present in the artefact it holds. Step 10's
issue code says what review_engine found; the precondition says the artefact in
hand still matches. When they disagree, the action is refused and reassessment
is requested, because a correction aimed at a defect that is not there means
something upstream is out of date.

WHY run_plan IS NOT CALLED
==========================
executor.run_plan is the right executor and is not duplicated here - no task
loop, no tool dispatch, no budget of its own. It is not called because v1 has
nothing for it to execute, and routing through it anyway would break two
things:

  * `tool = task.required_tool or "think"` (executor.py) would record a `think`
    invocation in ActionRecord and Observation for a transformation that never
    touched a model. A false audit trail is worse than none.
  * `summary = output[:REASON_MAX]` would truncate the corrected artefact to
    400 characters - the exact defect Step 9's D1 fix removed.

What IS reused from the executor: its result models, its cancellation channel,
and its security gate. When a real execution request appears - one needing a
tool, a sandbox or the network - it belongs in run_plan, not here.

THE RETRY BUDGET IS READ, NEVER CONSUMED
========================================
correction.apply_to_state already calls register_retry() when it routes
CORRECT -> ACT. Charging again here would cost two retries per correction round
and halt the loop at half its intended depth.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Callable, Dict, List, NamedTuple, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .correction import CorrectionAction, CorrectionReport, CorrectionStatus
from .executor import (
    ExecutionResult,
    ExecutionStatus,
    PolicyDenied,
    TaskOutcome,
    _gate,
    cancellation_check,
)
from .state import (
    CognitiveError,
    CognitivePhase,
    CognitiveState,
    FailureCategory,
    Observation,
    PlannedTask,
    REASON_MAX,
    TaskStatus,
    redact_secrets,
)


class ActStatus(str, Enum):
    """Outcome of one correction-execution pass.

    Note what is absent: there is no VERIFIED and no SUCCESS. APPLIED says a
    transformation ran. Whether it fixed anything is Step 9's to answer.
    """

    APPLIED = "APPLIED"
    NOTHING_APPROVED = "NOTHING_APPROVED"
    REFUSED = "REFUSED"
    CANCELLED = "CANCELLED"
    RETRY_BUDGET_SPENT = "RETRY_BUDGET_SPENT"


class _Remedy(NamedTuple):
    """A deterministic repair, the condition under which it is valid, and what
    the artefact should look like afterwards.

    `precondition` exists because `transform` alone is unsafe: closing an
    already-closed fence opens one.

    `removes_construct` exists because the two kinds of repair leave the
    artefact in different states, and only the remedy knows which it is:

      repair in place   the construct survives and becomes valid, so the check
                        runs again and should report VERIFIED
      removal           the construct is deleted, so the check finds nothing of
                        that kind and reports NOT_REQUIRED

    Step 12 needs that distinction to tell "the defect is gone because the
    block was removed" from "the block vanished when it should have been
    repaired". Declaring it here rather than inferring it downstream means a
    new remedy cannot forget to say which it is.
    """

    precondition: Callable[[str], bool]
    transform: Callable[[str], str]
    description: str
    removes_construct: bool = False


def remedy_removes_construct(issue: str) -> bool:
    """Whether the remedy for this issue code deletes the construct it repairs.

    Public because Step 12 must ask it to judge a post-remedy NOT_REQUIRED, and
    reaching into _DETERMINISTIC from another module would couple that stage to
    this one's private table.
    """
    remedy = _DETERMINISTIC.get(issue)
    return bool(remedy and remedy.removes_construct)


_FENCE = "`" * 3

# Locating a block is not judging one. review_engine decides what is wrong with
# an artefact and its verdict arrives as the issue code; this only finds the
# block that verdict is about, and only when there is exactly one candidate.
_MERMAID_BLOCK_RE = re.compile(r"```mermaid[ \t]*\r?\n(.*?)```", re.S)

# Mermaid's own grammar, not review_engine's severity policy. Used for one
# safety question - "could this block be a diagram at all?" - so that unfencing
# can never destroy a real diagram.
_MERMAID_HEADERS = (
    "graph", "flowchart", "sequenceDiagram", "pie", "gantt", "classDiagram",
    "stateDiagram-v2", "stateDiagram", "erDiagram", "journey",
)


def _fence_is_open(text: str) -> bool:
    return text.count(_FENCE) % 2 == 1


def _close_fence(text: str) -> str:
    return text.rstrip() + "\n" + _FENCE


def _sole_mermaid_block(text: str):
    """The one mermaid block, or None when there is not exactly one.

    Step 10's action carries an issue code, never which block it came from. With
    two blocks the offending one is unidentifiable, so the action is refused
    rather than applied to a guess.
    """
    found = list(_MERMAID_BLOCK_RE.finditer(text or ""))
    return found[0] if len(found) == 1 else None


def _is_prose_fenced_as_diagram(text: str) -> bool:
    """A sole mermaid block that cannot be a diagram.

    The header test is what makes unfencing safe on its own terms: a body that
    starts with no recognised diagram type is not a diagram, so removing the
    fence cannot destroy one.

    The odd-fence test is the one that matters more. `_MERMAID_BLOCK_RE` is
    non-greedy, so it closes at the FIRST following fence â€” which, when the
    markers do not pair up, is not the end of the block. Unfencing then removes
    two markers that were never a pair and leaves a stray one behind, creating
    the unclosed_fence this module exists to repair. Refuse instead.
    """
    if _fence_is_open(text):
        return False
    block = _sole_mermaid_block(text)
    if block is None:
        return False
    body = block.group(1).strip()
    if not body:
        return False
    first = body.splitlines()[0].strip()
    return not any(re.match(rf"^{re.escape(h)}\b", first) for h in _MERMAID_HEADERS)


def _unfence_diagram(text: str) -> str:
    """Keep every character of the body; drop only the fence markers."""
    block = _sole_mermaid_block(text)
    return text[:block.start()] + block.group(1).strip() + text[block.end():]


def _is_empty_diagram(text: str) -> bool:
    """A sole mermaid block containing nothing at all.

    Deliberately narrower than review_engine's empty_diagram, which also fires
    for a header with no nodes. A header is something a writer typed; deleting
    it destroys authored text, and deletion is the most destructive edit
    available. Whitespace is nothing, so removing it destroys nothing.
    """
    if _fence_is_open(text):
        return False        # block boundaries are unreliable; see _is_prose_...
    block = _sole_mermaid_block(text)
    return block is not None and not block.group(1).strip()


def _drop_empty_diagram(text: str) -> str:
    block = _sole_mermaid_block(text)
    return (text[:block.start()].rstrip() + "\n" + text[block.end():].lstrip()).strip()


# The whole of ACT's execution capability. Adding an entry is the only way to
# make ACT able to change anything new, which keeps the blast radius reviewable.
#
# Every entry repairs by REARRANGING what the artefact already contains - a
# fence closed, a fence removed, whitespace deleted. None of them writes a
# character of content, which is the line that separates a deterministic repair
# from authoring.
#
# Not included, and why:
#   python_syntax_error / json_parse_error  the correct source is unknowable
#   missing_diagram_type                    which type was meant is unknowable
#   unbalanced_brackets                     where the bracket belonged is unknowable
#   empty_data / malformed_block            TESTED AND REJECTED. Dropping a
#       chart block leaves the prose still announcing a chart, which
#       review_engine then reports as claim_without_block - one defect traded
#       for another. A test keeps that finding from being quietly forgotten.
_ARITHMETIC_EVIDENCE = re.compile(
    r"^recomputed=(?P<value>[+-]?(?:\d+(?:\.\d+)?|\.\d+))$"
)


def _arithmetic_repair_from_evidence(
    original: str,
    evidence: Sequence[str],
) -> Optional[str]:
    """Apply only the independently verified arithmetic result.

    ACT never evaluates the expression. VERIFY already did that.
    ACT only substitutes the verifier-provided recomputed value after
    confirming that the supplied artefact has the expected arithmetic shape.
    """
    if not original or not str(original).strip():
        return None

    match = re.search(
        r"(?P<expr>[+-]?(?:\d+(?:\.\d+)?|\.\d+)"
        r"(?:\s*(?:\*\*|//|[+\-*/%])\s*[+-]?(?:\d+(?:\.\d+)?|\.\d+))+"
        r")\s*=\s*(?P<result>[+-]?(?:\d+(?:\.\d+)?|\.\d+))",
        str(original),
    )
    if match is None:
        return None

    recomputed = None
    stated = None

    for item in evidence:
        value_match = _ARITHMETIC_EVIDENCE.match(str(item).strip())
        if value_match:
            recomputed = value_match.group("value")
        elif str(item).strip().startswith("stated="):
            stated = str(item).strip()[len("stated="):]

    if recomputed is None or stated is None:
        return None

    if match.group("result") != stated:
        return None

    return (
        str(original)[:match.start("result")]
        + recomputed
        + str(original)[match.end("result"):]
    )


def _python_syntax_repair_from_evidence(
    original: str,
    evidence: Sequence[str],
) -> Optional[str]:
    """Apply only an evidence-backed, single-delimiter Python repair.

    VERIFY owns the syntax verdict. ACT may only:
      1. locate exactly one Python fenced block,
      2. confirm the verifier reported an unclosed delimiter,
      3. find exactly one unmatched opener,
      4. append its deterministic closer,
      5. require ast.parse() to accept the resulting block.

    No model, execution, filesystem, or arbitrary rewrite is used.
    """
    import ast

    details = " ".join(str(item) for item in evidence).lower()
    if "was never closed" not in details:
        return None

    matches = list(re.finditer(
        r"```(?:python|py)\s*\n(?P<body>.*?)```",
        str(original),
        flags=re.IGNORECASE | re.DOTALL,
    ))
    if len(matches) != 1:
        return None

    match = matches[0]
    body = match.group("body")

    # Conservative lexical scan. Strings/comments are removed by tokenize;
    # if tokenization itself fails, we refuse rather than guess.
    import io
    import tokenize

    stack = []
    pairs = {")": "(", "]": "[", "}": "{"}
    closing = {"(": ")", "[": "]", "{": "}"}

    try:
        tokens = tokenize.generate_tokens(io.StringIO(body).readline)
        for tok in tokens:
            if tok.type == tokenize.OP:
                value = tok.string
                if value in closing:
                    stack.append(value)
                elif value in pairs:
                    if not stack or stack[-1] != pairs[value]:
                        return None
                    stack.pop()
    except tokenize.TokenError as exc:
        # tokenize reports an incomplete expression as EOF in a
        # multi-line statement. This is precisely the single-delimiter
        # case supported by this deterministic repair.
        if "EOF in multi-line statement" not in str(exc):
            return None
    except (IndentationError, SyntaxError):
        return None

    # Exactly one unmatched opener is required.
    if len(stack) != 1:
        return None

    candidate_body = body + closing[stack[0]]

    try:
        ast.parse(candidate_body)
    except (SyntaxError, ValueError, TypeError):
        return None

    return (
        str(original)[:match.start("body")]
        + candidate_body
        + str(original)[match.end("body"):]
    )


_DETERMINISTIC: Dict[str, _Remedy] = {
    # Repairs in place: the block survives and becomes valid, so the check runs
    # again and must report VERIFIED. A NOT_REQUIRED here would mean the block
    # disappeared, which is a failure of this remedy, not a success.
    "unclosed_fence": _Remedy(
        precondition=_fence_is_open,
        transform=_close_fence,
        description="close the unterminated code fence",
        removes_construct=False,
    ),
    # Both of these DELETE the mermaid block rather than fixing it, so the
    # diagram check afterwards finds nothing to check. That is success, not an
    # absent verdict â€” see removes_construct on _Remedy.
    "prose_not_diagram": _Remedy(
        precondition=_is_prose_fenced_as_diagram,
        transform=_unfence_diagram,
        description="unfence the block; its text is prose, not a diagram",
        removes_construct=True,
    ),
    "empty_diagram": _Remedy(
        precondition=_is_empty_diagram,
        transform=_drop_empty_diagram,
        description="remove the empty mermaid block",
        removes_construct=True,
    ),
}

# How much of an artefact a log-safe view may show. Small on purpose: this is a
# description of the evidence, not the evidence.
_PREVIEW_CHARS = 120

_R_NOT_APPROVED = "not in the approved allow-list"
_R_DENIED = "target task was refused by policy"
_R_NO_REMEDY = "no deterministic remedy for this issue"
_R_NO_ARTIFACT = "no artefact supplied for the target"
_R_PRECONDITION = "the defect is not present in the artefact supplied"
_C_CANCELLED = "execution was cancelled; nothing was applied"
_C_BUDGET = "retry budget is spent; nothing was applied"


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


def _safe_view(text: str) -> str:
    """A log-safe description of an artefact. Never the artefact itself.

    Redaction happens BEFORE the slice, so a bounded preview cannot cut a
    credential in half and leak the readable fragment. The `chars=` prefix
    means the result is structurally incapable of being byte-equal to the
    artefact, however short the artefact is.
    """
    redacted = redact_secrets(text or "")
    preview = " ".join(redacted[:_PREVIEW_CHARS].split())
    return f"chars={len(text or '')} lines={(text or '').count(chr(10)) + 1} preview={preview}"


class ActResult(_Base):
    """What ACT did, and the evidence VERIFY needs to judge it.

    `artifacts` is deliberately OUTSIDE ExecutionResult. Step 2's models scrub
    every text field to REASON_MAX, so an artefact stored in one would arrive
    at Step 9 truncated and validate as broken - that was D1. Keeping it here,
    and passing it to verify() explicitly, means the evidence stays intact and
    stays out of persisted state.

    THIS OBJECT IS NOT SAFE TO LOG. `artifacts` holds exactly what ACT
    produced, byte for byte, including anything credential-shaped that was
    already in the artefact. That is required rather than tolerated: Step 9
    must verify the bytes that were actually produced, and redacting first
    would mean VERIFY judges text nobody wrote - a redaction inside a JSON
    block can turn a valid artefact into a parse failure, which would be a
    verdict about the redaction rather than about the work.

    Use `safe_artifacts` for anything that gets logged, displayed or persisted.
    Never model_dump() this whole object into a log.
    """

    execution: ExecutionResult = Field(default_factory=ExecutionResult)
    # task_id -> the corrected artefact, EXACT. Not redacted, not truncated.
    # This is what goes to verify(artifacts=...) and nowhere else.
    artifacts: Dict[str, str] = Field(default_factory=dict)
    # task_id -> a redacted, bounded description of the same artefact. This is
    # the only representation that may reach a log or a human.
    safe_artifacts: Dict[str, str] = Field(default_factory=dict)
    applied_actions: List[str] = Field(default_factory=list)
    applied_tasks: List[str] = Field(default_factory=list)
    refused_actions: List[str] = Field(default_factory=list)
    refused_tasks: List[str] = Field(default_factory=list)
    # Why each refusal happened, in the same order as refused_actions.
    refusals: List[str] = Field(default_factory=list)
    requires_reassessment: bool = False
    status: ActStatus = ActStatus.NOTHING_APPROVED
    reason: str = ""

    # `artifacts` has NO validator, deliberately. Every other text field in the
    # cognitive package is scrubbed on the way in; this one must not be, or
    # Step 9 verifies something other than what ACT produced.

    @field_validator("safe_artifacts")
    @classmethod
    def _scrub_safe(cls, v: Dict[str, str]) -> Dict[str, str]:
        """Belt and braces over _safe_view, which already redacts."""
        return {k: redact_secrets(str(text or ""))[:REASON_MAX]
                for k, text in v.items()}

    @field_validator("reason")
    @classmethod
    def _scrub(cls, v: str) -> str:
        return redact_secrets(str(v or ""))[:REASON_MAX]

    @field_validator("refusals", "applied_actions", "applied_tasks",
                     "refused_actions", "refused_tasks")
    @classmethod
    def _scrub_list(cls, v: List[str]) -> List[str]:
        return [redact_secrets(str(i or ""))[:REASON_MAX] for i in v]


def _authorized(action: CorrectionAction, selection) -> None:
    """Apply the executor's own security gate when a Step 7 grant exists.

    Reused rather than restated so there is one definition of "authorized" in
    the engine. When no selection is supplied nothing is self-granted: the
    action is still bounded by _DETERMINISTIC, which is the stronger guarantee
    here anyway - a capability this module awarded itself would prove nothing.
    """
    if selection is None:
        return
    task = PlannedTask(task_id=action.target or "act", objective="apply correction",
                       status=TaskStatus.PENDING)
    _gate(task, selection, set(), set())


def act(
    state: CognitiveState,
    report: CorrectionReport,
    approved_action_ids: Sequence[str],
    artifacts: Optional[Dict[str, str]] = None,
    run_id: Optional[str] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
    selection=None,
) -> ActResult:
    """Apply the approved corrections that can be applied deterministically.

    `approved_action_ids` is an explicit allow-list. An empty list applies
    nothing and is not an error: approval is a decision made outside this
    module, and Step 10 cannot grant it to itself.

    Reads `state`, never writes it. apply_to_state() moves the phase.
    """
    approved = set(approved_action_ids or ())
    supplied = dict(artifacts or {})

    applied_actions: List[str] = []
    applied_tasks: List[str] = []
    refused_actions: List[str] = []
    refused_tasks: List[str] = []
    refusals: List[str] = []
    produced: Dict[str, str] = {}
    outcomes: List[TaskOutcome] = []
    observations: List[Observation] = []
    errors: List[CognitiveError] = []
    requires_reassessment = False

    def refuse(action: CorrectionAction, why: str, policy: bool = False,
               reassess: bool = False) -> None:
        nonlocal requires_reassessment
        refused_actions.append(action.action_id)
        refusals.append(why)
        if action.target and action.target not in refused_tasks:
            refused_tasks.append(action.target)
        outcomes.append(TaskOutcome(
            task_id=action.target or action.action_id,
            status=TaskStatus.SKIPPED,
            error_category=(FailureCategory.SECURITY_BLOCK if policy else None),
            safe_summary=why[:REASON_MAX],
        ))
        if policy:
            errors.append(CognitiveError(
                category=FailureCategory.SECURITY_BLOCK,
                message=why, task_id=action.target or None))
        if reassess:
            requires_reassessment = True

    # â”€â”€ cancellation ends it, before anything is examined â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    cancelled = is_cancelled or cancellation_check(run_id)
    if report.status is CorrectionStatus.CANCELLED or cancelled():
        return ActResult(
            execution=ExecutionResult(
                final_execution_status=ExecutionStatus.CANCELLED),
            status=ActStatus.CANCELLED, reason=_C_CANCELLED,
            requires_reassessment=False)

    # â”€â”€ the retry budget is read, not spent â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if state.retries_remaining() <= 0:
        return ActResult(
            execution=ExecutionResult(
                requires_reassessment=True,
                final_execution_status=ExecutionStatus.EXECUTION_FAILED),
            status=ActStatus.RETRY_BUDGET_SPENT, reason=_C_BUDGET,
            requires_reassessment=True)

    # A task the executor refused must not be reached through a correction.
    # Step 10 already guarantees no action targets one; this is checked again
    # because ACT is handed a report, not the report Step 10 happened to build,
    # and a security boundary that trusts its caller is not one.
    denied = {entry.split(":", 1)[0].strip()
              for entry in report.blocking_issues if ":" in entry}

    for action in report.corrections:
        if action.action_id not in approved:
            refuse(action, _R_NOT_APPROVED)
            continue

        if action.target in denied:
            refuse(action, _R_DENIED, policy=True)
            continue

        try:
            _authorized(action, selection)
        except PolicyDenied as refusal:
            refuse(action, str(refusal)[:REASON_MAX], policy=True)
            continue

        # Arithmetic is an evidence-driven repair.
        # VERIFY owns the calculation. ACT only applies the exact
        # verifier-provided recomputed value.
        if action.issue == "arithmetic_result_mismatch":
            original = supplied.get(action.target)
            if not original or not str(original).strip():
                refuse(action, _R_NO_ARTIFACT, reassess=True)
                continue

            corrected = _arithmetic_repair_from_evidence(
                str(original), action.evidence
            )
            if corrected is None:
                refuse(action, _R_PRECONDITION, reassess=True)
                continue

            produced[action.target] = corrected
            applied_actions.append(action.action_id)

            if action.target not in applied_tasks:
                applied_tasks.append(action.target)

            outcomes.append(TaskOutcome(
                task_id=action.target,
                status=TaskStatus.COMPLETED,
                success=True,
                safe_summary=f"applied={action.issue}",
                verification_required=True,
            ))
            continue
        # Python syntax repair is evidence-driven and validated with ast.parse.
        # ACT never invents Python; it only applies one verifier-supported
        # missing-delimiter repair and VERIFY must run again afterward.
        if action.issue == "python_syntax_error":
            original = supplied.get(action.target)
            if not original or not str(original).strip():
                refuse(action, _R_NO_ARTIFACT, reassess=True)
                continue

            corrected = _python_syntax_repair_from_evidence(
                str(original), action.evidence
            )
            if corrected is None:
                refuse(action, _R_PRECONDITION, reassess=True)
                continue

            produced[action.target] = corrected
            applied_actions.append(action.action_id)

            if action.target not in applied_tasks:
                applied_tasks.append(action.target)

            outcomes.append(TaskOutcome(
                task_id=action.target,
                status=TaskStatus.COMPLETED,
                success=True,
                safe_summary=f"applied={action.issue}",
                verification_required=True,
            ))
            continue

        remedy = _DETERMINISTIC.get(action.issue)
        if remedy is None:
            # v1 executes nothing it cannot derive. An unmapped correction is
            # a real defect with no safe automatic repair, which is a reason to
            # think again rather than to improvise.
            refuse(action, _R_NO_REMEDY, reassess=True)
            continue

        original = supplied.get(action.target)
        if not original or not str(original).strip():
            refuse(action, _R_NO_ARTIFACT, reassess=True)
            continue

        # A remedy that raises is a remedy that does not apply. With one
        # entry this was theoretical; with several, each carrying its own
        # parsing, a malformed artefact must refuse rather than take ACT down
        # mid-run and leave earlier corrections unreported.
        try:
            applies = remedy.precondition(str(original))
        except Exception:
            applies = False
        if not applies:
            refuse(action, _R_PRECONDITION, reassess=True)
            continue

        try:
            corrected = remedy.transform(str(original))
        except Exception:
            refuse(action, _R_PRECONDITION, reassess=True)
            continue
        produced[action.target] = corrected
        applied_actions.append(action.action_id)
        if action.target not in applied_tasks:
            applied_tasks.append(action.target)
        outcomes.append(TaskOutcome(
            task_id=action.target, status=TaskStatus.COMPLETED, success=True,
            # Operational fact only. The artefact itself travels in `artifacts`.
            safe_summary=f"applied={action.issue}",
            verification_required=True,
        ))
        observations.append(Observation(
            task_id=action.target,
            summary=f"applied={action.issue} remedy=deterministic",
            evidence_refs=["act:deterministic"]))

    # â”€â”€ status, most decisive first â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if applied_actions:
        status = ActStatus.APPLIED
        reason = (f"{len(applied_actions)} correction(s) applied; "
                  f"verification required")
    elif not approved:
        status = ActStatus.NOTHING_APPROVED
        reason = "no correction was approved for execution"
    else:
        status = ActStatus.REFUSED
        reason = f"{len(refused_actions)} correction(s) refused"

    if requires_reassessment:
        execution_status = ExecutionStatus.REASSESS_REQUIRED
    elif applied_actions:
        execution_status = ExecutionStatus.EXECUTION_COMPLETE
    elif refused_actions:
        execution_status = ExecutionStatus.EXECUTION_FAILED
    else:
        execution_status = ExecutionStatus.EXECUTION_COMPLETE

    execution = ExecutionResult(
        success=bool(applied_actions) and not requires_reassessment,
        completed_tasks=list(applied_tasks),
        denied_tasks=[t for t in refused_tasks if t in denied],
        skipped_tasks=[t for t in refused_tasks if t not in denied],
        outcomes=outcomes,
        observations=observations,
        errors=errors,
        requires_reassessment=requires_reassessment,
        # Always. An applied correction is unproven until Step 9 says otherwise.
        requires_verification=bool(applied_actions),
        final_execution_status=execution_status,
    )

    return ActResult(
        execution=execution,
        artifacts=produced,
        safe_artifacts={task_id: _safe_view(text)
                        for task_id, text in produced.items()},
        applied_actions=applied_actions,
        applied_tasks=applied_tasks,
        refused_actions=refused_actions,
        refused_tasks=refused_tasks,
        refusals=refusals,
        requires_reassessment=requires_reassessment,
        status=status,
        reason=reason,
    )


def apply_to_state(state: CognitiveState, result: ActResult) -> CognitiveState:
    """Record the pass and move the phase. Consumes no retry.

    On success the move is ACT -> VERIFY, which is the point of the stage: an
    applied change is evidence to be judged, never a conclusion. There is no
    path from here to LEARN or RESPOND, because nothing has been proven yet.
    """
    state.observations.extend(result.execution.observations)
    state.errors.extend(result.execution.errors)

    if result.status is ActStatus.CANCELLED:
        if state.can_transition_to(CognitivePhase.ABORTED):
            state.transition_to(CognitivePhase.ABORTED)
        return state

    if state.phase is not CognitivePhase.ACT and \
            state.can_transition_to(CognitivePhase.ACT):
        state.transition_to(CognitivePhase.ACT)

    # Reassessment beats verification: if the correction could not safely
    # proceed, there is nothing worth verifying.
    target = (CognitivePhase.ASSESS if result.requires_reassessment
              else CognitivePhase.VERIFY)
    if state.can_transition_to(target):
        state.transition_to(target)
    return state




