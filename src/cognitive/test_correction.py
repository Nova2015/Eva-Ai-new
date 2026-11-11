"""Tests for the Correction stage (Step 10).

Two load-bearing properties, and most of this file exists to hold them:

  1. **Correction never returns VERIFIED.** A proposal is unproven by
     construction; only VERIFY may call something correct.
  2. **A refusal is not a defect.** No correction may target a denied task or
     route around the policy that refused it — the same reasoning that fixed
     the Step 8 review defect, applied one stage later.

Everything here is offline. Nothing in this module writes a file, and a test
asserts that from the parsed source of correction.py rather than by trusting it.
"""

import pytest

try:
    from cognitive.correction import (
        correct, apply_to_state, CorrectionReport, CorrectionAction,
        CorrectionStatus, _REMEDY,
    )
    from cognitive.verification import VerificationReport, verify
    from cognitive.executor import ExecutionResult, ExecutionStatus
    from cognitive.planning import TaskPlan
    from cognitive.strategy import StrategyDecision, VerificationRequirement
    from cognitive.assessment import RiskLevel
    from cognitive.state import (
        CognitiveState, CognitivePhase, CognitiveError, FailureCategory,
        PlannedTask, VerificationResult, VerificationStatus, ReasoningStrategy,
    )
except ImportError:  # running from src/cognitive directly
    from correction import (  # type: ignore
        correct, apply_to_state, CorrectionReport, CorrectionAction,
        CorrectionStatus, _REMEDY,
    )
    from verification import VerificationReport, verify  # type: ignore
    from executor import ExecutionResult, ExecutionStatus  # type: ignore
    from planning import TaskPlan  # type: ignore
    from strategy import StrategyDecision, VerificationRequirement  # type: ignore
    from assessment import RiskLevel  # type: ignore
    from state import (  # type: ignore
        CognitiveState, CognitivePhase, CognitiveError, FailureCategory,
        PlannedTask, VerificationResult, VerificationStatus, ReasoningStrategy,
    )


# ── builders ─────────────────────────────────────────────────────────────────
def vr(status, task_id="t1", vtype="CODE_VALIDATION", reason=None,
       criteria=("code",), confidence=0.0):
    return VerificationResult(task_id=task_id, status=status,
                              verification_type=vtype, criteria=list(criteria),
                              failure_reason=reason, confidence=confidence)


def report(*results, status=None):
    results = list(results)
    statuses = {r.status for r in results}
    if status is None:
        if VerificationStatus.FAILED in statuses:
            status = VerificationStatus.FAILED
        elif VerificationStatus.INCONCLUSIVE in statuses:
            status = VerificationStatus.INCONCLUSIVE
        elif VerificationStatus.VERIFIED in statuses:
            status = VerificationStatus.VERIFIED
        else:
            status = VerificationStatus.NOT_REQUIRED
    return VerificationReport(
        results=results, status=status,
        verified_count=sum(1 for r in results
                           if r.status is VerificationStatus.VERIFIED),
        failed_count=sum(1 for r in results
                         if r.status is VerificationStatus.FAILED),
        inconclusive_count=sum(1 for r in results
                               if r.status is VerificationStatus.INCONCLUSIVE),
    )


def execution(**kw):
    kw.setdefault("completed_tasks", ["t1"])
    kw.setdefault("final_execution_status", ExecutionStatus.EXECUTION_COMPLETE)
    return ExecutionResult(**kw)


def at_verify():
    """A state that has legitimately reached VERIFY."""
    s = CognitiveState()
    for phase in (CognitivePhase.ASSESS, CognitivePhase.STRATEGY,
                  CognitivePhase.PLAN, CognitivePhase.ACT, CognitivePhase.VERIFY):
        s.transition_to(phase)
    return s


FAILED_CODE = vr(VerificationStatus.FAILED, reason="python_syntax_error")


# ── A: VERIFIED means leave it alone ─────────────────────────────────────────
def test_verified_needs_no_correction():
    r = correct(at_verify(), execution(),
                report(vr(VerificationStatus.VERIFIED, confidence=1.0)))
    assert r.status is CorrectionStatus.NO_CORRECTION_NEEDED
    assert r.corrections == []
    assert r.requires_reverification is False
    assert r.requires_reassessment is False


def test_not_required_is_not_a_defect():
    r = correct(at_verify(), execution(), report(vr(VerificationStatus.NOT_REQUIRED)))
    assert r.status is CorrectionStatus.NO_CORRECTION_NEEDED
    assert r.corrections == []


def test_verified_alongside_a_failure_only_corrects_the_failure():
    r = correct(at_verify(), execution(completed_tasks=["t1", "t2"]),
                report(vr(VerificationStatus.VERIFIED, task_id="t2", confidence=1.0),
                       FAILED_CODE))
    assert r.corrected_items == ["t1"]
    assert "t2" not in r.corrected_items


# ── B: INCONCLUSIVE means find evidence, not guess ───────────────────────────
def test_inconclusive_proposes_nothing_and_names_the_gap():
    r = correct(at_verify(), execution(),
                report(vr(VerificationStatus.INCONCLUSIVE,
                          reason="no verifiable artefact available")))
    assert r.status is CorrectionStatus.INSUFFICIENT_EVIDENCE
    assert r.corrections == []
    assert r.requires_reverification is False
    assert any("no verifiable artefact" in u for u in r.unresolved_items)


def test_inconclusive_does_not_trigger_reassessment():
    """Missing evidence is answered by obtaining evidence, not by re-planning."""
    r = correct(at_verify(), execution(),
                report(vr(VerificationStatus.INCONCLUSIVE, reason="validator error")))
    assert r.requires_reassessment is False


def test_a_warning_is_not_a_correction_trigger():
    """Step 9 reports non-fatal issues as INCONCLUSIVE. Rewriting an artefact
    on that basis would be a change made without proof anything is wrong."""
    r = correct(at_verify(), execution(),
                report(vr(VerificationStatus.INCONCLUSIVE, reason="js_syntax_error")))
    assert r.corrections == []
    assert r.requires_reassessment is False


# ── C: FAILED with actionable evidence ───────────────────────────────────────
def test_failed_code_validation_proposes_an_actionable_correction():
    r = correct(at_verify(), execution(), report(FAILED_CODE))
    assert r.status is CorrectionStatus.CORRECTIONS_PROPOSED
    assert len(r.corrections) == 1
    action = r.corrections[0]
    assert action.target == "t1"
    assert action.issue == "python_syntax_error"
    assert action.proposed_change == _REMEDY["python_syntax_error"]
    assert action.confidence == 1.0
    assert action.risk is RiskLevel.LOW
    assert r.corrected_items == ["t1"]


def test_the_correction_references_the_verification_that_justified_it():
    r = correct(at_verify(), execution(), report(FAILED_CODE))
    ref = r.corrections[0].evidence[0]
    assert "CODE_VALIDATION" in ref and "t1" in ref and "FAILED" in ref
    assert r.evidence_used, "the report must say what it acted on"


def test_each_issue_gets_its_own_action_not_one_blanket_fix():
    r = correct(at_verify(), execution(),
                report(vr(VerificationStatus.FAILED,
                          reason="python_syntax_error, unclosed_fence")))
    assert {a.issue for a in r.corrections} == {"python_syntax_error", "unclosed_fence"}
    assert all(a.proposed_change for a in r.corrections)


@pytest.mark.parametrize("code", sorted(_REMEDY))
def test_every_mapped_code_produces_a_specific_remedy(code):
    r = correct(at_verify(), execution(), report(vr(VerificationStatus.FAILED,
                                                   reason=code)))
    assert len(r.corrections) == 1
    assert r.corrections[0].proposed_change == _REMEDY[code]
    assert "fix everything" not in r.corrections[0].proposed_change.lower()


# ── D: FAILED without a derivable cause ──────────────────────────────────────
def test_unknown_issue_code_proposes_nothing():
    r = correct(at_verify(), execution(),
                report(vr(VerificationStatus.FAILED, reason="cosmic_ray")))
    assert r.corrections == []
    assert any("cosmic_ray" in u for u in r.unresolved_items)
    assert r.status is CorrectionStatus.REASSESS_REQUIRED
    assert r.requires_reassessment is True, \
        "a real failure with no derivable remedy is a reason to think again"


def test_execution_test_failure_has_no_artefact_level_remedy():
    """A runner status says the code misbehaved, not what to change about it."""
    r = correct(at_verify(), execution(),
                report(vr(VerificationStatus.FAILED, vtype="EXECUTION_TEST",
                          reason="RUNTIME_ERROR", criteria=("execution",))))
    assert r.corrections == []
    assert r.requires_reassessment is True


def test_partly_understood_failure_lowers_confidence_rather_than_rounding_up():
    r = correct(at_verify(), execution(),
                report(vr(VerificationStatus.FAILED,
                          reason="python_syntax_error, cosmic_ray")))
    assert len(r.corrections) == 1
    assert r.corrections[0].confidence == 0.5
    assert any("cosmic_ray" in u for u in r.unresolved_items)


def test_failed_with_no_reason_at_all_proposes_nothing():
    r = correct(at_verify(), execution(), report(vr(VerificationStatus.FAILED)))
    assert r.corrections == []
    assert r.requires_reassessment is True


# ── E: a denial is never corrected around ────────────────────────────────────
def test_security_denial_is_blocking_not_correctable():
    r = correct(at_verify(),
                execution(completed_tasks=[], denied_tasks=["t9"],
                          final_execution_status=ExecutionStatus.EXECUTION_FAILED),
                report())
    assert r.status is CorrectionStatus.BLOCKED
    assert r.corrections == []
    assert any("t9" in b for b in r.blocking_issues)
    assert r.requires_reassessment is False, \
        "re-planning around a refusal is the shape of a bypass attempt"


def test_no_correction_may_target_a_denied_task():
    r = correct(at_verify(),
                execution(completed_tasks=[], denied_tasks=["t1"],
                          final_execution_status=ExecutionStatus.EXECUTION_FAILED),
                report(FAILED_CODE))     # a verification that should not exist
    assert all(a.target != "t1" for a in r.corrections)
    assert r.corrections == []


def test_denial_errors_are_recorded_as_blocking():
    err = CognitiveError(category=FailureCategory.SECURITY_BLOCK, task_id="t5",
                         message="tool not whitelisted")
    r = correct(at_verify(),
                execution(completed_tasks=[], errors=[err],
                          final_execution_status=ExecutionStatus.EXECUTION_FAILED),
                report())
    assert any("SECURITY_BLOCK" in b for b in r.blocking_issues)
    assert r.requires_reassessment is False


def test_no_proposed_change_names_a_tool_a_path_or_a_command():
    """A correction is about an artefact. If one could name a tool it would be
    a route around the whitelist rather than a rewrite of a code block."""
    forbidden = ("subprocess", "os.system", "rm ", "sudo", "curl", "DROP TABLE",
                 "chmod", "http://", "https://", "--force", "whitelist", "policy")
    for remedy in _REMEDY.values():
        low = remedy.lower()
        assert not any(f.lower() in low for f in forbidden), remedy


def test_denial_alongside_a_real_failure_still_blocks_but_corrects_the_failure():
    r = correct(at_verify(),
                execution(completed_tasks=["t1"], denied_tasks=["t9"]),
                report(FAILED_CODE))
    assert r.corrections and r.corrections[0].target == "t1"
    assert any("t9" in b for b in r.blocking_issues)
    assert r.safe_to_apply is False, "an outstanding refusal withdraws that"


# ── F: cancellation is the user's decision ───────────────────────────────────
def test_cancellation_proposes_no_retry():
    r = correct(at_verify(),
                execution(completed_tasks=[], cancelled_tasks=["t1"],
                          final_execution_status=ExecutionStatus.CANCELLED),
                report(FAILED_CODE))
    assert r.status is CorrectionStatus.CANCELLED
    assert r.corrections == []
    assert r.requires_reassessment is False
    assert r.requires_reverification is False
    assert r.safe_to_apply is False


def test_cancellation_wins_over_everything_else():
    r = correct(at_verify(),
                execution(completed_tasks=["t1"], denied_tasks=["t9"],
                          requires_reassessment=True,
                          final_execution_status=ExecutionStatus.CANCELLED),
                report(FAILED_CODE))
    assert r.status is CorrectionStatus.CANCELLED


def test_cancellation_aborts_the_session():
    s = at_verify()
    apply_to_state(s, correct(s, execution(
        completed_tasks=[], final_execution_status=ExecutionStatus.CANCELLED),
        report()))
    assert s.phase is CognitivePhase.ABORTED


# ── G: conflicting evidence ──────────────────────────────────────────────────
def test_conflicting_evidence_is_not_resolved_by_picking_one():
    r = correct(at_verify(), execution(),
                report(vr(VerificationStatus.VERIFIED, confidence=1.0),
                       vr(VerificationStatus.FAILED, reason="python_syntax_error")))
    assert r.requires_reassessment is True
    assert r.status is CorrectionStatus.REASSESS_REQUIRED
    assert any("both passed and failed" in u for u in r.unresolved_items)


def test_the_same_check_on_different_tasks_is_not_a_conflict():
    r = correct(at_verify(), execution(completed_tasks=["t1", "t2"]),
                report(vr(VerificationStatus.VERIFIED, task_id="t2", confidence=1.0),
                       vr(VerificationStatus.FAILED, task_id="t1",
                          reason="python_syntax_error")))
    assert r.requires_reassessment is False
    assert r.status is CorrectionStatus.CORRECTIONS_PROPOSED


def test_different_checks_on_one_task_are_not_a_conflict():
    r = correct(at_verify(), execution(),
                report(vr(VerificationStatus.VERIFIED, vtype="DIAGRAM_VALIDATION",
                          criteria=("mermaid",), confidence=1.0),
                       vr(VerificationStatus.FAILED, reason="python_syntax_error")))
    assert r.requires_reassessment is False


def test_step_8_reassessment_is_carried_through_not_recomputed():
    r = correct(at_verify(), execution(requires_reassessment=True), report())
    assert r.requires_reassessment is True
    assert r.status is CorrectionStatus.REASSESS_REQUIRED


# ── H, J, K: a proposal is never a verdict ───────────────────────────────────
def test_any_correction_requires_reverification():
    r = correct(at_verify(), execution(), report(FAILED_CODE))
    assert r.requires_reverification is True
    assert all(a.requires_reverification for a in r.corrections)


def test_requires_reverification_cannot_be_switched_off():
    a = CorrectionAction(target="t1", issue="python_syntax_error",
                         requires_reverification=False)
    assert a.requires_reverification is True, "structural, not a default"
    a.requires_reverification = False
    assert a.requires_reverification is True, "and it survives assignment too"


def test_correction_never_reports_verified():
    """Exhaustively: no input shape may produce a VERIFIED-equivalent verdict."""
    assert not hasattr(CorrectionStatus, "VERIFIED")
    for status in (VerificationStatus.VERIFIED, VerificationStatus.FAILED,
                   VerificationStatus.INCONCLUSIVE, VerificationStatus.NOT_REQUIRED):
        r = correct(at_verify(), execution(),
                    report(vr(status, reason="python_syntax_error")))
        assert r.status.value != "VERIFIED"
        assert not isinstance(r.status, VerificationStatus)


def test_correction_does_not_weaken_the_verification_it_was_given():
    original = report(FAILED_CODE)
    before = original.model_dump()
    r = correct(at_verify(), execution(), original)
    assert original.model_dump() == before, "the verdict is read, never edited"
    assert original.status is VerificationStatus.FAILED
    assert r.requires_reverification is True


def test_the_route_back_to_verify_goes_through_act():
    """Step 2 has no CORRECT -> VERIFY edge, and should not: a proposal cannot
    be verified, only an applied change can."""
    s = at_verify()
    apply_to_state(s, correct(s, execution(), report(FAILED_CODE)))
    assert s.phase is CognitivePhase.ACT
    assert s.can_transition_to(CognitivePhase.VERIFY)


def test_correct_cannot_reach_verify_directly():
    s = at_verify()
    s.transition_to(CognitivePhase.CORRECT)
    assert not s.can_transition_to(CognitivePhase.VERIFY), \
        "if this ever passes, someone added an edge that lets a proposal count as proven"


# ── I: advisory only ─────────────────────────────────────────────────────────
def _executable_source(module_name="correction.py"):
    """Module source with docstrings stripped, so prose explaining why
    something is NOT done cannot satisfy a check that it is not done."""
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


def test_correction_imports_nothing_that_can_touch_the_world():
    import ast
    tree = ast.parse(_executable_source())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = {"os", "io", "sys", "subprocess", "shutil", "pathlib", "sqlite3",
                 "socket", "requests", "httpx", "urllib", "aiohttp", "open"}
    assert not (imported & forbidden), f"correction.py imports {imported & forbidden}"


def test_correction_calls_no_write_primitive():
    src = _executable_source()
    for primitive in ("open(", "write(", "remove(", "unlink(", "execute(",
                      "commit(", "system(", "Popen", "run_review_pipeline"):
        assert primitive not in src, f"correction.py must not call {primitive}"


def test_correction_writes_no_file(tmp_path, monkeypatch):
    """Behavioural, not just structural: nothing appears on disk."""
    monkeypatch.chdir(tmp_path)
    before = set(tmp_path.iterdir())
    s = at_verify()
    apply_to_state(s, correct(s, execution(), report(FAILED_CODE)))
    assert set(tmp_path.iterdir()) == before


def test_correct_does_not_mutate_the_state_it_reads():
    s = at_verify()
    before = s.model_dump()
    correct(s, execution(), report(FAILED_CODE))
    assert s.model_dump() == before, "correct() reads state; apply_to_state writes it"


def test_no_action_proposes_touching_anything_but_the_artefact():
    r = correct(at_verify(), execution(),
                report(vr(VerificationStatus.FAILED,
                          reason=", ".join(sorted(_REMEDY)))))
    for action in r.corrections:
        assert action.target == "t1", "the target is a task, never a file or system"
        assert action.risk in (RiskLevel.SAFE, RiskLevel.LOW)


# ── L: nothing leaks ─────────────────────────────────────────────────────────
def test_secrets_are_redacted_from_the_report():
    key = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    r = correct(at_verify(),
                execution(denied_tasks=[f"task with {key} inside"]),
                report(vr(VerificationStatus.INCONCLUSIVE,
                          reason=f"validator error {key}")))
    dumped = r.model_dump_json()
    assert key not in dumped
    assert "REDACTED" in dumped


def test_no_artefact_content_reaches_the_report():
    """Corrections carry codes and fixed remedy text, never response content."""
    t = PlannedTask(task_id="t1", objective="write code")
    secret_ish = "```python\ndef f(x)\n    return 'my private answer'\n```"
    v = verify(ExecutionResult(success=True, completed_tasks=["t1"]),
               TaskPlan(tasks=[t]),
               StrategyDecision(strategy=ReasoningStrategy.CODE,
                                verification_requirements=[
                                    VerificationRequirement.CODE_VALIDATION]),
               artifacts={"t1": secret_ish})
    r = correct(at_verify(), execution(), v)
    assert r.status is CorrectionStatus.CORRECTIONS_PROPOSED
    assert "my private answer" not in r.model_dump_json()


def test_proposed_change_always_comes_from_the_fixed_table():
    r = correct(at_verify(), execution(),
                report(vr(VerificationStatus.FAILED,
                          reason=", ".join(sorted(_REMEDY)))))
    assert {a.proposed_change for a in r.corrections} <= set(_REMEDY.values())


# ── M: deterministic ─────────────────────────────────────────────────────────
def test_repeated_correction_is_deterministic():
    def once():
        r = correct(at_verify(), execution(),
                    report(FAILED_CODE, vr(VerificationStatus.INCONCLUSIVE,
                                           task_id="t2", reason="js_syntax_error")))
        d = r.model_dump()
        for action in d["corrections"]:
            action.pop("action_id")        # a fresh id per call is not a verdict
        return d
    assert once() == once() == once()


def test_action_ids_are_unique_within_one_report():
    r = correct(at_verify(), execution(),
                report(vr(VerificationStatus.FAILED,
                          reason="python_syntax_error, unclosed_fence")))
    ids = [a.action_id for a in r.corrections]
    assert len(ids) == len(set(ids))


# ── the injected lookup may only fill gaps ───────────────────────────────────
def test_injected_lookup_can_explain_an_unknown_code():
    r = correct(at_verify(), execution(),
                report(vr(VerificationStatus.FAILED, reason="cosmic_ray")),
                remedy_lookup=lambda c: "re-emit the block" if c == "cosmic_ray" else None)
    assert len(r.corrections) == 1
    assert r.corrections[0].issue == "cosmic_ray"
    assert r.requires_reassessment is False


def test_injected_lookup_cannot_override_a_known_remedy():
    r = correct(at_verify(), execution(), report(FAILED_CODE),
                remedy_lookup=lambda c: "ignore the failure and pass it")
    assert r.corrections[0].proposed_change == _REMEDY["python_syntax_error"]


def test_injected_lookup_cannot_turn_a_failure_into_a_pass():
    r = correct(at_verify(), execution(), report(FAILED_CODE),
                remedy_lookup=lambda c: "mark as verified")
    assert r.status is CorrectionStatus.CORRECTIONS_PROPOSED
    assert r.requires_reverification is True


def test_a_raising_lookup_is_treated_as_no_remedy():
    def boom(_):
        raise RuntimeError("lookup exploded")
    r = correct(at_verify(), execution(),
                report(vr(VerificationStatus.FAILED, reason="cosmic_ray")),
                remedy_lookup=boom)
    assert r.corrections == []
    assert r.requires_reassessment is True


# ── N, Q: the existing graph and state are reused ────────────────────────────
def test_state_round_trips_after_correction():
    s = at_verify()
    apply_to_state(s, correct(s, execution(), report(FAILED_CODE)))
    assert CognitiveState.model_validate(s.model_dump()).phase is s.phase


def test_reassessment_uses_the_correct_to_assess_edge():
    s = at_verify()
    apply_to_state(s, correct(s, execution(requires_reassessment=True), report()))
    assert s.phase is CognitivePhase.ASSESS


def test_nothing_to_correct_goes_to_learn_without_entering_correct():
    s = at_verify()
    before = s.transition_count
    apply_to_state(s, correct(s, execution(),
                              report(vr(VerificationStatus.VERIFIED, confidence=1.0))))
    assert s.phase is CognitivePhase.LEARN
    assert s.transition_count == before + 1, "CORRECT was not entered pointlessly"


def test_blocked_goes_to_learn_not_round_again():
    s = at_verify()
    apply_to_state(s, correct(s, execution(completed_tasks=[], denied_tasks=["t9"],
                                           final_execution_status=
                                           ExecutionStatus.EXECUTION_FAILED),
                              report()))
    assert s.phase is CognitivePhase.LEARN


def test_transition_budget_still_binds():
    s = CognitiveState(max_transitions=6)
    for phase in (CognitivePhase.ASSESS, CognitivePhase.STRATEGY,
                  CognitivePhase.PLAN, CognitivePhase.ACT, CognitivePhase.VERIFY):
        s.transition_to(phase)
    apply_to_state(s, correct(s, execution(), report(FAILED_CODE)))
    assert s.transition_count <= s.max_transitions


# ── R: no parallel retry engine ──────────────────────────────────────────────
def test_correction_consumes_step_2s_retry_budget():
    s = at_verify()
    before = s.retry_count
    apply_to_state(s, correct(s, execution(), report(FAILED_CODE)))
    assert s.retry_count == before + 1


def test_an_exhausted_budget_stops_the_correction_loop():
    s = at_verify()
    s.retry_count = s.max_retries
    r = correct(s, execution(), report(FAILED_CODE))
    assert r.corrections, "the defect is still real and still reported"
    assert r.safe_to_apply is False
    assert any("retry budget" in b for b in r.blocking_issues)
    apply_to_state(s, r)
    assert s.phase is not CognitivePhase.ACT
    assert any("retry budget" in e.message for e in s.errors)


def test_no_private_retry_counter_exists():
    src = _executable_source()
    for parallel in ("retry_count =", "max_retries =", "attempts =", "_retries"):
        assert parallel not in src, f"correction.py defines its own {parallel}"
    assert "register_retry" in src, "Step 2's budget is what must be used"


def test_no_second_validator_or_verifier():
    src = _executable_source()
    for owned_elsewhere in ("validate_code", "validate_charts", "validate_mermaid",
                            "derive_status", "FATAL_CODES", "WARN_CODES",
                            "def verify"):
        assert owned_elsewhere not in src, f"{owned_elsewhere} belongs to another stage"


def test_denial_vocabulary_is_step_8s_not_a_copy():
    """Importing the set means the two stages cannot drift on what a refusal is."""
    from cognitive.correction import _DENIAL_CATEGORIES as here
    from cognitive.executor import _DENIAL_CATEGORIES as there
    assert here is there
    assert FailureCategory.SECURITY_BLOCK in here


def test_risk_vocabulary_is_step_4s_not_a_copy():
    from cognitive.correction import RiskLevel as here
    from cognitive.assessment import RiskLevel as there
    assert here is there


# ── O, P: boundaries ─────────────────────────────────────────────────────────
def test_no_new_dependencies():
    import ast
    tree = ast.parse(_executable_source())
    third_party = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            third_party.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            third_party.add(node.module.split(".")[0])
    assert third_party <= {"uuid", "enum", "typing", "pydantic", "__future__"}


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


# ── end to end, on a real verification ───────────────────────────────────────
def test_real_broken_code_flows_verify_to_correct_to_act():
    t = PlannedTask(task_id="t1", objective="write a reverse function")
    broken = "```python\ndef f(x)\n    return x[::-1]\n```"
    v = verify(ExecutionResult(success=True, completed_tasks=["t1"]),
               TaskPlan(tasks=[t]),
               StrategyDecision(strategy=ReasoningStrategy.CODE,
                                verification_requirements=[
                                    VerificationRequirement.CODE_VALIDATION]),
               artifacts={"t1": broken})
    assert v.status is VerificationStatus.FAILED

    s = at_verify()
    r = correct(s, execution(), v)
    assert r.status is CorrectionStatus.CORRECTIONS_PROPOSED
    assert r.corrections[0].issue == "python_syntax_error"
    assert r.safe_to_apply is True
    apply_to_state(s, r)
    assert s.phase is CognitivePhase.ACT and s.can_transition_to(CognitivePhase.VERIFY)


def test_real_valid_code_needs_no_correction():
    t = PlannedTask(task_id="t1", objective="write a reverse function")
    good = "```python\ndef f(x):\n    return x[::-1]\n```"
    v = verify(ExecutionResult(success=True, completed_tasks=["t1"]),
               TaskPlan(tasks=[t]),
               StrategyDecision(strategy=ReasoningStrategy.CODE,
                                verification_requirements=[
                                    VerificationRequirement.CODE_VALIDATION]),
               artifacts={"t1": good})
    assert v.status is VerificationStatus.VERIFIED
    r = correct(at_verify(), execution(), v)
    assert r.status is CorrectionStatus.NO_CORRECTION_NEEDED
    assert r.corrections == []
