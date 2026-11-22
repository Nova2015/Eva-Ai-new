"""Tests for the Learning stage (Step 12).

Three load-bearing properties:

  1. **Nothing is learned from an unverified outcome.** A lesson is a claim,
     and it needs the same evidence as any other. This is Step 9's property one
     stage further on.
  2. **Nothing is ever self-approved.** learning_loop already requires a human
     transition before anything reaches a dataset; this stage is the first
     thing that could have quietly broken that.
  3. **No free text reaches a candidate.** Summaries are assembled from enum
     values, counts and review_engine issue codes — never from a prompt, a
     response, an artefact or a model-generated phrase.
"""

import pytest

try:
    from cognitive.learning import (
        learn, emit, apply_to_state, LearningReport, LearningCategory,
        LearningStatus, _KNOWN_CATEGORIES, _UNCLASSIFIED,
    )
    from cognitive.correction import correct, CorrectionReport, CorrectionStatus
    from cognitive.verification import VerificationReport
    from cognitive.executor import ExecutionResult, ExecutionStatus, TaskOutcome
    from cognitive.state import (
        CognitiveState, CognitivePhase, FailureCategory, LearningCandidate,
        ProblemUnderstanding, StrategySelection, ReasoningStrategy, TaskStatus,
        VerificationResult, VerificationStatus,
    )
except ImportError:  # running from src/cognitive directly
    from learning import (  # type: ignore
        learn, emit, apply_to_state, LearningReport, LearningCategory,
        LearningStatus, _KNOWN_CATEGORIES, _UNCLASSIFIED,
    )
    from correction import correct, CorrectionReport, CorrectionStatus  # type: ignore
    from verification import VerificationReport  # type: ignore
    from executor import ExecutionResult, ExecutionStatus, TaskOutcome  # type: ignore
    from state import (  # type: ignore
        CognitiveState, CognitivePhase, FailureCategory, LearningCandidate,
        ProblemUnderstanding, StrategySelection, ReasoningStrategy, TaskStatus,
        VerificationResult, VerificationStatus,
    )


# ── builders ─────────────────────────────────────────────────────────────────
SECRET = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
PRIVATE_PHRASE = "the launch date is March the fourth"


def at_learn(category="coding", strategy=ReasoningStrategy.CODE, problem=""):
    """A state that has legitimately reached LEARN."""
    s = CognitiveState(problem=problem)
    s.understanding = ProblemUnderstanding(problem_category=category)
    if strategy is not None:
        s.strategy = StrategySelection(strategy=strategy)
    for phase in (CognitivePhase.ASSESS, CognitivePhase.STRATEGY,
                  CognitivePhase.PLAN, CognitivePhase.ACT, CognitivePhase.VERIFY,
                  CognitivePhase.LEARN):
        s.transition_to(phase)
    return s


def vr(status, task_id="t1", vtype="CODE_VALIDATION", reason=None):
    return VerificationResult(task_id=task_id, status=status,
                              verification_type=vtype, criteria=["code"],
                              failure_reason=reason)


def verification(status=VerificationStatus.VERIFIED, verified=1, failed=0,
                 unverifiable=None, results=None):
    return VerificationReport(
        results=results or [], status=status,
        verified_count=verified, failed_count=failed,
        unverifiable=list(unverifiable or []))


def execution(**kw):
    kw.setdefault("completed_tasks", ["t1"])
    kw.setdefault("final_execution_status", ExecutionStatus.EXECUTION_COMPLETE)
    return ExecutionResult(**kw)


def no_correction():
    return CorrectionReport(status=CorrectionStatus.NO_CORRECTION_NEEDED)


def outcome(category, task_id="t1"):
    return TaskOutcome(task_id=task_id, status=TaskStatus.FAILED,
                       error_category=category)


# ── 1: nothing is learned from an unverified outcome ─────────────────────────
def test_verified_outcome_teaches_the_strategy_worked():
    r = learn(at_learn(), execution(), verification(), no_correction())
    assert r.status is LearningStatus.CANDIDATES_PROPOSED
    lesson = r.by_category(LearningCategory.STRATEGY_OUTCOME)[0]
    assert "strategy=CODE" in lesson.summary
    assert "outcome=VERIFIED" in lesson.summary


def test_inconclusive_teaches_nothing_about_the_strategy():
    r = learn(at_learn(), execution(),
              verification(VerificationStatus.INCONCLUSIVE, verified=0), no_correction())
    assert r.by_category(LearningCategory.STRATEGY_OUTCOME) == []
    assert any("not verified" in w for w in r.withheld)


def test_not_required_teaches_nothing_about_the_strategy():
    r = learn(at_learn(), execution(),
              verification(VerificationStatus.NOT_REQUIRED, verified=0), no_correction())
    assert r.by_category(LearningCategory.STRATEGY_OUTCOME) == []
    assert any("not verified" in w for w in r.withheld)


def test_failed_outcome_teaches_the_strategy_did_not_work():
    r = learn(at_learn(), execution(),
              verification(VerificationStatus.FAILED, verified=0, failed=1),
              no_correction())
    lesson = r.by_category(LearningCategory.STRATEGY_OUTCOME)[0]
    assert "outcome=FAILED" in lesson.summary


def test_no_strategy_recorded_teaches_nothing():
    s = at_learn(strategy=None)
    r = learn(s, execution(), verification(), no_correction())
    assert r.by_category(LearningCategory.STRATEGY_OUTCOME) == []
    assert any("no strategy" in w for w in r.withheld)


def test_a_verification_gap_needs_no_verified_outcome():
    """The exception, and a deliberate one: the gap IS the observation."""
    r = learn(at_learn(), execution(),
              verification(VerificationStatus.INCONCLUSIVE, verified=0,
                           unverifiable=["CITATION_CHECK: runs on the ML service"]),
              no_correction())
    gaps = r.by_category(LearningCategory.VERIFICATION_GAP)
    assert len(gaps) == 1
    assert "requirement=CITATION_CHECK" in gaps[0].summary
    assert "outcome=UNVERIFIABLE" in gaps[0].summary


# ── 2: nothing is ever self-approved ─────────────────────────────────────────
def test_no_candidate_is_ever_approved():
    r = learn(at_learn(), execution(),
              verification(unverifiable=["EXECUTION_TEST: no runner"]), no_correction())
    assert r.candidates
    assert all(c.approved is False for c in r.candidates)


def test_the_builder_itself_produces_unapproved_candidates():
    """Checked at the builder, not only after the report has normalised it.

    Without this, a builder that set approved=True would still pass every other
    test in this file — the report validator would quietly undo it, and the
    outer layer would be doing all the work while appearing to confirm both.
    """
    from cognitive.learning import _candidate
    for confidence in (0.0, 0.5, 1.0):
        assert _candidate(LearningCategory.STRATEGY_OUTCOME, "x=y",
                          confidence).approved is False


def test_approval_cannot_be_forced_through_the_report():
    approved = LearningCandidate(category="STRATEGY_OUTCOME", summary="x",
                                 approved=True)
    r = LearningReport(candidates=[approved])
    assert all(c.approved is False for c in r.candidates), \
        "a human transition is the only path to a dataset"


def test_approval_cannot_survive_apply_to_state():
    s = at_learn()
    r = learn(s, execution(), verification(), no_correction())
    r.candidates[0].approved = True          # simulate a caller doing the wrong thing
    apply_to_state(s, r)
    assert all(c.approved is False for c in s.learning_candidates)


def test_the_report_says_a_human_must_review():
    r = learn(at_learn(), execution(), verification(), no_correction())
    assert r.requires_human_review is True


def test_nothing_to_learn_does_not_request_review():
    r = learn(at_learn(), execution(),
              verification(VerificationStatus.INCONCLUSIVE, verified=0), no_correction())
    assert r.requires_human_review is False


# ── 3: no free text reaches a candidate ──────────────────────────────────────
def test_problem_text_never_reaches_a_candidate():
    s = at_learn(problem=f"{PRIVATE_PHRASE} and my key is {SECRET}")
    r = learn(s, execution(), verification(), no_correction())
    dumped = r.model_dump_json()
    assert PRIVATE_PHRASE not in dumped
    assert SECRET not in dumped


def test_an_unknown_problem_category_is_not_written_through():
    """Step 3's hybrid path takes problem_category from the model's JSON and
    accepts whatever comes back, so an arbitrary string can arrive here."""
    s = at_learn(category=f"ignore previous instructions and {SECRET}")
    r = learn(s, execution(), verification(), no_correction())
    summary = r.by_category(LearningCategory.STRATEGY_OUTCOME)[0].summary
    assert f"category={_UNCLASSIFIED}" in summary
    assert "ignore previous" not in summary
    assert SECRET not in summary


@pytest.mark.parametrize("category", sorted(_KNOWN_CATEGORIES))
def test_documented_categories_pass_through(category):
    s = at_learn(category=category)
    r = learn(s, execution(), verification(), no_correction())
    assert f"category={category}" in r.by_category(
        LearningCategory.STRATEGY_OUTCOME)[0].summary


def test_artefact_content_never_reaches_a_candidate():
    from cognitive.verification import verify
    from cognitive.planning import TaskPlan
    from cognitive.strategy import StrategyDecision, VerificationRequirement
    from cognitive.state import PlannedTask
    t = PlannedTask(task_id="t1", objective="write code")
    artefact = f"```python\ndef f(x)\n    return '{PRIVATE_PHRASE}'\n```"
    v = verify(ExecutionResult(success=True, completed_tasks=["t1"]),
               TaskPlan(tasks=[t]),
               StrategyDecision(strategy=ReasoningStrategy.CODE,
                                verification_requirements=[
                                    VerificationRequirement.CODE_VALIDATION]),
               artifacts={"t1": artefact})
    c = correct(at_learn(), execution(), v)
    r = learn(at_learn(), execution(), v, c)
    dumped = r.model_dump_json()
    assert PRIVATE_PHRASE not in dumped
    assert "issue=python_syntax_error" in dumped, "the code IS kept; the content is not"


def test_every_summary_is_key_value_pairs_only():
    """Structural: a summary that ever contained prose would fail this."""
    import re
    v = verification(unverifiable=["CITATION_CHECK: not local"])
    r = learn(at_learn(), execution(outcomes=[outcome(FailureCategory.TOOL_FAILURE)]),
              v, no_correction())
    assert r.candidates
    for candidate in r.candidates:
        for token in candidate.summary.split():
            assert re.fullmatch(r"[A-Za-z_]+=[A-Za-z0-9_.]+", token), \
                f"non key=value token {token!r} in {candidate.summary!r}"


def test_exception_messages_never_reach_a_candidate():
    outcomes = [TaskOutcome(task_id="t1", status=TaskStatus.FAILED,
                            error_category=FailureCategory.TOOL_FAILURE,
                            safe_summary=f"boom {PRIVATE_PHRASE}")]
    r = learn(at_learn(), execution(outcomes=outcomes), verification(), no_correction())
    assert PRIVATE_PHRASE not in r.model_dump_json()


# ── a denial is not a lesson ─────────────────────────────────────────────────
def test_denials_are_withheld_entirely():
    r = learn(at_learn(),
              execution(completed_tasks=[], denied_tasks=["t9"],
                        final_execution_status=ExecutionStatus.EXECUTION_FAILED),
              verification(VerificationStatus.NOT_REQUIRED, verified=0),
              no_correction())
    assert any("refusals are not recorded" in w for w in r.withheld)
    assert all("denied" not in c.summary.lower() for c in r.candidates)
    assert all("t9" not in c.summary for c in r.candidates)


def test_there_is_no_category_for_a_policy_refusal():
    """Enforced by the type, not by which branch happened to run."""
    assert not any("POLICY" in c.value or "DENIAL" in c.value or "SECURITY" in c.value
                   for c in LearningCategory)


def test_a_denied_task_outcome_produces_no_capability_lesson():
    outcomes = [outcome(FailureCategory.SECURITY_BLOCK, task_id="t9")]
    r = learn(at_learn(),
              execution(completed_tasks=[], denied_tasks=["t9"], outcomes=outcomes,
                        final_execution_status=ExecutionStatus.EXECUTION_FAILED),
              verification(VerificationStatus.NOT_REQUIRED, verified=0),
              no_correction())
    assert r.by_category(LearningCategory.CAPABILITY_RELIABILITY) == []


def test_a_denied_task_is_skipped_even_with_an_instructive_failure():
    """Separates the two guards that both suppress a denied task's lesson.

    The test above uses SECURITY_BLOCK, which the failure-category filter
    already excludes — so it passes whether or not the denial skip exists. Only
    an instructive category on a denied task exercises the skip alone.
    """
    outcomes = [outcome(FailureCategory.TOOL_FAILURE, task_id="t9")]
    r = learn(at_learn(),
              execution(completed_tasks=[], denied_tasks=["t9"], outcomes=outcomes,
                        final_execution_status=ExecutionStatus.EXECUTION_FAILED),
              verification(VerificationStatus.NOT_REQUIRED, verified=0),
              no_correction())
    assert r.by_category(LearningCategory.CAPABILITY_RELIABILITY) == [], \
        "a refused task teaches nothing about the capability; it never ran"


def test_a_security_block_is_never_instructive_even_undenied():
    """Belt and braces: the category itself is excluded, not just the task id."""
    r = learn(at_learn(), execution(outcomes=[outcome(FailureCategory.SECURITY_BLOCK)]),
              verification(), no_correction())
    assert r.by_category(LearningCategory.CAPABILITY_RELIABILITY) == []


def test_an_instructive_failure_does_produce_a_lesson():
    r = learn(at_learn(), execution(outcomes=[outcome(FailureCategory.TIMEOUT)]),
              verification(), no_correction())
    lessons = r.by_category(LearningCategory.CAPABILITY_RELIABILITY)
    assert len(lessons) == 1
    assert "failure_category=TIMEOUT" in lessons[0].summary


# ── cancellation ─────────────────────────────────────────────────────────────
def test_cancellation_learns_nothing():
    r = learn(at_learn(),
              execution(completed_tasks=[],
                        final_execution_status=ExecutionStatus.CANCELLED),
              verification(VerificationStatus.FAILED, verified=0, failed=1),
              no_correction())
    assert r.status is LearningStatus.WITHHELD
    assert r.candidates == []
    assert any("cancelled" in w for w in r.withheld)


def test_cancellation_from_the_correction_report_also_withholds():
    r = learn(at_learn(), execution(), verification(),
              CorrectionReport(status=CorrectionStatus.CANCELLED))
    assert r.candidates == []


def test_cancellation_wins_over_a_verified_outcome():
    r = learn(at_learn(),
              execution(final_execution_status=ExecutionStatus.CANCELLED),
              verification(unverifiable=["CITATION_CHECK: not local"]),
              no_correction())
    assert r.candidates == []


# ── corrections teach that a defect occurred, not that a fix works ───────────
def test_a_proposed_correction_is_not_a_proven_fix():
    from cognitive.correction import CorrectionAction
    c = CorrectionReport(status=CorrectionStatus.CORRECTIONS_PROPOSED,
                         corrections=[CorrectionAction(target="t1",
                                                       issue="python_syntax_error")])
    r = learn(at_learn(), execution(), verification(), c)
    lesson = r.by_category(LearningCategory.RECURRING_DEFECT)[0]
    assert "status=PROPOSED_UNAPPLIED" in lesson.summary
    assert lesson.confidence < 1.0, "an unapplied fix is not evidence a fix works"


def test_repeated_defects_are_counted_not_duplicated():
    from cognitive.correction import CorrectionAction
    c = CorrectionReport(
        status=CorrectionStatus.CORRECTIONS_PROPOSED,
        corrections=[CorrectionAction(target="t1", issue="unclosed_fence"),
                     CorrectionAction(target="t2", issue="unclosed_fence")])
    r = learn(at_learn(), execution(), verification(), c)
    lessons = r.by_category(LearningCategory.RECURRING_DEFECT)
    assert len(lessons) == 1
    assert "occurrences=2" in lessons[0].summary


# ── emit: the only exit ──────────────────────────────────────────────────────
def test_without_a_sink_nothing_leaves():
    r = learn(at_learn(), execution(), verification(), no_correction())
    assert r.candidates
    assert emit(r) == 0, "no default sink; a default would choose for the caller"


def test_a_sink_receives_unapproved_candidates():
    seen = []
    r = learn(at_learn(), execution(), verification(), no_correction())
    assert emit(r, lambda c: seen.append(c) or True) == len(r.candidates)
    assert seen and all(c.approved is False for c in seen)


def test_a_rejecting_sink_is_counted_honestly():
    r = learn(at_learn(), execution(), verification(), no_correction())
    assert emit(r, lambda c: False) == 0


def test_a_raising_sink_never_breaks_the_request():
    def boom(_):
        raise RuntimeError("training store unreachable")
    r = learn(at_learn(), execution(), verification(), no_correction())
    assert emit(r, boom) == 0, "learning must never be why a request fails"


def test_emit_on_an_empty_report_is_a_no_op():
    assert emit(LearningReport(), lambda c: True) == 0


# ── determinism and state ────────────────────────────────────────────────────
def test_learning_is_deterministic():
    def once():
        r = learn(at_learn(), execution(outcomes=[outcome(FailureCategory.TIMEOUT)]),
                  verification(unverifiable=["CITATION_CHECK: not local"]),
                  no_correction())
        d = r.model_dump()
        for candidate in d["candidates"]:
            candidate.pop("candidate_id")
        return d
    assert once() == once() == once()


def test_learn_does_not_mutate_the_state_it_reads():
    s = at_learn()
    before = s.model_dump()
    learn(s, execution(), verification(), no_correction())
    assert s.model_dump() == before, "learn() reads state; apply_to_state writes it"


def test_apply_to_state_records_and_closes_the_session():
    s = at_learn()
    r = learn(s, execution(), verification(), no_correction())
    apply_to_state(s, r)
    assert s.learning_candidates
    assert s.phase is CognitivePhase.RESPOND
    assert s.is_terminal()


def test_learning_cannot_send_the_engine_round_again():
    s = at_learn()
    apply_to_state(s, learn(s, execution(),
                            verification(VerificationStatus.FAILED, verified=0, failed=1),
                            no_correction()))
    assert s.phase is CognitivePhase.RESPOND
    assert not s.can_transition_to(CognitivePhase.ASSESS)


def test_respond_is_reachable_even_with_the_budget_spent():
    s = at_learn()
    s.transition_count = s.max_transitions
    apply_to_state(s, learn(s, execution(), verification(), no_correction()))
    assert s.phase is CognitivePhase.RESPOND


def test_state_round_trips_after_learning():
    s = at_learn()
    apply_to_state(s, learn(s, execution(), verification(), no_correction()))
    restored = CognitiveState.model_validate(s.model_dump())
    assert restored.phase is s.phase
    assert len(restored.learning_candidates) == len(s.learning_candidates)
    assert all(c.approved is False for c in restored.learning_candidates)


# ── boundaries ───────────────────────────────────────────────────────────────
def _executable_source(module_name="learning.py"):
    """Source with docstrings stripped, so prose explaining why something is
    NOT done cannot satisfy a check that it is not done."""
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


def test_learning_imports_nothing_that_can_touch_the_world():
    import ast
    tree = ast.parse(_executable_source())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = {"os", "io", "sys", "sqlite3", "subprocess", "socket", "requests",
                 "httpx", "urllib", "json", "logging", "threading"}
    assert not (imported & forbidden), f"learning.py imports {imported & forbidden}"


def test_no_new_dependencies():
    import ast
    tree = ast.parse(_executable_source())
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module.split(".")[0])
    assert modules <= {"enum", "typing", "pydantic", "__future__"}


def test_no_parallel_training_store():
    """learning_loop owns the candidate table and the human review workflow.
    A second one here would give the product two stores and two queues."""
    src = _executable_source()
    for owned_by_learning_loop in ("training_candidates", "capture_candidate",
                                   "STATUS_PENDING", "STATUS_APPROVED",
                                   "_fingerprint", "INSERT INTO", "CREATE TABLE",
                                   "learning_loop"):
        assert owned_by_learning_loop not in src, \
            f"{owned_by_learning_loop} belongs to learning_loop"


def test_no_write_primitive_is_called():
    src = _executable_source()
    for primitive in ("open(", "commit(", "execute(", "write(", "Popen"):
        assert primitive not in src


def test_learning_writes_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = set(tmp_path.iterdir())
    s = at_learn()
    r = learn(s, execution(), verification(), no_correction())
    emit(r)
    apply_to_state(s, r)
    assert set(tmp_path.iterdir()) == before


def test_the_candidate_model_is_step_2s_not_a_copy():
    from cognitive.learning import LearningCandidate as here
    from cognitive.state import LearningCandidate as there
    assert here is there


def test_no_second_verifier_or_corrector():
    src = _executable_source()
    for owned_elsewhere in ("def verify", "def correct", "run_review_pipeline",
                            "derive_status", "validate_code", "FATAL_CODES"):
        assert owned_elsewhere not in src


def test_only_the_bridge_is_wired_into_the_product():
    """This stage has no direct line to /chat.

    Before integration this asserted that app.py mentioned `cognitive` at all.
    That invariant is now obsolete — the engine IS wired in — so it is replaced
    by the one that still matters: chat_bridge is the single door, and app.py
    never reaches past it into an individual stage.
    """
    import io, os, re
    app = os.path.join(os.path.dirname(__file__), "..", "app.py")
    src = io.open(app, encoding="utf-8").read()
    imports = re.findall(r"^\s*from\s+(cognitive\S*)\s+import", src, re.M)
    imports += re.findall(r"^\s*import\s+(cognitive\S*)", src, re.M)
    assert imports == ["cognitive.chat_bridge"],         f"app.py must reach the engine only through the bridge; found {imports}"

# ── end to end ───────────────────────────────────────────────────────────────
def test_a_verified_session_ends_with_a_reviewable_lesson():
    s = at_learn()
    r = learn(s, execution(), verification(), no_correction())
    accepted = []
    assert emit(r, lambda c: accepted.append(c) or True) == 1
    apply_to_state(s, r)
    assert s.phase is CognitivePhase.RESPOND
    assert accepted[0].approved is False
    assert accepted[0].category == LearningCategory.STRATEGY_OUTCOME.value


def test_a_refused_session_ends_with_nothing_to_review():
    s = at_learn()
    r = learn(s, execution(completed_tasks=[], denied_tasks=["t9"],
                           final_execution_status=ExecutionStatus.EXECUTION_FAILED),
              verification(VerificationStatus.NOT_REQUIRED, verified=0),
              no_correction())
    assert r.candidates == []
    assert r.requires_human_review is False
    assert emit(r, lambda c: True) == 0
    apply_to_state(s, r)
    assert s.learning_candidates == []


# ═══════════════════════════════════════════════════════════════════════════
# B1–B4 — verification provenance, correction outcome, remedy efficacy
#
# Once ACT exists a cycle produces TWO verifications, and they routinely
# disagree. Handed the stale one, this stage reported outcome=FAILED for a
# cycle whose corrected artefact verified clean. These pin the fix.
# ═══════════════════════════════════════════════════════════════════════════

from cognitive.act import act, ActResult, ActStatus
from cognitive.correction import correct, CorrectionAction
from cognitive.learning import CorrectionCycle, CorrectionOutcome, _outcome_of
from cognitive.planning import TaskPlan
from cognitive.strategy import StrategyDecision, VerificationRequirement
from cognitive.verification import verify
from cognitive.state import PlannedTask

FENCE = "`" * 3
# Valid Python, fence cut off: the deterministic remedy fully resolves it.
GOOD_OPEN = "Here:\n" + FENCE + "python\ndef f(x):\n    return x[::-1]\n"
# Broken Python, fence cut off: the fence is repaired, the code is still wrong.
BAD_OPEN = "Here:\n" + FENCE + "python\ndef f(x)\n    return x\n"


def _verify(artifacts):
    t = PlannedTask(task_id="t1", objective="write code")
    return verify(ExecutionResult(success=True, completed_tasks=["t1"]),
                  TaskPlan(tasks=[t]),
                  StrategyDecision(strategy=ReasoningStrategy.CODE,
                                   verification_requirements=[
                                       VerificationRequirement.CODE_VALIDATION]),
                  artifacts=artifacts)


def _cycle_for(artefact):
    """Drive the real VERIFY -> CORRECT -> ACT -> VERIFY loop."""
    s = at_learn()
    ex = ExecutionResult(success=True, completed_tasks=["t1"])
    first = _verify({"t1": artefact})
    proposal = correct(s, ex, first)
    applied = act(s, proposal, [a.action_id for a in proposal.corrections],
                  {"t1": artefact})
    second = _verify(applied.artifacts)
    return s, ex, first, proposal, applied, second


def _report(status, task_id="t1", reason=None):
    """A hand-built verification, for outcomes the one deterministic remedy
    cannot produce on its own."""
    return VerificationReport(
        results=[vr(status, task_id=task_id, reason=reason)], status=status,
        verified_count=1 if status is VerificationStatus.VERIFIED else 0,
        failed_count=1 if status is VerificationStatus.FAILED else 0)


# ── 1: a stale pre-ACT report cannot become the final outcome ────────────────
def test_a_stale_pre_act_failed_report_cannot_form_a_cycle():
    """The defect this exists for, driven through the real loop: the corrected
    artefact verifies clean while the pre-correction report still says FAILED.

    Step 9 now fingerprints the artefact it read, so the pair is rejected where
    it is built rather than argued about downstream. Task coverage alone never
    caught this — both reports are about t1, and only the content differs.
    """
    s, ex, first, proposal, applied, second = _cycle_for(GOOD_OPEN)
    assert first.status is VerificationStatus.FAILED
    assert second.status is VerificationStatus.VERIFIED

    with pytest.raises(ValueError, match="different artefact"):
        CorrectionCycle(act=applied, verification=first)


def test_the_digests_are_what_distinguishes_the_two_reports():
    """Guards the premise: same task, different bytes."""
    from cognitive.verification import artifact_digest
    s, ex, first, proposal, applied, second = _cycle_for(GOOD_OPEN)
    assert set(first.artifact_digests) == set(second.artifact_digests) == {"t1"}
    assert first.artifact_digests["t1"] != second.artifact_digests["t1"]
    assert second.artifact_digests["t1"] == artifact_digest(applied.artifacts["t1"])


def test_a_matching_digest_is_accepted():
    s, ex, first, proposal, applied, second = _cycle_for(GOOD_OPEN)
    cycle = CorrectionCycle(act=applied, verification=second)
    assert cycle.proves_content_for("t1") is True


def test_an_unproven_digest_is_not_a_mismatch_but_is_not_proof():
    """No fingerprint means Step 9 read no artefact for that task. That is not
    evidence of staleness, and it is not evidence of resolution either."""
    s, ex, first, proposal, applied, second = _cycle_for(GOOD_OPEN)
    no_digest = _report(VerificationStatus.VERIFIED)     # hand-built, no digests
    cycle = CorrectionCycle(act=applied, verification=no_digest)
    assert cycle.proves_content_for("t1") is False
    r = learn(s, ex, first, proposal, cycle=cycle)
    assert not any("APPLIED_RESOLVED" in c.summary for c in r.candidates), \
        "a clean verdict with no provenance cannot prove the remedy worked"


def test_the_stale_object_guard_still_covers_the_unproven_case():
    """The digest check cannot fire without a digest, so learn's own staleness
    guard remains the fallback for reports that recorded none."""
    s, ex, first, proposal, applied, second = _cycle_for(GOOD_OPEN)
    no_digest = _report(VerificationStatus.FAILED, reason="unclosed_fence")
    r = learn(s, ex, no_digest, proposal,
              cycle=CorrectionCycle(act=applied, verification=no_digest))
    assert r.by_category(LearningCategory.STRATEGY_OUTCOME) == []
    assert any("pre-correction" in w for w in r.withheld)


def test_no_cycle_at_all_withholds_the_outcome():
    s, ex, first, proposal, applied, second = _cycle_for(GOOD_OPEN)
    r = learn(s, ex, first, proposal)
    assert r.by_category(LearningCategory.STRATEGY_OUTCOME) == []
    assert any("cannot be established" in w for w in r.withheld)


def test_the_bound_cycle_produces_the_correct_outcome():
    s, ex, first, proposal, applied, second = _cycle_for(GOOD_OPEN)
    r = learn(s, ex, first, proposal, cycle=CorrectionCycle(act=applied,
                                                            verification=second))
    lesson = r.by_category(LearningCategory.STRATEGY_OUTCOME)[0]
    assert "outcome=VERIFIED" in lesson.summary


def test_the_two_reports_genuinely_disagree():
    """Guards the premise: if they ever agreed, every test above would pass
    for the wrong reason."""
    s, ex, first, proposal, applied, second = _cycle_for(GOOD_OPEN)
    assert first.status is not second.status


def test_a_cycle_must_cover_every_corrected_task():
    """Structural binding: an ActResult paired with a verification about
    different work is rejected at construction."""
    s, ex, first, proposal, applied, second = _cycle_for(GOOD_OPEN)
    elsewhere = _report(VerificationStatus.VERIFIED, task_id="t99")
    with pytest.raises(ValueError):
        CorrectionCycle(act=applied, verification=elsewhere)


def test_no_correction_means_the_initial_report_is_final():
    """Nothing came after it, so there is nothing staler to prefer."""
    r = learn(at_learn(), execution(), verification(), no_correction())
    assert r.by_category(LearningCategory.STRATEGY_OUTCOME)[0].summary.count(
        "outcome=VERIFIED") == 1


# ── 2 & 5: APPLIED_RESOLVED requires VERIFY, never ActStatus ─────────────────
def test_verified_after_act_produces_applied_resolved():
    s, ex, first, proposal, applied, second = _cycle_for(GOOD_OPEN)
    r = learn(s, ex, first, proposal, cycle=CorrectionCycle(act=applied,
                                                            verification=second))
    defect = r.by_category(LearningCategory.RECURRING_DEFECT)[0]
    assert "status=APPLIED_RESOLVED" in defect.summary


def test_the_defect_still_present_after_act_is_applied_unresolved():
    s, ex, first, proposal, applied, second = _cycle_for(GOOD_OPEN)
    still_broken = _report(VerificationStatus.FAILED, reason="unclosed_fence")
    r = learn(s, ex, first, proposal,
              cycle=CorrectionCycle(act=applied, verification=still_broken))
    defect = r.by_category(LearningCategory.RECURRING_DEFECT)[0]
    assert "status=APPLIED_UNRESOLVED" in defect.summary


def test_act_applied_alone_never_implies_resolved():
    """ACT says a transformation ran. Only Step 9 may say it worked."""
    s, ex, first, proposal, applied, second = _cycle_for(GOOD_OPEN)
    assert applied.status is ActStatus.APPLIED
    for post in (_report(VerificationStatus.FAILED, reason="unclosed_fence"),
                 _report(VerificationStatus.INCONCLUSIVE, reason="no artefact"),
                 _report(VerificationStatus.NOT_REQUIRED)):
        r = learn(s, ex, first, proposal,
                  cycle=CorrectionCycle(act=applied, verification=post))
        summaries = " ".join(c.summary for c in r.candidates)
        assert "APPLIED_RESOLVED" not in summaries, post.status.value


def test_an_unsettled_check_is_not_resolution():
    """None and empty-set are different: 'the check did not run' is not
    'the defect is gone'."""
    s, ex, first, proposal, applied, second = _cycle_for(GOOD_OPEN)
    inconclusive = _report(VerificationStatus.INCONCLUSIVE, reason="no artefact")
    action = proposal.corrections[0]
    outcome = _outcome_of(action, CorrectionCycle(act=applied,
                                                  verification=inconclusive))
    assert outcome is CorrectionOutcome.APPLIED_UNRESOLVED


# ── 4: proposed but never applied ────────────────────────────────────────────
def test_a_correction_act_refused_is_proposed_unapplied():
    """ACT refuses a non-deterministic remedy, so nothing was applied."""
    s = at_learn()
    ex = ExecutionResult(success=True, completed_tasks=["t1"])
    proposal = CorrectionReport(
        status=CorrectionStatus.CORRECTIONS_PROPOSED,
        corrections=[CorrectionAction(target="t1", issue="python_syntax_error")])
    refused = act(s, proposal, [proposal.corrections[0].action_id],
                  {"t1": BAD_OPEN})
    assert refused.applied_actions == []
    r = learn(s, ex, _report(VerificationStatus.FAILED), proposal,
              cycle=CorrectionCycle(act=refused,
                                    verification=_report(VerificationStatus.FAILED)))
    defect = r.by_category(LearningCategory.RECURRING_DEFECT)[0]
    assert "status=PROPOSED_UNAPPLIED" in defect.summary
    assert defect.confidence == 0.5, "nothing was proven, so the lesson is weaker"


def test_an_unapplied_correction_is_never_resolved():
    s = at_learn()
    proposal = CorrectionReport(
        status=CorrectionStatus.CORRECTIONS_PROPOSED,
        corrections=[CorrectionAction(target="t1", issue="python_syntax_error")])
    refused = act(s, proposal, [proposal.corrections[0].action_id], {"t1": BAD_OPEN})
    r = learn(s, ExecutionResult(success=True, completed_tasks=["t1"]),
              _report(VerificationStatus.FAILED), proposal,
              cycle=CorrectionCycle(act=refused,
                                    verification=_report(VerificationStatus.VERIFIED)))
    summaries = " ".join(c.summary for c in r.candidates)
    assert "APPLIED_RESOLVED" not in summaries, \
        "a clean verification does not retroactively apply a refused correction"


# ── 3: remedy efficacy ───────────────────────────────────────────────────────
def test_remedy_efficacy_records_the_whole_chain():
    s, ex, first, proposal, applied, second = _cycle_for(GOOD_OPEN)
    r = learn(s, ex, first, proposal, cycle=CorrectionCycle(act=applied,
                                                            verification=second))
    efficacy = r.by_category(LearningCategory.REMEDY_EFFICACY)[0]
    for part in ("issue=unclosed_fence", "remedy=deterministic", "applied=yes",
                 "outcome=APPLIED_RESOLVED"):
        assert part in efficacy.summary


def test_remedy_efficacy_and_defect_lessons_never_disagree():
    """Both are built from one basis, so they cannot drift apart."""
    for artefact in (GOOD_OPEN, BAD_OPEN):
        s, ex, first, proposal, applied, second = _cycle_for(artefact)
        r = learn(s, ex, first, proposal,
                  cycle=CorrectionCycle(act=applied, verification=second))
        defects = r.by_category(LearningCategory.RECURRING_DEFECT)
        efficacy = r.by_category(LearningCategory.REMEDY_EFFICACY)
        assert len(defects) == len(efficacy)
        for d, e in zip(defects, efficacy):
            outcome = d.summary.split("status=")[1]
            assert f"outcome={outcome}" in e.summary


def test_a_working_remedy_and_a_failed_overall_outcome_coexist():
    """The nuance the loop exists to capture: closing the fence genuinely
    worked, and the answer is still wrong for a different reason."""
    s, ex, first, proposal, applied, second = _cycle_for(BAD_OPEN)
    assert second.status is VerificationStatus.FAILED
    r = learn(s, ex, first, proposal, cycle=CorrectionCycle(act=applied,
                                                            verification=second))
    assert "outcome=FAILED" in r.by_category(
        LearningCategory.STRATEGY_OUTCOME)[0].summary
    assert "APPLIED_RESOLVED" in r.by_category(
        LearningCategory.REMEDY_EFFICACY)[0].summary


def test_the_efficacy_vocabulary_is_closed():
    assert {o.value for o in CorrectionOutcome} == {
        "PROPOSED_UNAPPLIED", "APPLIED_UNRESOLVED", "APPLIED_RESOLVED"}


# ── 6: a final FAILED is still a legitimate lesson ───────────────────────────
def test_a_final_failed_outcome_still_teaches():
    s, ex, first, proposal, applied, second = _cycle_for(BAD_OPEN)
    r = learn(s, ex, first, proposal, cycle=CorrectionCycle(act=applied,
                                                            verification=second))
    lesson = r.by_category(LearningCategory.STRATEGY_OUTCOME)[0]
    assert "outcome=FAILED" in lesson.summary
    assert r.status is LearningStatus.CANDIDATES_PROPOSED


def test_a_failed_outcome_is_not_proof_a_correction_succeeded():
    s, ex, first, proposal, applied, second = _cycle_for(BAD_OPEN)
    r = learn(s, ex, first, proposal, cycle=CorrectionCycle(act=applied,
                                                            verification=second))
    assert not any("outcome=VERIFIED" in c.summary for c in r.candidates)


# ── 7 & 8: unchanged behaviour ───────────────────────────────────────────────
def test_inconclusive_is_still_withheld_with_a_cycle():
    s, ex, first, proposal, applied, second = _cycle_for(GOOD_OPEN)
    inconclusive = _report(VerificationStatus.INCONCLUSIVE, reason="no artefact")
    r = learn(s, ex, first, proposal,
              cycle=CorrectionCycle(act=applied, verification=inconclusive))
    assert r.by_category(LearningCategory.STRATEGY_OUTCOME) == []
    assert any("not verified" in w for w in r.withheld)


def test_gap_lessons_survive_an_unestablished_outcome():
    """What EVA cannot check does not depend on whether a correction worked."""
    s = at_learn()
    proposal = CorrectionReport(
        status=CorrectionStatus.CORRECTIONS_PROPOSED,
        corrections=[CorrectionAction(target="t1", issue="unclosed_fence")])
    r = learn(s, execution(),
              verification(VerificationStatus.FAILED, verified=0, failed=1,
                           unverifiable=["CITATION_CHECK: runs on the ML service"]),
              proposal)                      # no cycle
    assert r.by_category(LearningCategory.STRATEGY_OUTCOME) == []
    assert r.by_category(LearningCategory.VERIFICATION_GAP), \
        "a gap is an observation, not an outcome"


def test_gaps_from_both_reports_are_collected_once():
    s, ex, first, proposal, applied, second = _cycle_for(GOOD_OPEN)
    gapped = VerificationReport(
        results=[vr(VerificationStatus.VERIFIED)], status=VerificationStatus.VERIFIED,
        verified_count=1, unverifiable=["CITATION_CHECK: not local"])
    r = learn(s, ex, first, proposal,
              cycle=CorrectionCycle(act=applied, verification=gapped))
    gaps = r.by_category(LearningCategory.VERIFICATION_GAP)
    assert len(gaps) == len({g.summary for g in gaps}), "no duplicates"


def test_cancellation_still_wins_over_a_cycle():
    s, ex, first, proposal, applied, second = _cycle_for(GOOD_OPEN)
    r = learn(s, ExecutionResult(completed_tasks=[],
                                 final_execution_status=ExecutionStatus.CANCELLED),
              first, proposal, cycle=CorrectionCycle(act=applied, verification=second))
    assert r.candidates == []


def test_denials_are_still_withheld_with_a_cycle():
    s, ex, first, proposal, applied, second = _cycle_for(GOOD_OPEN)
    r = learn(s, ExecutionResult(completed_tasks=["t1"], denied_tasks=["t9"]),
              first, proposal, cycle=CorrectionCycle(act=applied, verification=second))
    assert any("refusals are not recorded" in w for w in r.withheld)


# ── 9: nothing leaks through the new path ────────────────────────────────────
def test_no_artefact_content_reaches_a_candidate_through_the_cycle():
    private = "the launch date is March the fourth"
    artefact = "Here:\n" + FENCE + f"python\ndef f(x)\n    return '{private}'\n"
    s, ex, first, proposal, applied, second = _cycle_for(artefact)
    r = learn(s, ex, first, proposal, cycle=CorrectionCycle(act=applied,
                                                            verification=second))
    assert private not in r.model_dump_json()


def test_no_secret_reaches_a_candidate_through_the_cycle():
    key = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    artefact = "Here:\n" + FENCE + f"python\ntoken = '{key}'\n"
    s, ex, first, proposal, applied, second = _cycle_for(artefact)
    assert key in applied.artifacts["t1"], "ACT keeps the artefact exact"
    r = learn(s, ex, first, proposal, cycle=CorrectionCycle(act=applied,
                                                            verification=second))
    assert key not in r.model_dump_json(), "learning must not inherit that"


def test_every_summary_is_still_key_value_pairs_only():
    import re
    s, ex, first, proposal, applied, second = _cycle_for(GOOD_OPEN)
    r = learn(s, ex, first, proposal, cycle=CorrectionCycle(act=applied,
                                                            verification=second))
    for candidate in r.candidates:
        for token in candidate.summary.split():
            assert re.fullmatch(r"[A-Za-z_]+=[A-Za-z0-9_.]+", token), \
                f"non key=value token {token!r} in {candidate.summary!r}"


# ── 10: deterministic and bounded ────────────────────────────────────────────
def test_learning_with_a_cycle_is_deterministic():
    s, ex, first, proposal, applied, second = _cycle_for(GOOD_OPEN)
    cycle = CorrectionCycle(act=applied, verification=second)

    def once():
        d = learn(s, ex, first, proposal, cycle=cycle).model_dump()
        for candidate in d["candidates"]:
            candidate.pop("candidate_id")
        return d
    assert once() == once() == once()


def test_the_candidate_count_stays_bounded():
    s, ex, first, proposal, applied, second = _cycle_for(GOOD_OPEN)
    r = learn(s, ex, first, proposal, cycle=CorrectionCycle(act=applied,
                                                            verification=second))
    assert len(r.candidates) <= 40


def test_learn_still_does_not_mutate_the_state():
    s, ex, first, proposal, applied, second = _cycle_for(GOOD_OPEN)
    before = s.model_dump()
    learn(s, ex, first, proposal, cycle=CorrectionCycle(act=applied,
                                                        verification=second))
    assert s.model_dump() == before


def test_learning_still_performs_no_io_after_the_change():
    import ast
    tree = ast.parse(_executable_source())
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module.split(".")[0])
    assert modules <= {"enum", "typing", "pydantic", "__future__"}


def test_learning_still_does_not_verify_correct_or_execute():
    src = _executable_source()
    for owned_elsewhere in ("def verify", "def correct", "def act",
                            "run_review_pipeline", "derive_status", "_DETERMINISTIC"):
        assert owned_elsewhere not in src, f"{owned_elsewhere} belongs to another stage"


# ═══════════════════════════════════════════════════════════════════════════
# Update 15 — post-remedy verification semantics.
#
# NOT_REQUIRED and INCONCLUSIVE used to be treated alike, and they are
# opposites: one is evidence of absence, the other the absence of evidence.
# Collapsing them meant every REMOVAL remedy was judged to have failed, because
# the block it deleted was exactly what the check looked for.
# ═══════════════════════════════════════════════════════════════════════════

def _report_with(*results, digests=None):
    """A post-ACT verification carrying chosen per-check verdicts."""
    from cognitive.verification import VerificationReport
    from cognitive.state import VerificationResult
    built = [VerificationResult(task_id=t, status=s, verification_type=v,
                                criteria=[c], failure_reason=r)
             for (t, s, v, c, r) in results]
    worst = VerificationStatus.NOT_REQUIRED
    for b in built:
        if b.status is VerificationStatus.FAILED:
            worst = VerificationStatus.FAILED
            break
        if b.status is VerificationStatus.VERIFIED:
            worst = VerificationStatus.VERIFIED
    return VerificationReport(results=built, status=worst,
                              artifact_digests=dict(digests or {}))


# ── the three states ─────────────────────────────────────────────────────────
def test_check_state_distinguishes_settled_absent_and_unknown():
    from cognitive.learning import _check_state, _CheckState
    T = "t1"
    settled = _report_with((T, VerificationStatus.FAILED, "DIAGRAM_VALIDATION",
                            "mermaid", "prose_not_diagram"))
    absent = _report_with((T, VerificationStatus.NOT_REQUIRED,
                           "DIAGRAM_VALIDATION", "mermaid", None))
    unknown = _report_with((T, VerificationStatus.INCONCLUSIVE,
                            "DIAGRAM_VALIDATION", "mermaid", "no artefact"))
    assert _check_state(settled, T)[0] is _CheckState.SETTLED
    assert _check_state(absent, T)[0] is _CheckState.ABSENT
    assert _check_state(unknown, T)[0] is _CheckState.UNKNOWN


def test_a_settled_verdict_outranks_an_absent_one():
    """With several requirements on one task, a check that FAILED is decisive
    even while another finds nothing of its kind."""
    from cognitive.learning import _check_state, _CheckState
    T = "t1"
    mixed = _report_with(
        (T, VerificationStatus.NOT_REQUIRED, "DIAGRAM_VALIDATION", "mermaid", None),
        (T, VerificationStatus.FAILED, "CODE_VALIDATION", "code",
         "python_syntax_error"))
    state, codes = _check_state(mixed, T)
    assert state is _CheckState.SETTLED
    assert codes == {"python_syntax_error"}


def test_a_state_for_another_task_is_ignored():
    from cognitive.learning import _check_state, _CheckState
    other = _report_with(("t2", VerificationStatus.NOT_REQUIRED,
                          "DIAGRAM_VALIDATION", "mermaid", None))
    assert _check_state(other, "t1")[0] is _CheckState.UNKNOWN


# ── removal vs repair-in-place ───────────────────────────────────────────────
def test_every_remedy_declares_what_it_leaves_behind():
    from cognitive.act import _DETERMINISTIC
    for issue, remedy in _DETERMINISTIC.items():
        assert isinstance(remedy.removes_construct, bool), issue


def test_a_remedy_that_forgets_to_declare_defaults_to_repair_in_place():
    """Every current remedy declares explicitly, so the default is unreachable
    today and flipping it changes nothing observable. It still has to be the
    safe direction: an undeclared remedy assumed to REMOVE its construct would
    let a vanished block pass as a successful repair.
    """
    from cognitive.act import _Remedy
    undeclared = _Remedy(precondition=lambda t: True, transform=lambda t: t,
                         description="a future remedy")
    assert undeclared.removes_construct is False


def test_the_declarations_match_what_the_remedies_actually_do():
    """Checked against the transform, not against the declaration."""
    from cognitive.act import _DETERMINISTIC, remedy_removes_construct
    from cognitive.verification import run_review_pipeline
    F = "`" * 3
    samples = {
        "unclosed_fence": "Here:\n" + F + "python\ndef f(x):\n    return x\n",
        "prose_not_diagram": ("Here:\n" + F +
                              "mermaid\nFirst the user logs in.\n" + F + "\n"),
        "empty_diagram": "Here:\n" + F + "mermaid\n\n" + F + "\n",
    }
    for issue, text in samples.items():
        fixed = _DETERMINISTIC[issue].transform(text)
        checks = run_review_pipeline(fixed)["checks"]
        name = {"unclosed_fence": "code", "prose_not_diagram": "mermaid",
                "empty_diagram": "mermaid"}[issue]
        still_present = checks[name]["applicable"]
        assert remedy_removes_construct(issue) is (not still_present), (
            f"{issue}: declares removes_construct="
            f"{remedy_removes_construct(issue)} but the construct is "
            f"{'present' if still_present else 'gone'} afterwards")


def test_an_unknown_issue_code_removes_nothing():
    from cognitive.act import remedy_removes_construct
    assert remedy_removes_construct("cosmic_ray") is False
    assert remedy_removes_construct("") is False


# ── the outcome rule ─────────────────────────────────────────────────────────
def _cycle_with(issue, post_report, artefact):
    from cognitive.act import act
    from cognitive.correction import CorrectionReport, CorrectionStatus, CorrectionAction
    from cognitive.learning import CorrectionCycle
    from cognitive.state import CognitiveState, CognitivePhase
    from cognitive.verification import artifact_digest
    s = CognitiveState()
    for phase in (CognitivePhase.ASSESS, CognitivePhase.STRATEGY,
                  CognitivePhase.PLAN, CognitivePhase.ACT, CognitivePhase.VERIFY,
                  CognitivePhase.CORRECT):
        s.transition_to(phase)
    action = CorrectionAction(target="t1", issue=issue)
    proposal = CorrectionReport(status=CorrectionStatus.CORRECTIONS_PROPOSED,
                                corrections=[action])
    applied = act(s, proposal, [action.action_id], {"t1": artefact})
    assert applied.artifacts, f"{issue} must actually apply for this fixture"
    post_report.artifact_digests = {"t1": artifact_digest(applied.artifacts["t1"])}
    return action, CorrectionCycle(act=applied, verification=post_report)


F3 = "`" * 3
PROSE_DIAG = "Here:\n" + F3 + "mermaid\nFirst the user logs in.\n" + F3 + "\n"
OPEN_PY = "Here:\n" + F3 + "python\ndef f(x):\n    return x\n"


def test_a_removal_remedy_resolves_on_not_required():
    """The defect this update fixes: unfencing deletes the block, so the check
    finds nothing — and for a removal remedy that IS the repair."""
    from cognitive.learning import _outcome_of, CorrectionOutcome
    post = _report_with(("t1", VerificationStatus.NOT_REQUIRED,
                         "DIAGRAM_VALIDATION", "mermaid", None))
    action, cycle = _cycle_with("prose_not_diagram", post, PROSE_DIAG)
    assert _outcome_of(action, cycle) is CorrectionOutcome.APPLIED_RESOLVED


def test_a_repair_in_place_remedy_does_not_resolve_on_not_required():
    """The guard the declaration buys: a block that VANISHED when it should
    have been repaired is a failure, not a success."""
    from cognitive.learning import _outcome_of, CorrectionOutcome
    post = _report_with(("t1", VerificationStatus.NOT_REQUIRED,
                         "CODE_VALIDATION", "code", None))
    action, cycle = _cycle_with("unclosed_fence", post, OPEN_PY)
    assert _outcome_of(action, cycle) is CorrectionOutcome.APPLIED_UNRESOLVED


def test_inconclusive_still_never_resolves_for_either_kind():
    """Absence of evidence is still not evidence — for removal remedies too."""
    from cognitive.learning import _outcome_of, CorrectionOutcome
    for issue, artefact in (("prose_not_diagram", PROSE_DIAG),
                            ("unclosed_fence", OPEN_PY)):
        post = _report_with(("t1", VerificationStatus.INCONCLUSIVE,
                             "DIAGRAM_VALIDATION", "mermaid", "no artefact"))
        action, cycle = _cycle_with(issue, post, artefact)
        assert _outcome_of(action, cycle) is CorrectionOutcome.APPLIED_UNRESOLVED, issue


def test_a_still_reported_defect_never_resolves():
    from cognitive.learning import _outcome_of, CorrectionOutcome
    post = _report_with(("t1", VerificationStatus.FAILED, "DIAGRAM_VALIDATION",
                         "mermaid", "prose_not_diagram"))
    action, cycle = _cycle_with("prose_not_diagram", post, PROSE_DIAG)
    assert _outcome_of(action, cycle) is CorrectionOutcome.APPLIED_UNRESOLVED


def test_a_destroyed_answer_cannot_pass_as_a_repair():
    """The attack the D1 fix already defends: an emptied artefact verifies
    INCONCLUSIVE, never NOT_REQUIRED, so it can never read as resolved."""
    from cognitive.verification import verify
    from cognitive.executor import ExecutionResult, ExecutionStatus
    from cognitive.planning import TaskPlan
    from cognitive.state import PlannedTask
    from cognitive.strategy import StrategyDecision, VerificationRequirement
    from cognitive.state import ReasoningStrategy
    t = PlannedTask(task_id="t1", objective="x")
    report = verify(
        ExecutionResult(success=True, completed_tasks=["t1"],
                        final_execution_status=ExecutionStatus.EXECUTION_COMPLETE),
        TaskPlan(tasks=[t]),
        StrategyDecision(strategy=ReasoningStrategy.CODE,
                         verification_requirements=[
                             VerificationRequirement.DIAGRAM_VALIDATION]),
        artifacts={"t1": "   "})
    assert report.results[0].status is VerificationStatus.INCONCLUSIVE


def test_learning_records_the_removal_remedy_as_effective():
    """The efficacy lesson follows the same rule, because both read
    _outcome_of — they cannot disagree about whether a remedy worked."""
    from cognitive.learning import learn, LearningCategory
    from cognitive.correction import CorrectionReport, CorrectionStatus
    post = _report_with(("t1", VerificationStatus.NOT_REQUIRED,
                         "DIAGRAM_VALIDATION", "mermaid", None))
    action, cycle = _cycle_with("prose_not_diagram", post, PROSE_DIAG)
    proposal = CorrectionReport(status=CorrectionStatus.CORRECTIONS_PROPOSED,
                                corrections=[action])
    r = learn(at_learn(), execution(), verification(VerificationStatus.FAILED,
                                                    verified=0, failed=1),
              proposal, cycle=cycle)
    efficacy = r.by_category(LearningCategory.REMEDY_EFFICACY)
    assert efficacy and "outcome=APPLIED_RESOLVED" in efficacy[0].summary
