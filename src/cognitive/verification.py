"""Verification â€” Step 9 of the Cognitive Engine.

Answers: **did execution actually produce a correct result?**

Contains no validators of its own. `review_engine` already implements
`validate_code`, `validate_charts` and `validate_mermaid`, and
`run_review_pipeline` is the entry point production already uses. This maps
Step 5's declared verification requirements onto those checks and reports the
verdict in Step 2's vocabulary.

IT DOES NOT INHERIT REVIEW_ENGINE'S OPTIMISM
============================================
`run_review_pipeline` is deliberately FAIL-OPEN: if a validator crashes it
returns `valid=True` with `review_meta.error` set, because review is
observational there and must never block a reply.

That default is exactly wrong for verification. "The checker broke" is not
evidence the answer is correct. `derive_status` already draws this distinction
â€” an error maps to UNKNOWN, never VALID â€” and this module carries it through to
INCONCLUSIVE. Claiming VERIFIED for a check that never ran would make the whole
stage worse than useless, because Step 10 would then skip a correction that was
actually needed.

WHAT CAN AND CANNOT BE VERIFIED HERE
====================================
Step 5 names eight verification requirements. Only three have a local
implementation:

    CODE_VALIDATION     -> review_engine.validate_code
    CHART_VALIDATION    -> review_engine.validate_charts
    DIAGRAM_VALIDATION  -> review_engine.validate_mermaid

    EXECUTION_TEST      -> runtime_engine, injected (async + network)
    CITATION_CHECK      -> grounded_sources, lives on the ML service
        ARITHMETIC_RECHECK  -> no implementation exists
    CONSISTENCY_CHECK   -> structured task-order validator,
                           requires explicit tasks and proposed order
Requirements without an available checker are reported INCONCLUSIVE,
never VERIFIED. CONSISTENCY_CHECK is verified only when the structured
adapter actually validates the supplied task graph and proposed order.

A DIGEST IS NOT AN ARTEFACT
===========================
Only text the caller supplies in `artifacts` is validated. Observation.summary
is scrubbed to REASON_MAX by Step 2, so a real code block arrives cut in half
and `validate_code` correctly calls the truncation `unclosed_fence` â€” a FATAL
code. Verifying summaries therefore reported FAILED for correct artefacts, on
every artefact longer than 400 characters.

That is the same lie as VERIFIED-without-a-check, pointed the other way: it
sends Step 10 to correct code that was never broken. Missing evidence is
INCONCLUSIVE. It is never FAILED.

EACH CHECK IS JUDGED ON ITS OWN ISSUES
======================================
review["issues"] and review["score"] span every validator. Deriving one
requirement's verdict from them let a fatal mermaid defect mark CODE_VALIDATION
as FAILED, and let a broken diagram halve a clean code check's confidence. Each
verdict now comes from review["checks"][name] alone.

NOT PURE. review_engine's JS path runs `node --check` in a subprocess against a
temp file. That is pre-existing, guarded by shutil.which, bounded by a 10s
timeout and cleaned up â€” but it means verification, unlike Steps 3-7, can touch
the filesystem and spawn a process. Python code is checked with ast.parse and
does neither.

NO CORRECTION, NO LEARNING, NO ANSWER. This reports a verdict. Step 10 decides
what to do about it.
"""

from __future__ import annotations

import copy
import hashlib
import ast
import math
import re
from enum import Enum
from typing import Callable, Dict, List, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .executor import ExecutionResult
from .planning import TaskPlan
from .state import (
    PlannedTask,
    VerificationResult,
    VerificationStatus,
    REASON_MAX,
    redact_secrets,
)
from .strategy import StrategyDecision, VerificationRequirement
# Structured task-order consistency verification.
try:
    from .consistency_adapter import verify_task_order_consistency
except Exception:
    verify_task_order_consistency = None
# review_engine is the verifier. Its absence yields INCONCLUSIVE â€” never a pass.
#
# Two import forms, because the package and one of its modules share the name
# `review_engine`. When src/review_engine/ is on sys.path (which the repo
# conftest does, so the flat fallbacks in its own tests resolve), the FILE
# review_engine.py shadows the PACKAGE, and `review_engine.integration_adapter`
# raises "not a package" â€” even though that is exactly the form app.py uses in
# production, where only src/ is on the path.
#
# The same dual-import pattern appears inside review_engine's own modules for
# the same reason. Trying the package form first keeps production's path the
# primary one.
try:
    from src.review_engine.integration_adapter import run_review_pipeline
    from src.review_engine.review_status import derive_status
    REVIEW_ENGINE_AVAILABLE = True
except Exception:
    run_review_pipeline = None
    derive_status = None
    REVIEW_ENGINE_AVAILABLE = False


# Said once, so every "we could not check this" path reads identically.
NO_ARTIFACT = "no verifiable artefact available"

# Length of a recorded artefact fingerprint. 16 hex characters is 64 bits: far
# beyond accidental collision between two artefacts in one session, and short
# enough that the report stays readable.
DIGEST_CHARS = 16


def artifact_digest(text: str) -> str:
    """A stable fingerprint of the artefact that was verified.

    Recorded so a later stage can prove a report describes the bytes it thinks
    it does. Step 12 could previously only check that an ActResult and a
    VerificationReport mentioned the same TASK, which a stale pre-correction
    report also satisfies - both reports are about the same task, and only the
    content differs.

    A hash, never the text: this travels in a structure meant to be logged, and
    the artefact itself must not. Unsalted, because two processes must agree on
    the value for the comparison to mean anything - which does mean someone
    holding a candidate artefact can confirm a guess, the standard trade for a
    content address.
    """
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:DIGEST_CHARS]

# derive_status speaks FAILED/WARNING/VALID/UNKNOWN/None. Step 2 speaks
# VERIFIED/FAILED/INCONCLUSIVE/NOT_REQUIRED. One mapping, stated once.
#
# WARNING becomes INCONCLUSIVE rather than VERIFIED: a non-fatal issue was
# found, so the artefact cannot be asserted correct, but neither is it plainly
# wrong. None becomes NOT_REQUIRED, preserving review_engine's own rule that
# plain prose asserts nothing.
_STATUS_MAP: Dict[Optional[str], VerificationStatus] = {
    "VALID": VerificationStatus.VERIFIED,
    "FAILED": VerificationStatus.FAILED,
    "WARNING": VerificationStatus.INCONCLUSIVE,
    "UNKNOWN": VerificationStatus.INCONCLUSIVE,
    None: VerificationStatus.NOT_REQUIRED,
}

# Which review_engine check answers which Step 5 requirement.
_REQUIREMENT_TO_CHECK: Dict[VerificationRequirement, str] = {
    VerificationRequirement.CODE_VALIDATION: "code",
    VerificationRequirement.CHART_VALIDATION: "chart",
    VerificationRequirement.DIAGRAM_VALIDATION: "mermaid",
}

# Requirements with no local implementation, and why. Reported, not pretended.
_UNBACKED: Dict[VerificationRequirement, str] = {
    VerificationRequirement.EXECUTION_TEST:
        "needs runtime_engine; supply a code_runner to enable it",
    VerificationRequirement.CITATION_CHECK:
        "grounded_sources runs on the ML service, not in this process",
    VerificationRequirement.CONSISTENCY_CHECK:
        "structured consistency adapter is unavailable",
}



# Deterministic local arithmetic verification. Unsupported or ambiguous
# expressions remain INCONCLUSIVE; arbitrary Python is never executed.
_ARITHMETIC_PATTERN = re.compile(
    r"(?P<expr>[+-]?(?:\d+(?:\.\d+)?|\.\d+)"
    r"(?:\s*(?:\*\*|//|[+\-*/%])\s*[+-]?(?:\d+(?:\.\d+)?|\.\d+))+"
    r")\s*=\s*(?P<result>[+-]?(?:\d+(?:\.\d+)?|\.\d+))"
)


def _safe_arithmetic_value(node: ast.AST) -> float:
    """Evaluate only the bounded arithmetic AST supported by the verifier."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        value = float(node.value)
        if math.isfinite(value) and abs(value) <= 1_000_000_000:
            return value
        raise ValueError("numeric value outside verifier bounds")

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _safe_arithmetic_value(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value

    if not isinstance(node, ast.BinOp):
        raise ValueError("unsupported arithmetic expression")

    left = _safe_arithmetic_value(node.left)
    right = _safe_arithmetic_value(node.right)

    if isinstance(node.op, ast.Add):
        value = left + right
    elif isinstance(node.op, ast.Sub):
        value = left - right
    elif isinstance(node.op, ast.Mult):
        value = left * right
    elif isinstance(node.op, ast.Div):
        if right == 0:
            raise ValueError("division by zero")
        value = left / right
    elif isinstance(node.op, ast.FloorDiv):
        if right == 0:
            raise ValueError("division by zero")
        value = left // right
    elif isinstance(node.op, ast.Mod):
        if right == 0:
            raise ValueError("division by zero")
        value = left % right
    elif isinstance(node.op, ast.Pow):
        if abs(right) > 20:
            raise ValueError("exponent outside verifier bounds")
        value = left ** right
    else:
        raise ValueError("unsupported arithmetic operator")

    if not math.isfinite(value) or abs(value) > 1_000_000_000:
        raise ValueError("arithmetic result outside verifier bounds")
    return float(value)


def _arithmetic_check(text: str, task_id: Optional[str]) -> VerificationResult:
    """Independently recompute one explicitly stated arithmetic claim."""
    match = _ARITHMETIC_PATTERN.search(text or '')
    if not match:
        return _unchecked(
            VerificationRequirement.ARITHMETIC_RECHECK,
            "no explicit arithmetic expression/result pair found",
            task_id,
            ["arithmetic"],
        )

    expression = match.group('expr')
    stated = float(match.group('result'))

    try:
        tree = ast.parse(expression, mode='eval')
        computed = _safe_arithmetic_value(tree.body)
    except Exception as exc:
        return _unchecked(
            VerificationRequirement.ARITHMETIC_RECHECK,
            f"arithmetic expression not independently evaluable: {type(exc).__name__}",
            task_id,
            ["arithmetic"],
        )

    if math.isclose(computed, stated, rel_tol=1e-12, abs_tol=1e-12):
        return VerificationResult(
            task_id=task_id,
            status=VerificationStatus.VERIFIED,
            verification_type=VerificationRequirement.ARITHMETIC_RECHECK.value,
            criteria=["arithmetic"],
            confidence=1.0,
        )

    return VerificationResult(
        task_id=task_id,
        status=VerificationStatus.FAILED,
        verification_type=VerificationRequirement.ARITHMETIC_RECHECK.value,
        criteria=["arithmetic", "recomputed=" + f"{computed:g}", "stated=" + f"{stated:g}"],
        failure_reason="arithmetic_result_mismatch",
        confidence=1.0,
    )


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class VerificationReport(_Base):
    results: List[VerificationResult] = Field(default_factory=list)
    status: VerificationStatus = VerificationStatus.NOT_REQUIRED
    verified_count: int = 0
    failed_count: int = 0
    inconclusive_count: int = 0
    # Requirements Step 5 asked for that nothing here can actually check.
    unverifiable: List[str] = Field(default_factory=list)
    # task_id -> fingerprint of the artefact actually read for that task.
    # Present only where an artefact was genuinely verified, which is what
    # makes its ABSENCE meaningful: no entry means no verdict about content.
    artifact_digests: Dict[str, str] = Field(default_factory=dict)
    summary: str = ""

    @field_validator("summary")
    @classmethod
    def _scrub(cls, v: str) -> str:
        return redact_secrets(str(v or ""))[:REASON_MAX]

    @field_validator("unverifiable")
    @classmethod
    def _scrub_list(cls, v: List[str]) -> List[str]:
        return [redact_secrets(str(i or ""))[:REASON_MAX] for i in v]

    def results_for(self, task_id: str) -> List[VerificationResult]:
        return [r for r in self.results if r.task_id == task_id]


def _aggregate(results: Sequence[VerificationResult]) -> VerificationStatus:
    """Worst case wins, matching CognitiveState.verification_status().

    An overall VERIFIED must be impossible while any check failed or could not
    be run â€” that is the property the whole stage rests on.
    """
    statuses = {r.status for r in results}
    if VerificationStatus.FAILED in statuses:
        return VerificationStatus.FAILED
    if VerificationStatus.INCONCLUSIVE in statuses:
        return VerificationStatus.INCONCLUSIVE
    if VerificationStatus.VERIFIED in statuses:
        return VerificationStatus.VERIFIED
    return VerificationStatus.NOT_REQUIRED


def _artifact_for(task: PlannedTask,
                  artifacts: Optional[Dict[str, str]]) -> Optional[str]:
    """The artefact to check, or None when there isn't one.

    Only an explicitly supplied artefact counts. Observation.summary was the
    fallback and cannot be: Step 2 caps it at REASON_MAX, so anything real
    arrives truncated and validates as broken. Length is not the test either â€”
    a summary that happens to fit is still a digest, and asserting a verdict
    about the artefact from its digest is unsound at any size.

    Step 8 deliberately produces no final answer, so when the caller supplies
    nothing there is genuinely nothing to verify. That is INCONCLUSIVE.
    """
    if artifacts and task.task_id in artifacts:
        text = str(artifacts[task.task_id] or "")
        if text.strip():
            return text
    return None


def _unchecked(requirement: VerificationRequirement, reason: str,
               task_id: Optional[str] = None,
               criteria: Optional[List[str]] = None) -> VerificationResult:
    """A requirement that could not be answered. Never VERIFIED, never FAILED."""
    return VerificationResult(
        task_id=task_id,
        status=VerificationStatus.INCONCLUSIVE,
        verification_type=requirement.value,
        criteria=list(criteria or []),
        failure_reason=reason[:REASON_MAX],
        confidence=0.0,
    )


# The mode every caller in the chat path uses. Named so a future second mode
# cannot silently share a cached payload with the first.
REVIEW_MODE = "standard"


def available_requirements(
    code_runner: Optional[Callable[[str], dict]] = None,
) -> "frozenset":
    """Which verification requirements this runtime can actually execute.

    A FUNCTION, not a constant, because capability is context-dependent:
    EXECUTION_TEST is real the moment a caller supplies a runner, and absent
    when it does not. Freezing that into a module constant would hard-code one
    caller's limitations into every caller's.

    Step 5 asks what would prove an answer right. This answers what can be run
    here. Requesting a check nothing can execute produced the state Update 14
    exists to fix: five of eight strategies asked only for unrunnable checks, so
    verification never returned a verdict, correction never proposed, and the
    loop was inert for most traffic.

    What is NOT here is as important as what is. CITATION_CHECK lives on the ML
    service, and ARITHMETIC_RECHECK has no implementation. CONSISTENCY_CHECK
    has a deterministic structured adapter, but it is not advertised as
    generally available because it requires explicit task-order inputs.
    """
    runnable = set(_REQUIREMENT_TO_CHECK)          # code / chart / diagram
    if not REVIEW_ENGINE_AVAILABLE:
        # No validators reachable, so none of the three can actually run.
        runnable = set()
    runnable.add(VerificationRequirement.ARITHMETIC_RECHECK)
    if code_runner is not None:
        runnable.add(VerificationRequirement.EXECUTION_TEST)
    return frozenset(runnable)


def new_review_cache() -> Dict[str, dict]:
    """A request-scoped store for review payloads, owned by the caller.

    Deliberately not a module-level cache. A process-wide one would hold
    response text for the lifetime of the worker, key a security-relevant
    verdict across unrelated users, and need eviction nobody would tune. This
    lives exactly as long as the request that made it.
    """
    return {}


def review_key(text: str, mode: str = REVIEW_MODE) -> str:
    """Cache identity: the exact bytes reviewed, plus the mode that reviewed
    them. Different text is a different key, so a corrected artefact can never
    inherit the verdict of the one it replaced."""
    return f"{mode}:{artifact_digest(text)}"


def review_once(text: str, cache: Optional[Dict[str, dict]] = None,
                mode: str = REVIEW_MODE) -> Optional[dict]:
    """Review this artefact, reusing a payload already computed for it.

    Reuse is only ever for byte-identical text, so this removes duplicate WORK
    without removing a single check: every distinct artefact is still reviewed,
    and a corrected one is reviewed again because its bytes differ.

    A cache miss, a broken cache, or no cache at all falls through to running
    the pipeline â€” the sharing can fail without weakening anything.
    """
    if not REVIEW_ENGINE_AVAILABLE or run_review_pipeline is None:
        return None

    key = review_key(text or "", mode)
    if cache is not None:
        try:
            hit = cache.get(key)
        except Exception:      # a caller passed something dict-like and broken
            hit = None
        if hit is not None:
            # A COPY, never the stored object. app.py's review hook does
            # `review.update(status)` on what it receives, so handing out the
            # cached dict would let one consumer edit what the next one reads.
            # Deep, because a shallow copy still shares `issues` and `checks` â€”
            # the lists a verdict is actually derived from. ~13us against an
            # ~80ms node --check pass.
            return copy.deepcopy(hit)

    try:
        payload = run_review_pipeline(text or "", mode=mode)
    except Exception:
        # run_review_pipeline is documented never to raise; if it somehow does,
        # that is a broken checker, which means INCONCLUSIVE, not a pass.
        return None

    if cache is not None:
        try:
            # The cache keeps its own copy; the caller keeps the original. Two
            # objects from here on, so neither can edit the other's. Copying
            # only on READ would not be enough: on a miss the caller receives
            # the very object being stored, so the first consumer to touch it
            # corrupts what every later one reads.
            cache[key] = copy.deepcopy(payload)
        except Exception:
            pass               # sharing is an optimisation, never a requirement
    return payload


def _review(text: str, cache: Optional[Dict[str, dict]] = None) -> Optional[dict]:
    return review_once(text, cache)


def _only(check_name: str, check: dict) -> dict:
    """A review payload narrowed to one check.

    derive_status reads the TOP-LEVEL issues list, which pools every
    validator's findings â€” so asking it about the whole payload answered a
    question about the artefact, not about this check. Feeding it a payload
    containing only this check asks the right question while keeping
    review_engine's severity rules (FATAL_CODES / WARN_CODES) the single
    authority on fatal-vs-warning. None of that vocabulary is copied here; if
    review_engine reclassifies a code, this follows automatically.
    """
    return {
        "issues": [i for i in (check.get("issues") or []) if isinstance(i, dict)],
        "checks": {check_name: check},
        # Emptied deliberately: a pipeline-wide error is handled before this is
        # reached, and leaving it in would make every narrowed check UNKNOWN.
        "review_meta": {},
    }


def _check_result(
    requirement: VerificationRequirement,
    review: Optional[dict],
    task_id: str,
) -> VerificationResult:
    """Turn one check inside a review payload into one typed verdict.

    Reads review["checks"][name] and nothing else, so no other validator's
    findings can reach this verdict or its confidence.
    """
    check_name = _REQUIREMENT_TO_CHECK[requirement]

    if review is None:
        return _unchecked(requirement, "review_engine unavailable",
                          task_id, [check_name])

    # BEFORE the applicable test, not after. run_review_pipeline is fail-open:
    # a crashed validator yields valid=True with checks={} and the error in
    # review_meta. Testing `applicable` first read that empty dict as "nothing
    # of this kind present" and returned NOT_REQUIRED, so the guard below could
    # not fire on any payload the real adapter produces.
    if (review.get("review_meta") or {}).get("error"):
        return _unchecked(requirement, "validator error; result not asserted",
                          task_id, [check_name])

    check = (review.get("checks") or {}).get(check_name) or {}

    # Nothing of this kind was present in the artefact. review_engine's own
    # rule: assert nothing rather than pass by default.
    if not check.get("applicable"):
        return VerificationResult(
            task_id=task_id, status=VerificationStatus.NOT_REQUIRED,
            verification_type=requirement.value, criteria=[check_name],
            confidence=0.0,
        )

    issues = [i for i in (check.get("issues") or []) if isinstance(i, dict)]
    codes = [str(i.get("code", "")) for i in issues]
    passed = bool(check.get("passed")) and not issues

    derived = (derive_status(_only(check_name, check)) if derive_status
               else {"status": "UNKNOWN"})
    status = _STATUS_MAP.get(derived.get("status"), VerificationStatus.INCONCLUSIVE)

    # Two independent sources must agree before anything is called VERIFIED:
    # review_engine's severity verdict, and the validator's own `passed` flag.
    # Either one alone would be a single point of failure for the property the
    # whole stage rests on.
    if status is VerificationStatus.VERIFIED and not passed:
        status = VerificationStatus.INCONCLUSIVE

    verified = status is VerificationStatus.VERIFIED

    # Preserve concrete validator evidence for deterministic correction.
    # Only details belonging to this check are forwarded.
    criteria = [check_name]
    for issue in issues:
        issue_code = str(issue.get("code", "")).strip()
        issue_detail = str(issue.get("detail", "")).strip()
        if issue_code in codes and issue_detail:
            criteria.append(issue_detail[:REASON_MAX])

    return VerificationResult(
        task_id=task_id, status=status,
        verification_type=requirement.value,
        criteria=criteria,
        failure_reason=None if verified else (", ".join(codes)[:REASON_MAX]
                                              or "unspecified issue"),
        # Per-check and deterministic. review["score"] is passing-validators /
        # applicable-validators across the whole payload, so a clean code check
        # reported 0.5 confidence when an unrelated diagram failed.
        confidence=1.0 if verified else 0.0,
    )


def verify(
    result: ExecutionResult,
    plan: TaskPlan,
    decision: StrategyDecision,
    artifacts: Optional[Dict[str, str]] = None,
    code_runner: Optional[Callable[[str], dict]] = None,
    review_cache: Optional[Dict[str, dict]] = None,
    proposed_order: Optional[Sequence[str]] = None,
    proposed_order_count: Optional[int] = None,
) -> VerificationReport:
    """Check what execution produced against what Step 5 said would prove it.

    Pure with respect to the cognitive state: nothing is mutated, nothing is
    cached, and a second call on the same inputs gives the same verdict â€” the
    correction stage may re-verify after a retry.

    `code_runner` enables EXECUTION_TEST. Without it that requirement is
    INCONCLUSIVE rather than assumed to pass; runtime_engine's runner is async
    and reaches the network, so wiring it is the caller's decision.
    """
    requirements = [r for r in (decision.verification_requirements or [])
                    if r is not VerificationRequirement.NONE]

    if not requirements:
        return VerificationReport(
            status=VerificationStatus.NOT_REQUIRED,
            summary="no verification was required for this strategy",
        )

    # Only tasks that actually ran can be verified. A denied or cancelled task
    # produced nothing, and verifying nothing would manufacture a verdict.
    executed = [t for t in plan.tasks if t.task_id in set(result.completed_tasks)]

    results: List[VerificationResult] = []
    unverifiable: List[str] = []
    # Recorded at the single point an artefact is read, so a digest cannot be
    # present for something that was never actually looked at.
    digests: Dict[str, str] = {}

    def read(task: PlannedTask) -> Optional[str]:
        artifact = _artifact_for(task, artifacts)
        if artifact is not None:
            digests[task.task_id] = artifact_digest(artifact)
        return artifact

    def cannot(requirement: VerificationRequirement, reason: str,
               task_id: Optional[str] = None,
               criteria: Optional[List[str]] = None) -> None:
        """Record an unanswerable requirement in both places, always together.

        Appending to `results` without appending to `unverifiable` is how a
        required check went missing from the report; one helper makes the two
        impossible to separate.
        """
        results.append(_unchecked(requirement, reason, task_id, criteria))
        entry = f"{requirement.value}: {reason}"
        if entry not in unverifiable:
            unverifiable.append(entry)

    for requirement in requirements:
        if requirement is VerificationRequirement.CONSISTENCY_CHECK:
            if verify_task_order_consistency is None:
                cannot(
                    requirement,
                    "structured consistency adapter is unavailable",
                )
                continue

            consistency_result = verify_task_order_consistency(
                tasks=plan.tasks,
                proposed_order=proposed_order,
                proposed_order_count=proposed_order_count
            )

            results.append(consistency_result)

            if consistency_result.status is VerificationStatus.INCONCLUSIVE:
                entry = (
                    f"{requirement.value}: "
                    f"{consistency_result.failure_reason or 'verification inconclusive'}"
                )
                if entry not in unverifiable:
                    unverifiable.append(entry)

            continue
        if requirement is VerificationRequirement.EXECUTION_TEST:
            if code_runner is None:
                cannot(requirement, _UNBACKED[requirement])
                continue
            if not executed:
                # Previously this fell through the `for task in executed` body
                # and hit `continue`, leaving zero results and an empty
                # unverifiable list â€” the requirement simply vanished.
                cannot(requirement, "no task completed; nothing was executed to test",
                       criteria=["execution"])
                continue
            for task in executed:
                artifact = read(task)
                if artifact is None:
                    cannot(requirement, NO_ARTIFACT, task.task_id, ["execution"])
                    continue
                try:
                    run = code_runner(artifact) or {}
                    ok = str(run.get("status", "")).upper() == "SUCCESS"
                except Exception:
                    ok, run = False, {"status": "ERROR"}
                results.append(VerificationResult(
                    task_id=task.task_id,
                    status=(VerificationStatus.VERIFIED if ok
                            else VerificationStatus.FAILED),
                    verification_type=requirement.value,
                    criteria=["execution"],
                    failure_reason=None if ok else str(run.get("status", "error"))[:REASON_MAX],
                    confidence=1.0 if ok else 0.0,
                ))
            continue

        if requirement is VerificationRequirement.ARITHMETIC_RECHECK:
            if not executed:
                cannot(requirement, "nothing executed to verify",
                       criteria=["arithmetic"])
                continue
            for task in executed:
                artifact = read(task)
                if artifact is None:
                    cannot(requirement, NO_ARTIFACT, task.task_id,
                           ["arithmetic"])
                    continue
                results.append(_arithmetic_check(artifact, task.task_id))
            continue

        if requirement in _UNBACKED:
            cannot(requirement, _UNBACKED[requirement])
            continue

        if requirement not in _REQUIREMENT_TO_CHECK:
            cannot(requirement, "no checker mapped")
            continue

        if not executed:
            cannot(requirement, "nothing executed to verify")
            continue

        check_name = _REQUIREMENT_TO_CHECK[requirement]
        for task in executed:
            artifact = read(task)
            if artifact is None:
                # A truncated digest used to be validated here, which reported
                # FAILED for correct artefacts. Absent evidence is not evidence.
                cannot(requirement, NO_ARTIFACT, task.task_id, [check_name])
                continue
            results.append(_check_result(requirement, _review(artifact, review_cache),
                                          task.task_id))

    status = _aggregate(results)
    verified = sum(1 for r in results if r.status is VerificationStatus.VERIFIED)
    failed = sum(1 for r in results if r.status is VerificationStatus.FAILED)
    inconclusive = sum(1 for r in results if r.status is VerificationStatus.INCONCLUSIVE)

    if status is VerificationStatus.FAILED:
        summary = f"{failed} check(s) failed"
    elif status is VerificationStatus.INCONCLUSIVE:
        summary = f"{inconclusive} check(s) could not be asserted"
    elif status is VerificationStatus.VERIFIED:
        summary = f"{verified} check(s) passed"
    else:
        summary = "nothing verifiable was produced"

    return VerificationReport(
        results=results, status=status,
        verified_count=verified, failed_count=failed, inconclusive_count=inconclusive,
        unverifiable=unverifiable, artifact_digests=digests, summary=summary,
    )

