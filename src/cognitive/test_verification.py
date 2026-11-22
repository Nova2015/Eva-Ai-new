"""Tests for the Verification stage (Step 9).

The load-bearing property: **VERIFIED is never asserted for a check that did
not actually run**. A stage that quietly passes unverifiable work is worse than
no stage at all, because Step 10 would then skip a correction that was needed.

Python code samples are used throughout, which review_engine checks with
ast.parse. JavaScript would invoke `node --check` in a subprocess; one test
covers that path explicitly and is skipped when node is absent.
"""

import shutil
import pytest

try:
    from cognitive.verification import (
        verify, VerificationReport, REVIEW_ENGINE_AVAILABLE, NO_ARTIFACT,
        _STATUS_MAP, _UNBACKED, _REQUIREMENT_TO_CHECK,
    )
    from cognitive.executor import ExecutionResult
    from cognitive.planning import TaskPlan
    from cognitive.strategy import StrategyDecision, VerificationRequirement
    from cognitive.state import (
        PlannedTask, Observation, VerificationStatus, ReasoningStrategy,
    )
except ImportError:  # running from src/cognitive directly
    from verification import (  # type: ignore
        verify, VerificationReport, REVIEW_ENGINE_AVAILABLE, NO_ARTIFACT,
        _STATUS_MAP, _UNBACKED, _REQUIREMENT_TO_CHECK,
    )
    from executor import ExecutionResult  # type: ignore
    from planning import TaskPlan  # type: ignore
    from strategy import StrategyDecision, VerificationRequirement  # type: ignore
    from state import (  # type: ignore
        PlannedTask, Observation, VerificationStatus, ReasoningStrategy,
    )

pytestmark = pytest.mark.skipif(not REVIEW_ENGINE_AVAILABLE,
                                reason="review_engine unavailable on this path")

GOOD_PY = "Here you go:\n```python\ndef f(x):\n    return x[::-1]\n```\n"
BAD_PY = "Here you go:\n```python\ndef f(x)\n    return x\n```\n"      # missing colon
GOOD_MERMAID = "```mermaid\nflowchart TD\n  A[Start] --> B[End]\n```\n"
BAD_MERMAID = "```mermaid\nthis is just prose, not a diagram at all\n```\n"
PLAIN_PROSE = "The capital of France is Paris."


def task(tid=None, objective="do a thing"):
    t = PlannedTask(objective=objective, verification_criteria=["done"])
    if tid:
        t.task_id = tid
    return t


def execution(tasks, summaries=None):
    """An ExecutionResult in which every task completed."""
    summaries = summaries or {}
    return ExecutionResult(
        success=True,
        completed_tasks=[t.task_id for t in tasks],
        observations=[Observation(task_id=t.task_id,
                                  summary=summaries.get(t.task_id, ""))
                      for t in tasks],
    )


def decision(*requirements):
    return StrategyDecision(
        strategy=ReasoningStrategy.CODE,
        verification_requirements=list(requirements) or [VerificationRequirement.NONE],
    )


# ── the core property ────────────────────────────────────────────────────────
def test_valid_code_verifies():
    t = task()
    r = verify(execution([t]), TaskPlan(tasks=[t]),
               decision(VerificationRequirement.CODE_VALIDATION),
               artifacts={t.task_id: GOOD_PY})
    assert r.status is VerificationStatus.VERIFIED
    assert r.verified_count == 1 and r.failed_count == 0


def test_broken_code_fails():
    t = task()
    r = verify(execution([t]), TaskPlan(tasks=[t]),
               decision(VerificationRequirement.CODE_VALIDATION),
               artifacts={t.task_id: BAD_PY})
    assert r.status is VerificationStatus.FAILED
    assert r.failed_count >= 1
    assert "syntax" in (r.results[0].failure_reason or "")


def test_valid_diagram_verifies():
    t = task()
    r = verify(execution([t]), TaskPlan(tasks=[t]),
               decision(VerificationRequirement.DIAGRAM_VALIDATION),
               artifacts={t.task_id: GOOD_MERMAID})
    assert r.status is VerificationStatus.VERIFIED


def test_prose_masquerading_as_a_diagram_fails():
    t = task()
    r = verify(execution([t]), TaskPlan(tasks=[t]),
               decision(VerificationRequirement.DIAGRAM_VALIDATION),
               artifacts={t.task_id: BAD_MERMAID})
    assert r.status is VerificationStatus.FAILED


# ── never assert what was not checked ────────────────────────────────────────
def test_plain_prose_is_not_required_not_verified():
    """review_engine's own rule: nothing verifiable means assert nothing."""
    t = task()
    r = verify(execution([t]), TaskPlan(tasks=[t]),
               decision(VerificationRequirement.CODE_VALIDATION),
               artifacts={t.task_id: PLAIN_PROSE})
    assert r.results[0].status is VerificationStatus.NOT_REQUIRED
    assert r.status is not VerificationStatus.VERIFIED


@pytest.mark.parametrize("requirement", [
    VerificationRequirement.CITATION_CHECK,
    VerificationRequirement.CONSISTENCY_CHECK,
])
def test_unbacked_requirements_are_inconclusive_never_verified(requirement):
    t = task()
    r = verify(execution([t]), TaskPlan(tasks=[t]), decision(requirement),
               artifacts={t.task_id: GOOD_PY})
    assert r.status is VerificationStatus.INCONCLUSIVE
    assert r.unverifiable, "an unbacked requirement must be named, not hidden"
    assert r.verified_count == 0

def test_consistency_check_valid_order_and_count():
    tasks = [
        task("A"),
        task("B"),
        task("C"),
        task("D"),
    ]

    tasks[1].depends_on = ["A"]
    tasks[2].depends_on = ["A"]
    tasks[3].depends_on = ["B", "C"]

    r = verify(
        execution(tasks),
        TaskPlan(tasks=tasks),
        decision(VerificationRequirement.CONSISTENCY_CHECK),
        proposed_order=["A", "B", "C", "D"],
        proposed_order_count=2,
    )

    assert r.status is VerificationStatus.VERIFIED
    assert r.verified_count == 1
    assert r.failed_count == 0


def test_consistency_check_rejects_wrong_order_count():
    tasks = [
        task("A"),
        task("B"),
        task("C"),
        task("D"),
    ]

    tasks[1].depends_on = ["A"]
    tasks[2].depends_on = ["A"]
    tasks[3].depends_on = ["B", "C"]

    r = verify(
        execution(tasks),
        TaskPlan(tasks=tasks),
        decision(VerificationRequirement.CONSISTENCY_CHECK),
        proposed_order=["A", "B", "C", "D"],
        proposed_order_count=6,
    )

    assert r.status is VerificationStatus.FAILED
    assert r.failed_count == 1
    assert "assistant stated 6" in r.results[0].failure_reason

def test_execution_test_without_a_runner_is_inconclusive():
    t = task()
    r = verify(execution([t]), TaskPlan(tasks=[t]),
               decision(VerificationRequirement.EXECUTION_TEST),
               artifacts={t.task_id: GOOD_PY})
    assert r.status is VerificationStatus.INCONCLUSIVE
    assert any("code_runner" in u for u in r.unverifiable)


def test_execution_test_with_an_injected_runner():
    t = task()
    r = verify(execution([t]), TaskPlan(tasks=[t]),
               decision(VerificationRequirement.EXECUTION_TEST),
               artifacts={t.task_id: GOOD_PY},
               code_runner=lambda text: {"status": "SUCCESS"})
    assert r.status is VerificationStatus.VERIFIED


def test_execution_test_runner_failure_is_failed_not_inconclusive():
    t = task()
    r = verify(execution([t]), TaskPlan(tasks=[t]),
               decision(VerificationRequirement.EXECUTION_TEST),
               artifacts={t.task_id: GOOD_PY},
               code_runner=lambda text: {"status": "RUNTIME_ERROR"})
    assert r.status is VerificationStatus.FAILED


def test_execution_test_runner_raising_is_failed():
    def boom(_):
        raise RuntimeError("piston unreachable")
    t = task()
    r = verify(execution([t]), TaskPlan(tasks=[t]),
               decision(VerificationRequirement.EXECUTION_TEST),
               artifacts={t.task_id: GOOD_PY}, code_runner=boom)
    assert r.status is VerificationStatus.FAILED


# ── aggregation ──────────────────────────────────────────────────────────────
def test_failure_dominates_a_pass():
    a, b = task(), task()
    r = verify(execution([a, b]), TaskPlan(tasks=[a, b]),
               decision(VerificationRequirement.CODE_VALIDATION),
               artifacts={a.task_id: GOOD_PY, b.task_id: BAD_PY})
    assert r.status is VerificationStatus.FAILED
    assert r.verified_count == 1 and r.failed_count == 1


def test_inconclusive_beats_verified():
    t = task()
    r = verify(execution([t]), TaskPlan(tasks=[t]),
               decision(VerificationRequirement.CODE_VALIDATION,
                        VerificationRequirement.CITATION_CHECK),
               artifacts={t.task_id: GOOD_PY})
    assert r.verified_count >= 1
    assert r.status is VerificationStatus.INCONCLUSIVE, \
        "an unrunnable check must stop the whole report reading VERIFIED"


def test_no_requirements_is_not_required():
    t = task()
    r = verify(execution([t]), TaskPlan(tasks=[t]), decision())
    assert r.status is VerificationStatus.NOT_REQUIRED
    assert r.results == []


# ── only what actually ran is verified ───────────────────────────────────────
def test_a_task_that_did_not_complete_is_not_verified():
    t = task()
    empty = ExecutionResult(success=False, completed_tasks=[], failed_tasks=[t.task_id])
    r = verify(empty, TaskPlan(tasks=[t]),
               decision(VerificationRequirement.CODE_VALIDATION),
               artifacts={t.task_id: GOOD_PY})
    assert r.status is VerificationStatus.INCONCLUSIVE
    assert r.verified_count == 0, "verifying work that never ran manufactures a verdict"


def test_observation_summary_is_never_validated_as_an_artefact():
    """This test previously asserted the opposite, and that was the defect.

    A summary short enough to survive Step 2's scrubber looks like a working
    fallback, which is exactly why it shipped — the same code path truncates
    anything real. A digest is not the artefact at any length.
    """
    t = task()
    r = verify(execution([t], {t.task_id: GOOD_PY}), TaskPlan(tasks=[t]),
               decision(VerificationRequirement.CODE_VALIDATION))
    assert r.status is VerificationStatus.INCONCLUSIVE
    assert r.verified_count == 0
    assert any(NO_ARTIFACT in u for u in r.unverifiable)


# ── the status mapping ───────────────────────────────────────────────────────
def test_status_map_never_turns_a_warning_into_a_pass():
    assert _STATUS_MAP["WARNING"] is VerificationStatus.INCONCLUSIVE
    assert _STATUS_MAP["UNKNOWN"] is VerificationStatus.INCONCLUSIVE
    assert _STATUS_MAP["FAILED"] is VerificationStatus.FAILED
    assert _STATUS_MAP["VALID"] is VerificationStatus.VERIFIED
    assert _STATUS_MAP[None] is VerificationStatus.NOT_REQUIRED


def test_a_crashed_validator_is_inconclusive_not_verified():
    """run_review_pipeline is fail-open (valid=True on crash) because review is
    observational. Verification must not inherit that optimism."""
    import cognitive.verification as v
    t = task()
    original = v.run_review_pipeline
    v.run_review_pipeline = lambda text, mode="standard", **kw: {
        "valid": True, "score": None, "issues": [],
        "checks": {"code": {"applicable": True, "passed": True, "issues": []}},
        "review_meta": {"error": "ValidatorExploded"},
    }
    try:
        r = verify(execution([t]), TaskPlan(tasks=[t]),
                   decision(VerificationRequirement.CODE_VALIDATION),
                   artifacts={t.task_id: GOOD_PY})
    finally:
        v.run_review_pipeline = original
    assert r.status is VerificationStatus.INCONCLUSIVE
    assert "validator error" in (r.results[0].failure_reason or "")


def test_review_engine_absent_is_inconclusive():
    import cognitive.verification as v
    t = task()
    original = v.run_review_pipeline
    v.run_review_pipeline = None
    try:
        r = verify(execution([t]), TaskPlan(tasks=[t]),
                   decision(VerificationRequirement.CODE_VALIDATION),
                   artifacts={t.task_id: GOOD_PY})
    finally:
        v.run_review_pipeline = original
    assert r.status is VerificationStatus.INCONCLUSIVE


# ── boundaries ───────────────────────────────────────────────────────────────
def test_no_validators_are_reimplemented():
    import io, os
    src = io.open(os.path.join(os.path.dirname(__file__), "verification.py"),
                  encoding="utf-8").read()
    for owned_by_review_engine in ("def validate_code", "def validate_charts",
                                   "def validate_mermaid", "FATAL_CODES ="):
        assert owned_by_review_engine not in src


def test_no_correction_or_learning_here():
    banned = {"correct", "retry", "replan", "learn", "learning_candidates", "answer"}
    assert banned.isdisjoint(VerificationReport.model_fields.keys())


def test_no_network_or_provider_imports():
    import ast, io, os
    tree = ast.parse(io.open(os.path.join(os.path.dirname(__file__), "verification.py"),
                             encoding="utf-8").read())
    imports = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imports |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            imports.add(n.module or "")
    forbidden = ("httpx", "requests", "urllib", "socket", "openai", "groq",
                 "boto3", "aiohttp", "psycopg2")
    assert not [i for i in imports if any(f in i for f in forbidden)]


def test_verification_does_not_mutate_the_plan_or_result():
    t = task()
    ex = execution([t])
    plan = TaskPlan(tasks=[t])
    before_task = t.model_dump()
    before_result = ex.model_dump()
    verify(ex, plan, decision(VerificationRequirement.CODE_VALIDATION),
           artifacts={t.task_id: GOOD_PY})
    assert t.model_dump() == before_task
    assert ex.model_dump() == before_result


def test_repeatable():
    t = task()
    ex, plan, d = execution([t]), TaskPlan(tasks=[t]), decision(VerificationRequirement.CODE_VALIDATION)
    a = verify(ex, plan, d, artifacts={t.task_id: GOOD_PY})
    b = verify(ex, plan, d, artifacts={t.task_id: GOOD_PY})
    assert a.status is b.status and a.verified_count == b.verified_count


def test_secrets_are_not_stored_in_the_report():
    key = "sk-abcdefghijklmnop1234567890"
    t = task()
    r = verify(execution([t]), TaskPlan(tasks=[t]),
               decision(VerificationRequirement.CODE_VALIDATION),
               artifacts={t.task_id: f"```python\ndef f() # broken {key}\n```"})
    assert key not in r.model_dump_json()


def test_results_are_addressable_per_task():
    a, b = task(), task()
    r = verify(execution([a, b]), TaskPlan(tasks=[a, b]),
               decision(VerificationRequirement.CODE_VALIDATION),
               artifacts={a.task_id: GOOD_PY, b.task_id: BAD_PY})
    assert len(r.results_for(a.task_id)) == 1
    assert r.results_for(a.task_id)[0].status is VerificationStatus.VERIFIED
    assert r.results_for(b.task_id)[0].status is VerificationStatus.FAILED


# ── the subprocess path, acknowledged explicitly ─────────────────────────────
@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_javascript_path_uses_node_and_still_classifies():
    """review_engine shells out to `node --check` for JS. Pre-existing and
    guarded, but it means verification is not a pure function."""
    t = task()
    r = verify(execution([t]), TaskPlan(tasks=[t]),
               decision(VerificationRequirement.CODE_VALIDATION),
               artifacts={t.task_id: "```javascript\nfunction f( { return 1\n```"})
    assert r.status in (VerificationStatus.FAILED, VerificationStatus.INCONCLUSIVE)


# ═══════════════════════════════════════════════════════════════════════════
# STEP 9 FIX — the four reviewed defects
#
# The review found that a truncated summary was validated as an artefact, that
# per-check verdicts and confidence were taken from whole-payload fields, and
# that a required EXECUTION_TEST could vanish from the report. These pin the
# corrected behaviour.
# ═══════════════════════════════════════════════════════════════════════════

# Comfortably past REASON_MAX (400) — the size every real code artefact has.
LONG_PY = ("Here is the module you asked for:\n```python\n"
           + "\n".join(f"value_{i} = {i}" for i in range(200))
           + "\n```\n")

# One artefact, two validators: the code block only warns, the diagram is fatal.
JS_WARN = "```javascript\nfunction f( {\n```"
JS_WARN_PLUS_FATAL_DIAGRAM = JS_WARN + "\n\n" + BAD_MERMAID
GOOD_PY_PLUS_FATAL_DIAGRAM = GOOD_PY + "\n" + BAD_MERMAID
BAD_PY_PLUS_GOOD_DIAGRAM = BAD_PY + "\n" + GOOD_MERMAID


def _one(text, requirement, tid="a"):
    """verify() over a single completed task carrying `text` as its artefact."""
    t = task(tid)
    return verify(execution([t]), TaskPlan(tasks=[t]), decision(requirement),
                  artifacts={t.task_id: text})


# ── D1: a truncated digest is never validated ────────────────────────────────
def test_fix_long_valid_code_without_artifacts_is_inconclusive_not_failed():
    """The headline defect: 200 lines of valid Python reported FAILED because
    Step 2 cut the summary at 400 chars and the cut landed inside the fence."""
    t = task()
    r = verify(execution([t], {t.task_id: LONG_PY}), TaskPlan(tasks=[t]),
               decision(VerificationRequirement.CODE_VALIDATION))
    assert r.status is VerificationStatus.INCONCLUSIVE
    assert r.failed_count == 0, "absent evidence must never read as FAILED"
    assert r.verified_count == 0
    assert any(NO_ARTIFACT in u for u in r.unverifiable)


def test_fix_the_truncation_that_caused_it_is_real():
    """Guards the premise: if summary ever stopped truncating, the test above
    would pass for the wrong reason."""
    from cognitive.state import REASON_MAX
    obs = Observation(task_id="a", summary=LONG_PY)
    assert len(LONG_PY) > REASON_MAX
    assert len(obs.summary) == REASON_MAX
    assert not obs.summary.rstrip().endswith("`" * 3), "the fence is cut open"


def test_fix_truncated_digest_would_have_validated_as_broken():
    """What the old fallback fed the validator, checked directly."""
    from cognitive.verification import _review
    review = _review(Observation(task_id="a", summary=LONG_PY).summary)
    codes = [i.get("code") for i in review["issues"]]
    assert "unclosed_fence" in codes, "this is the false FAILED that shipped"


def test_fix_explicit_artifact_still_verifies_at_any_length():
    r = _one(LONG_PY, VerificationRequirement.CODE_VALIDATION)
    assert r.status is VerificationStatus.VERIFIED


def test_fix_empty_artifact_is_inconclusive_not_verified():
    t = task()
    r = verify(execution([t]), TaskPlan(tasks=[t]),
               decision(VerificationRequirement.CODE_VALIDATION),
               artifacts={t.task_id: "   "})
    assert r.status is VerificationStatus.INCONCLUSIVE
    assert any(NO_ARTIFACT in u for u in r.unverifiable)


# ── D2: one check's issues decide one check's verdict ────────────────────────
def test_fix_code_warn_plus_fatal_diagram_is_inconclusive_not_failed():
    alone = _one(JS_WARN, VerificationRequirement.CODE_VALIDATION)
    mixed = _one(JS_WARN_PLUS_FATAL_DIAGRAM, VerificationRequirement.CODE_VALIDATION)
    assert alone.status is VerificationStatus.INCONCLUSIVE
    assert mixed.status is VerificationStatus.INCONCLUSIVE, \
        "a fatal mermaid defect must not make CODE_VALIDATION FAILED"
    assert mixed.results[0].failure_reason == alone.results[0].failure_reason


def test_fix_clean_code_plus_fatal_diagram_still_verifies():
    assert _one(GOOD_PY_PLUS_FATAL_DIAGRAM,
                VerificationRequirement.CODE_VALIDATION).status \
        is VerificationStatus.VERIFIED


def test_fix_fatal_code_is_still_failed():
    r = _one(BAD_PY, VerificationRequirement.CODE_VALIDATION)
    assert r.status is VerificationStatus.FAILED
    assert "python_syntax_error" in (r.results[0].failure_reason or "")


def test_fix_fatal_code_does_not_contaminate_the_diagram_verdict():
    r = _one(BAD_PY_PLUS_GOOD_DIAGRAM, VerificationRequirement.DIAGRAM_VALIDATION)
    assert r.status is VerificationStatus.VERIFIED, \
        "a broken code block says nothing about a valid diagram"


def test_fix_a_checks_verdict_is_invariant_to_every_other_check():
    """The general property, not one instance of it.

    JS_WARN is deliberately absent: a javascript block is checked by `code`,
    the same check under test, so appending it would change the verdict
    legitimately. Only genuinely other checks belong here.
    """
    others = ("", "\n" + BAD_MERMAID, "\n" + GOOD_MERMAID,
              "\nHere is a bar chart of the results.")   # chart: claim_without_block
    for extra in others:
        r = _one(GOOD_PY + extra, VerificationRequirement.CODE_VALIDATION)
        assert r.status is VerificationStatus.VERIFIED, f"changed by: {extra!r}"
        assert r.results[0].confidence == 1.0, f"confidence changed by: {extra!r}"


def _executable_source(module_name):
    """Module source with docstrings and comments removed.

    Scanning raw text finds the words in the very comments that explain why
    they are NOT used — the same false positive that made a Step 7 check and a
    Step 8 check pass for the wrong reason.
    """
    import ast, io, os
    src = io.open(os.path.join(os.path.dirname(__file__), module_name),
                  encoding="utf-8").read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                              ast.AsyncFunctionDef))
                and ast.get_docstring(node) is not None):
            node.body = node.body[1:] or [ast.Pass()]
    return ast.unparse(ast.fix_missing_locations(tree))


def test_fix_severity_vocabulary_is_not_duplicated():
    """FATAL_CODES/WARN_CODES stay review_engine's. Narrowing the payload is
    what makes per-check severity possible without a second copy."""
    src = _executable_source("verification.py")
    for owned_by_review_engine in ("FATAL_CODES", "WARN_CODES", "unclosed_fence",
                                   "python_syntax_error", "missing_diagram_type",
                                   "js_syntax_error"):
        assert owned_by_review_engine not in src, \
            f"{owned_by_review_engine} is review_engine's to define"


def test_fix_the_source_scan_can_actually_fail():
    """A scan that cannot fail proves nothing — Step 8's grep-based coverage
    check read 'covered' for every row because of exactly this gap."""
    import io, os
    assert "derive_status" in _executable_source("verification.py"), \
        "the scan is not reading real code"
    raw = io.open(os.path.join(os.path.dirname(__file__), "verification.py"),
                  encoding="utf-8").read()
    assert "FATAL_CODES" in raw, \
        "the prose does name it; stripping docstrings is what makes the check above pass"


# ── D3: a required EXECUTION_TEST always appears ─────────────────────────────
def _exec_test(exec_result, tasks, runner, artifacts=None):
    return verify(exec_result, TaskPlan(tasks=tasks),
                  decision(VerificationRequirement.EXECUTION_TEST),
                  artifacts=artifacts, code_runner=runner)


def test_fix_runner_with_zero_executed_tasks_is_inconclusive():
    t = task()
    r = _exec_test(ExecutionResult(completed_tasks=[]), [t],
                   lambda s: {"status": "SUCCESS"})
    assert r.status is VerificationStatus.INCONCLUSIVE, "was NOT_REQUIRED"
    assert len(r.results) == 1, "the requirement used to vanish entirely"
    assert r.unverifiable, "and left no trace in unverifiable"


def test_fix_runner_with_cancelled_task_does_not_verify_it():
    t = task()
    r = _exec_test(ExecutionResult(completed_tasks=[], cancelled_tasks=[t.task_id]),
                   [t], lambda s: {"status": "SUCCESS"})
    assert r.status is VerificationStatus.INCONCLUSIVE
    assert r.verified_count == 0, "a cancelled task produced nothing to test"


def test_fix_runner_with_failed_task_does_not_verify_it():
    t = task()
    r = _exec_test(ExecutionResult(completed_tasks=[], failed_tasks=[t.task_id]),
                   [t], lambda s: {"status": "SUCCESS"})
    assert r.status is VerificationStatus.INCONCLUSIVE
    assert r.verified_count == 0


def test_fix_runner_with_successful_task_verifies():
    t = task()
    r = _exec_test(execution([t]), [t], lambda s: {"status": "SUCCESS"},
                   artifacts={t.task_id: GOOD_PY})
    assert r.status is VerificationStatus.VERIFIED
    assert r.verified_count == 1


def test_fix_execution_test_without_an_artifact_is_inconclusive():
    t = task()
    r = _exec_test(execution([t]), [t], lambda s: {"status": "SUCCESS"})
    assert r.status is VerificationStatus.INCONCLUSIVE
    assert any(NO_ARTIFACT in u for u in r.unverifiable)


def test_fix_every_unanswerable_requirement_is_listed():
    """results and unverifiable move together — D3 was them coming apart."""
    for req in VerificationRequirement:
        if req is VerificationRequirement.NONE:
            continue
        t = task()
        r = verify(ExecutionResult(completed_tasks=[]), TaskPlan(tasks=[t]),
                   decision(req), code_runner=lambda s: {"status": "SUCCESS"})
        assert r.results, f"{req.value} produced no result at all"
        assert r.unverifiable, f"{req.value} left unverifiable empty"
        assert r.verified_count == 0


# ── D4: confidence is per-check ──────────────────────────────────────────────
def test_fix_unrelated_failure_does_not_reduce_confidence():
    clean = _one(GOOD_PY, VerificationRequirement.CODE_VALIDATION)
    mixed = _one(GOOD_PY_PLUS_FATAL_DIAGRAM, VerificationRequirement.CODE_VALIDATION)
    assert clean.results[0].confidence == 1.0
    assert mixed.results[0].confidence == 1.0, \
        "aggregate review.score reported 0.5 here"


def test_fix_code_failure_does_not_affect_diagram_confidence():
    r = _one(BAD_PY_PLUS_GOOD_DIAGRAM, VerificationRequirement.DIAGRAM_VALIDATION)
    assert r.results[0].confidence == 1.0


def test_fix_confidence_is_bounded_and_zero_unless_verified():
    for text in (GOOD_PY, BAD_PY, JS_WARN, PLAIN_PROSE, LONG_PY,
                 GOOD_PY_PLUS_FATAL_DIAGRAM):
        for req in (VerificationRequirement.CODE_VALIDATION,
                    VerificationRequirement.DIAGRAM_VALIDATION,
                    VerificationRequirement.CHART_VALIDATION):
            for result in _one(text, req).results:
                assert 0.0 <= result.confidence <= 1.0
                if result.status is not VerificationStatus.VERIFIED:
                    assert result.confidence == 0.0


def test_fix_aggregate_score_is_no_longer_read():
    import io, os
    src = io.open(os.path.join(os.path.dirname(__file__), "verification.py"),
                  encoding="utf-8").read()
    assert 'review.get("score")' not in src


# ── the fail-open guard the review exposed as unreachable ────────────────────
def test_fix_a_real_crashed_pipeline_is_inconclusive():
    """The existing crash test hand-built a payload with an applicable check, a
    shape run_review_pipeline never emits: on a crash it returns checks={}. The
    `applicable` test ran first, so that read as NOT_REQUIRED and the guard
    below it could not fire on any real payload."""
    import cognitive.verification as v
    t = task()
    original = v.run_review_pipeline
    v.run_review_pipeline = lambda text, mode="standard", **kw: {
        "valid": True, "score": None, "issues": [], "checks": {},
        "review_meta": {"error": "ValidatorExploded"},
    }
    try:
        r = verify(execution([t]), TaskPlan(tasks=[t]),
                   decision(VerificationRequirement.CODE_VALIDATION),
                   artifacts={t.task_id: GOOD_PY})
    finally:
        v.run_review_pipeline = original
    assert r.status is VerificationStatus.INCONCLUSIVE, "was NOT_REQUIRED"
    assert "validator error" in (r.results[0].failure_reason or "")


# ── artefact provenance ──────────────────────────────────────────────────────
# A report that cannot say WHICH artefact it read cannot be checked for
# staleness by anything downstream. Step 12 could previously only confirm that
# an ActResult and a report mentioned the same TASK — which a pre-correction
# report also satisfies, because only the content differs.

SECRET_PY = "```python\ntoken = 'sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345'\n```"


def test_a_verified_artefact_is_fingerprinted():
    from cognitive.verification import artifact_digest
    t = task()
    r = verify(execution([t]), TaskPlan(tasks=[t]),
               decision(VerificationRequirement.CODE_VALIDATION),
               artifacts={t.task_id: GOOD_PY})
    assert r.artifact_digests[t.task_id] == artifact_digest(GOOD_PY)


def test_different_artefacts_fingerprint_differently():
    from cognitive.verification import artifact_digest
    assert artifact_digest(GOOD_PY) != artifact_digest(BAD_PY)
    # The pair that matters: one closing fence apart.
    open_fence = "Here:\n```python\ndef f(x):\n    return x\n"
    assert artifact_digest(open_fence) != artifact_digest(open_fence + "```")


def test_the_fingerprint_is_stable():
    from cognitive.verification import artifact_digest
    assert artifact_digest(GOOD_PY) == artifact_digest(GOOD_PY)
    assert artifact_digest("") == artifact_digest(None)


def test_the_fingerprint_is_not_the_artefact():
    """It travels in a structure meant to be logged; the artefact must not."""
    from cognitive.verification import artifact_digest, DIGEST_CHARS
    digest = artifact_digest(GOOD_PY)
    assert len(digest) == DIGEST_CHARS
    assert "def f" not in digest
    assert all(c in "0123456789abcdef" for c in digest)


def test_a_secret_in_an_artefact_does_not_reach_the_report():
    t = task()
    r = verify(execution([t]), TaskPlan(tasks=[t]),
               decision(VerificationRequirement.CODE_VALIDATION),
               artifacts={t.task_id: SECRET_PY})
    assert "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345" not in r.model_dump_json()
    assert r.artifact_digests[t.task_id], "but provenance is still recorded"


def test_no_fingerprint_when_no_artefact_was_read():
    """Absence is meaningful: it means no verdict about content."""
    t = task()
    r = verify(execution([t]), TaskPlan(tasks=[t]),
               decision(VerificationRequirement.CODE_VALIDATION))
    assert r.artifact_digests == {}
    assert r.status is VerificationStatus.INCONCLUSIVE


def test_a_settled_verdict_always_carries_a_fingerprint():
    """The property Step 12 leans on: VERIFIED or FAILED implies an artefact
    was read, so provenance is available wherever a verdict exists."""
    for text in (GOOD_PY, BAD_PY, GOOD_MERMAID, BAD_MERMAID, PLAIN_PROSE):
        t = task()
        r = verify(execution([t]), TaskPlan(tasks=[t]),
                   decision(VerificationRequirement.CODE_VALIDATION,
                            VerificationRequirement.DIAGRAM_VALIDATION),
                   artifacts={t.task_id: text})
        for result in r.results:
            if result.status in (VerificationStatus.VERIFIED,
                                 VerificationStatus.FAILED):
                assert result.task_id in r.artifact_digests, repr(text[:30])


def test_execution_test_artefacts_are_fingerprinted_too():
    from cognitive.verification import artifact_digest
    t = task()
    r = verify(execution([t]), TaskPlan(tasks=[t]),
               decision(VerificationRequirement.EXECUTION_TEST),
               artifacts={t.task_id: GOOD_PY},
               code_runner=lambda text: {"status": "SUCCESS"})
    assert r.artifact_digests[t.task_id] == artifact_digest(GOOD_PY)


def test_fingerprints_are_per_task():
    from cognitive.verification import artifact_digest
    a, b = task(), task()
    r = verify(execution([a, b]), TaskPlan(tasks=[a, b]),
               decision(VerificationRequirement.CODE_VALIDATION),
               artifacts={a.task_id: GOOD_PY, b.task_id: BAD_PY})
    assert r.artifact_digests[a.task_id] == artifact_digest(GOOD_PY)
    assert r.artifact_digests[b.task_id] == artifact_digest(BAD_PY)


def test_recording_a_fingerprint_changes_no_verdict():
    """Provenance is additive. The verdicts are what they always were."""
    for text, expected in ((GOOD_PY, VerificationStatus.VERIFIED),
                           (BAD_PY, VerificationStatus.FAILED),
                           (PLAIN_PROSE, VerificationStatus.NOT_REQUIRED)):
        t = task()
        r = verify(execution([t]), TaskPlan(tasks=[t]),
                   decision(VerificationRequirement.CODE_VALIDATION),
                   artifacts={t.task_id: text})
        assert r.results[0].status is expected


def test_a_digest_is_recorded_only_where_an_artefact_was_read():
    """Two tasks, one artefact: the other must not acquire a fingerprint."""
    a, b = task(), task()
    r = verify(execution([a, b]), TaskPlan(tasks=[a, b]),
               decision(VerificationRequirement.CODE_VALIDATION),
               artifacts={a.task_id: GOOD_PY})
    assert a.task_id in r.artifact_digests
    assert b.task_id not in r.artifact_digests
    assert any(NO_ARTIFACT in u for u in r.unverifiable)


# ── Update 14: capability discovery ──────────────────────────────────────────
# What this runtime can actually execute, as opposed to what would prove an
# answer right. A constant would hard-code one caller's limitations into every
# caller's, so it is a function of the context it is asked about.

def test_the_three_backed_checks_are_available():
    from cognitive.verification import available_requirements
    assert available_requirements() == {
        VerificationRequirement.CODE_VALIDATION,
        VerificationRequirement.CHART_VALIDATION,
        VerificationRequirement.DIAGRAM_VALIDATION,
        VerificationRequirement.ARITHMETIC_RECHECK,
    }

def test_execution_test_appears_only_with_a_runner():
    from cognitive.verification import available_requirements
    assert VerificationRequirement.EXECUTION_TEST not in available_requirements()
    with_runner = available_requirements(code_runner=lambda text: {"status": "SUCCESS"})
    assert VerificationRequirement.EXECUTION_TEST in with_runner


def test_capability_matches_what_step_9_can_actually_run():
    """Step 9-backed validators plus the independent arithmetic validator."""
    from cognitive.verification import available_requirements
    assert available_requirements() == (
        frozenset(_REQUIREMENT_TO_CHECK)
        | {VerificationRequirement.ARITHMETIC_RECHECK}
    )

def test_nothing_unbacked_is_ever_claimed_available():
    from cognitive.verification import available_requirements
    everything = available_requirements(
        code_runner=lambda t: {"status": "SUCCESS"}
    )
    for requirement in (
        VerificationRequirement.CITATION_CHECK,
        VerificationRequirement.CONSISTENCY_CHECK,
    ):
        assert requirement not in everything, requirement.value

def test_no_validators_means_no_capability():
    """Review-engine validators disappear; arithmetic remains independently backed."""
    import cognitive.verification as v
    original = v.REVIEW_ENGINE_AVAILABLE
    v.REVIEW_ENGINE_AVAILABLE = False
    try:
        assert v.available_requirements() == {
            VerificationRequirement.ARITHMETIC_RECHECK
        }
        assert v.available_requirements(
            code_runner=lambda t: {"status": "SUCCESS"}
        ) == {
            VerificationRequirement.ARITHMETIC_RECHECK,
            VerificationRequirement.EXECUTION_TEST,
        }
    finally:
        v.REVIEW_ENGINE_AVAILABLE = original

def test_capability_is_a_function_not_a_constant():
    """Two different contexts must be able to give two different answers."""
    from cognitive.verification import available_requirements
    assert available_requirements() != available_requirements(
        code_runner=lambda t: {"status": "SUCCESS"})


def test_the_returned_set_cannot_be_mutated_by_a_caller():
    from cognitive.verification import available_requirements
    first = available_requirements()
    assert isinstance(first, frozenset)
    assert available_requirements() == first
