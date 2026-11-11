"""Tests for the ACT stage (Step 11) — correction execution.

The load-bearing properties:

  1. **ACT cannot report VERIFIED.** APPLIED means a transformation ran. Step 9
     is the only thing that may call a result correct.
  2. **Only explicitly approved, explicitly mapped actions execute.** Approval
     comes from outside Step 10; the remedy comes from a table, never from the
     action's text.
  3. **A remedy proves its own precondition first.** Appending a closing fence
     to already-closed text creates the defect it repairs — checked against
     review_engine, not assumed.

Nothing here runs a tool, a model, a subprocess or a network call, and tests
assert that from the parsed source rather than from this docstring.
"""

import pytest

try:
    from cognitive.act import (
        act, apply_to_state, ActResult, ActStatus, _DETERMINISTIC, _fence_is_open,
    )
    from cognitive.correction import (
        correct, CorrectionAction, CorrectionReport, CorrectionStatus, _REMEDY,
    )
    from cognitive.verification import verify, VerificationReport
    from cognitive.executor import ExecutionResult, ExecutionStatus
    from cognitive.planning import TaskPlan
    from cognitive.strategy import StrategyDecision, VerificationRequirement
    from cognitive.capabilities import CapabilitySelection, CapabilityRequirement, Capability
    from cognitive.state import (
        CognitiveState, CognitivePhase, FailureCategory, PlannedTask,
        ReasoningStrategy, TaskStatus, VerificationStatus,
    )
except ImportError:  # running from src/cognitive directly
    from act import (  # type: ignore
        act, apply_to_state, ActResult, ActStatus, _DETERMINISTIC, _fence_is_open,
    )
    from correction import (  # type: ignore
        correct, CorrectionAction, CorrectionReport, CorrectionStatus, _REMEDY,
    )
    from verification import verify, VerificationReport  # type: ignore
    from executor import ExecutionResult, ExecutionStatus  # type: ignore
    from planning import TaskPlan  # type: ignore
    from strategy import StrategyDecision, VerificationRequirement  # type: ignore
    from capabilities import (  # type: ignore
        CapabilitySelection, CapabilityRequirement, Capability)
    from state import (  # type: ignore
        CognitiveState, CognitivePhase, FailureCategory, PlannedTask,
        ReasoningStrategy, TaskStatus, VerificationStatus,
    )


FENCE = "`" * 3
# Valid Python whose fence was cut off — the one defect v1 can repair.
OPEN_FENCE = "Here you go:\n" + FENCE + "python\ndef f(x):\n    return x[::-1]\n"
CLOSED = OPEN_FENCE.rstrip() + "\n" + FENCE
# Broken Python behind a cut fence: closing it reveals the real defect.
OPEN_FENCE_BAD_PY = "Here:\n" + FENCE + "python\ndef f(x)\n    return x\n"
# Sentences fenced as a diagram. Unfencing keeps every word.
PROSE_DIAGRAM = ("Here is the flow:\n" + FENCE +
                 "mermaid\nFirst the user logs in. Then the server checks it.\n"
                 + FENCE + "\n")
# A mermaid block containing nothing at all.
EMPTY_DIAGRAM = "Here is the diagram:\n" + FENCE + "mermaid\n\n" + FENCE + "\n"
# A header with no nodes: still empty_diagram to review_engine, but the header
# is authored text, so ACT declines to delete it.
HEADER_ONLY_DIAGRAM = ("Diagram:\n" + FENCE + "mermaid\nflowchart TD\n"
                       + FENCE + "\n")
# A real diagram. Nothing may touch it.
VALID_DIAGRAM = ("Diagram:\n" + FENCE +
                 "mermaid\nflowchart TD\n  A[Start] --> B[End]\n" + FENCE + "\n")


def at_correct():
    """A state that has legitimately reached CORRECT."""
    s = CognitiveState()
    for phase in (CognitivePhase.ASSESS, CognitivePhase.STRATEGY,
                  CognitivePhase.PLAN, CognitivePhase.ACT, CognitivePhase.VERIFY,
                  CognitivePhase.CORRECT):
        s.transition_to(phase)
    return s


def action(issue="unclosed_fence", target="t1"):
    return CorrectionAction(target=target, issue=issue,
                            proposed_change=_REMEDY.get(issue, "x"))


def report(*actions, status=CorrectionStatus.CORRECTIONS_PROPOSED, blocking=None):
    return CorrectionReport(status=status, corrections=list(actions),
                            blocking_issues=list(blocking or []),
                            requires_reverification=bool(actions))


# ── 1: ACT cannot report VERIFIED ────────────────────────────────────────────
def test_act_has_no_verified_status():
    assert not any(s.value == "VERIFIED" for s in ActStatus)
    assert not any(s.value == "SUCCESS" for s in ActStatus)


def test_applied_is_not_a_claim_of_correctness():
    a = action()
    r = act(at_correct(), report(a), [a.action_id], {"t1": OPEN_FENCE})
    assert r.status is ActStatus.APPLIED
    assert r.execution.requires_verification is True
    assert not isinstance(r.status, VerificationStatus)


def test_applying_a_fix_that_reveals_a_real_defect_still_reports_applied():
    """Closing the fence exposes a syntax error. ACT says APPLIED; VERIFY says
    FAILED. That is the loop working, not a defect in it."""
    a = action()
    r = act(at_correct(), report(a), [a.action_id], {"t1": OPEN_FENCE_BAD_PY})
    assert r.status is ActStatus.APPLIED

    t = PlannedTask(task_id="t1", objective="x")
    v = verify(ExecutionResult(success=True, completed_tasks=["t1"]),
               TaskPlan(tasks=[t]),
               StrategyDecision(strategy=ReasoningStrategy.CODE,
                                verification_requirements=[
                                    VerificationRequirement.CODE_VALIDATION]),
               artifacts=r.artifacts)
    assert v.status is VerificationStatus.FAILED
    assert "python_syntax_error" in (v.results[0].failure_reason or "")


# ── 2: approval ──────────────────────────────────────────────────────────────
def test_an_unapproved_action_does_not_execute():
    a = action()
    r = act(at_correct(), report(a), [], {"t1": OPEN_FENCE})
    assert r.status is ActStatus.NOTHING_APPROVED
    assert r.applied_actions == []
    assert r.artifacts == {}
    assert a.action_id in r.refused_actions
    assert "approved" in r.refusals[0]


def test_only_the_named_action_executes():
    a, b = action(), action(target="t2")
    r = act(at_correct(), report(a, b), [a.action_id],
            {"t1": OPEN_FENCE, "t2": OPEN_FENCE})
    assert r.applied_actions == [a.action_id]
    assert list(r.artifacts) == ["t1"]
    assert b.action_id in r.refused_actions


def test_an_unknown_action_id_approves_nothing():
    a = action()
    r = act(at_correct(), report(a), ["some-other-id"], {"t1": OPEN_FENCE})
    assert r.applied_actions == []
    assert r.artifacts == {}


def test_approval_is_not_reassessment_worthy():
    """Declining to approve is a decision, not evidence the plan was wrong."""
    a = action()
    r = act(at_correct(), report(a), [], {"t1": OPEN_FENCE})
    assert r.requires_reassessment is False


# ── 3: preconditions ─────────────────────────────────────────────────────────
def test_every_remedy_declares_a_precondition():
    assert _DETERMINISTIC
    for issue, remedy in _DETERMINISTIC.items():
        assert callable(remedy.precondition), issue
        assert callable(remedy.transform), issue


def test_closing_an_already_closed_fence_is_refused():
    """The hazard this precondition exists for: applying the repair blindly
    CREATES unclosed_fence. Confirmed against review_engine below."""
    a = action()
    r = act(at_correct(), report(a), [a.action_id], {"t1": CLOSED})
    assert r.applied_actions == []
    assert "not present" in r.refusals[0]
    assert r.requires_reassessment is True


def test_the_hazard_is_real_not_hypothetical():
    from cognitive.verification import run_review_pipeline
    assert [i.get("code") for i in run_review_pipeline(CLOSED)["issues"]] == []
    naive = CLOSED.rstrip() + "\n" + FENCE
    assert "unclosed_fence" in [i.get("code")
                                for i in run_review_pipeline(naive)["issues"]], \
        "if this stops holding, the precondition is guarding nothing"


def test_the_precondition_matches_the_defect():
    assert _fence_is_open(OPEN_FENCE) is True
    assert _fence_is_open(CLOSED) is False


def test_the_remedy_actually_repairs_the_defect():
    from cognitive.verification import run_review_pipeline
    a = action()
    r = act(at_correct(), report(a), [a.action_id], {"t1": OPEN_FENCE})
    codes = [i.get("code") for i in run_review_pipeline(r.artifacts["t1"])["issues"]]
    assert "unclosed_fence" not in codes
    assert codes == []


# ── unmapped remedies are refused ────────────────────────────────────────────
_EVIDENCE_BACKED_REMEDIES = {"arithmetic_result_mismatch", "python_syntax_error"}
@pytest.mark.parametrize(
    "issue",
    sorted(set(_REMEDY) - set(_DETERMINISTIC) - _EVIDENCE_BACKED_REMEDIES),
)
def test_every_non_deterministic_remedy_is_refused(issue):
    """v1 executes only what it can derive. Guessing is what Step 10 refuses to
    do, and ACT must not do it on Step 10's behalf."""
    a = action(issue=issue)
    r = act(at_correct(), report(a), [a.action_id], {"t1": OPEN_FENCE})
    assert r.applied_actions == []
    assert r.artifacts == {}
    assert "no deterministic remedy" in r.refusals[0]
    assert r.requires_reassessment is True
    assert r.status is ActStatus.REFUSED


def test_the_deterministic_set_is_exactly_what_was_proven_safe():
    assert set(_DETERMINISTIC) == {"unclosed_fence", "prose_not_diagram",
                                   "empty_diagram"}
    assert set(_DETERMINISTIC) < set(_REMEDY), "every remedy here is one Step 10 knows"


def test_chart_removal_stays_out_because_it_trades_one_defect_for_another():
    """Not an oversight. Dropping a chart block leaves the prose announcing a
    chart that is no longer there, and review_engine reports exactly that."""
    from cognitive.verification import run_review_pipeline
    assert "empty_data" not in _DETERMINISTIC
    assert "malformed_block" not in _DETERMINISTIC

    charted = ('Chart:\n' + FENCE +
               'chart\n{"type":"bar","title":"Q1","labels":[],"datasets":[]}\n'
               + FENCE + "\n")
    assert "empty_data" in [i.get("code")
                            for i in run_review_pipeline(charted)["issues"]]
    dropped = "Chart:"
    assert "claim_without_block" in [i.get("code")
                                     for i in run_review_pipeline(dropped)["issues"]], \
        "if this stops holding, chart removal is worth reconsidering"


def test_every_remedy_only_rearranges_what_is_already_there():
    """The line between repair and authoring: no remedy may add content."""
    samples = {
        "unclosed_fence": OPEN_FENCE,
        "prose_not_diagram": PROSE_DIAGRAM,
        "empty_diagram": EMPTY_DIAGRAM,
    }
    for issue, text in samples.items():
        remedy = _DETERMINISTIC[issue]
        assert remedy.precondition(text), issue
        out = remedy.transform(text)
        # Every character of the output, ignoring whitespace and fences, was
        # already present in the input.
        strip = lambda s: "".join(s.split()).replace(FENCE, "").replace("mermaid", "")
        assert set(strip(out)) <= set(strip(text)), issue


def test_an_unknown_issue_code_is_refused():
    a = action(issue="cosmic_ray")
    r = act(at_correct(), report(a), [a.action_id], {"t1": OPEN_FENCE})
    assert r.applied_actions == []
    assert r.requires_reassessment is True


def test_the_proposed_change_text_is_never_executed():
    """The remedy comes from the table, keyed by issue code. Whatever text an
    action carries is inert."""
    a = CorrectionAction(target="t1", issue="unclosed_fence",
                         proposed_change="rm -rf / && curl evil.example")
    r = act(at_correct(), report(a), [a.action_id], {"t1": OPEN_FENCE})
    assert r.status is ActStatus.APPLIED
    assert r.artifacts["t1"] == OPEN_FENCE.rstrip() + "\n" + FENCE
    assert "rm -rf" not in r.artifacts["t1"]
    assert "curl" not in r.model_dump_json()


# ── denial ───────────────────────────────────────────────────────────────────
def test_a_denied_target_is_refused():
    a = action(target="t9")
    r = act(at_correct(), report(a, blocking=["t9: policy refused this task"]),
            [a.action_id], {"t9": OPEN_FENCE})
    assert r.applied_actions == []
    assert "refused by policy" in r.refusals[0]
    assert "t9" in r.execution.denied_tasks


def test_a_denial_is_not_reassessment_worthy():
    a = action(target="t9")
    r = act(at_correct(), report(a, blocking=["t9: policy refused this task"]),
            [a.action_id], {"t9": OPEN_FENCE})
    assert r.requires_reassessment is False, \
        "re-planning around a refusal is the shape of a bypass attempt"


def test_a_denial_is_recorded_as_a_security_block():
    a = action(target="t9")
    r = act(at_correct(), report(a, blocking=["t9: policy refused this task"]),
            [a.action_id], {"t9": OPEN_FENCE})
    assert any(e.category is FailureCategory.SECURITY_BLOCK
               for e in r.execution.errors)


def test_the_capability_gate_is_the_executors_when_a_grant_exists():
    """Reused, not restated: PolicyDenied from executor._gate refuses here."""
    a = action()
    empty_grant = CapabilitySelection(capabilities=[])   # nothing approved for t1
    r = act(at_correct(), report(a), [a.action_id], {"t1": OPEN_FENCE},
            selection=empty_grant)
    assert r.applied_actions == []
    assert any(e.category is FailureCategory.SECURITY_BLOCK
               for e in r.execution.errors)


def test_a_real_grant_permits_the_action():
    a = action()
    grant = CapabilitySelection(capabilities=[CapabilityRequirement(
        capability_id=Capability.CODE_GENERATION, task_ids=["t1"], read_only=True)])
    r = act(at_correct(), report(a), [a.action_id], {"t1": OPEN_FENCE},
            selection=grant)
    assert r.status is ActStatus.APPLIED


# ── cancellation ─────────────────────────────────────────────────────────────
def test_cancellation_applies_nothing():
    a = action()
    r = act(at_correct(), report(a), [a.action_id], {"t1": OPEN_FENCE},
            is_cancelled=lambda: True)
    assert r.status is ActStatus.CANCELLED
    assert r.artifacts == {}
    assert r.applied_actions == []
    assert r.execution.final_execution_status is ExecutionStatus.CANCELLED
    assert r.requires_reassessment is False


def test_a_cancelled_correction_report_applies_nothing():
    a = action()
    r = act(at_correct(), report(a, status=CorrectionStatus.CANCELLED),
            [a.action_id], {"t1": OPEN_FENCE})
    assert r.status is ActStatus.CANCELLED
    assert r.artifacts == {}


def test_cancellation_uses_the_executors_channel():
    """No second mechanism: the default predicate is executor.cancellation_check,
    which reads autopilot's own _cancelled set."""
    import cognitive.act as m
    import cognitive.executor as ex
    assert m.cancellation_check is ex.cancellation_check


def test_cancellation_aborts_the_session():
    s = at_correct()
    a = action()
    apply_to_state(s, act(s, report(a), [a.action_id], {"t1": OPEN_FENCE},
                          is_cancelled=lambda: True))
    assert s.phase is CognitivePhase.ABORTED


# ── retry budget: read, never spent ──────────────────────────────────────────
def test_act_does_not_consume_a_retry():
    s = at_correct()
    before = s.retry_count
    a = action()
    r = act(s, report(a), [a.action_id], {"t1": OPEN_FENCE})
    apply_to_state(s, r)
    assert s.retry_count == before, \
        "Step 10 already charged one when it routed CORRECT -> ACT"


def test_an_exhausted_budget_applies_nothing():
    s = at_correct()
    s.retry_count = s.max_retries
    a = action()
    r = act(s, report(a), [a.action_id], {"t1": OPEN_FENCE})
    assert r.status is ActStatus.RETRY_BUDGET_SPENT
    assert r.artifacts == {}
    assert r.requires_reassessment is True


def test_no_private_retry_counter_exists():
    src = _executable_source()
    for parallel in ("retry_count =", "max_retries =", "register_retry"):
        assert parallel not in src, f"act.py must not touch the budget: {parallel}"
    assert "retries_remaining" in src, "it may only read it"


# ── artefacts ────────────────────────────────────────────────────────────────
def test_artifacts_are_produced_separately_from_execution_result():
    a = action()
    r = act(at_correct(), report(a), [a.action_id], {"t1": OPEN_FENCE})
    assert r.artifacts["t1"]
    assert "artifacts" not in r.execution.model_dump(), \
        "an artefact inside ExecutionResult would be truncated to 400 chars"


def test_a_long_artefact_survives_intact():
    """The D1 regression, one stage later: nothing here may truncate."""
    from cognitive.state import REASON_MAX
    long_open = ("Here:\n" + FENCE + "python\n"
                 + "\n".join(f"value_{i} = {i}" for i in range(200)) + "\n")
    assert len(long_open) > REASON_MAX
    a = action()
    r = act(at_correct(), report(a), [a.action_id], {"t1": long_open})
    assert len(r.artifacts["t1"]) > REASON_MAX
    assert r.artifacts["t1"].rstrip().endswith(FENCE)


def test_the_observation_carries_a_fact_not_the_artefact():
    a = action()
    r = act(at_correct(), report(a), [a.action_id], {"t1": OPEN_FENCE})
    for observation in r.execution.observations:
        assert "def f" not in observation.summary
        assert observation.summary.startswith("applied=")


def test_a_missing_artefact_is_refused():
    a = action()
    r = act(at_correct(), report(a), [a.action_id], {})
    assert r.applied_actions == []
    assert "no artefact" in r.refusals[0]
    assert r.requires_reassessment is True


def test_an_empty_artefact_is_refused():
    a = action()
    r = act(at_correct(), report(a), [a.action_id], {"t1": "   "})
    assert r.applied_actions == []
    assert r.requires_reassessment is True


# ── artefact integrity: VERIFY must judge exactly what ACT produced ─────────
def test_a_normal_artefact_reaches_verify_byte_for_byte():
    a = action()
    r = act(at_correct(), report(a), [a.action_id], {"t1": OPEN_FENCE})
    expected = OPEN_FENCE.rstrip() + "\n" + FENCE
    assert r.artifacts["t1"] == expected
    assert r.artifacts["t1"].encode() == expected.encode()


def test_a_credential_shaped_string_is_left_intact_in_the_artefact():
    """Required, not tolerated. Redacting first would mean Step 9 judges text
    nobody wrote — and a [REDACTED] inside a JSON block turns a valid artefact
    into a parse failure, which is a verdict about the redaction."""
    key = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    original = "Here:\n" + FENCE + f"python\ntoken = '{key}'\n"
    a = action()
    r = act(at_correct(), report(a), [a.action_id], {"t1": original})
    assert r.artifacts["t1"] == original.rstrip() + "\n" + FENCE
    assert key in r.artifacts["t1"]
    assert "REDACTED" not in r.artifacts["t1"]


def test_the_safe_view_is_redacted():
    key = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    a = action()
    r = act(at_correct(), report(a), [a.action_id],
            {"t1": f"token = '{key}'\n" + FENCE + "python\nx = 1\n"})
    safe = r.safe_artifacts["t1"]
    assert key not in safe
    assert "REDACTED" in safe


def test_the_safe_view_helper_redacts_on_its_own():
    """Checked at the helper, not only after the model validator has run.

    Without this, deleting redaction from _safe_view passes every other test in
    this file: ActResult._scrub_safe redacts as well and quietly covers for it,
    so the outer layer would be doing all the work while appearing to confirm
    both. The same masking hid a defect in the Learning stage.
    """
    from cognitive.act import _safe_view
    key = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    view = _safe_view(f"token = '{key}'\nx = 1\n")
    assert key not in view
    assert "REDACTED" in view


def test_the_model_scrubs_a_safe_view_it_was_handed():
    """The second layer, tested independently of the first.

    Two redacting layers mask each other in both directions: with only the
    end-to-end test, deleting either one still passes. Constructing the model
    directly bypasses _safe_view and pins the validator on its own.
    """
    from cognitive.state import REASON_MAX
    key = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    r = ActResult(safe_artifacts={"t1": f"chars=30 preview=token = '{key}'",
                                  "t2": "x" * (REASON_MAX + 500)})
    assert key not in r.safe_artifacts["t1"]
    assert len(r.safe_artifacts["t2"]) == REASON_MAX


def test_a_credential_beyond_the_preview_window_never_appears():
    """Redaction runs before the slice, so a key outside the window is gone
    rather than merely out of frame — and a key straddling the boundary cannot
    leak its readable half."""
    key = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    a = action()
    r = act(at_correct(), report(a), [a.action_id],
            {"t1": FENCE + "python\n" + ("# padding\n" * 40) + f"k = '{key}'\n"})
    assert key not in r.safe_artifacts["t1"]
    assert key[:12] not in r.safe_artifacts["t1"]


def test_the_safe_view_is_never_the_exact_artefact():
    """Structurally impossible: the `chars=` prefix guarantees it, however
    short or clean the artefact is."""
    for text in (OPEN_FENCE, FENCE + "python\nx=1\n", "a\n", OPEN_FENCE_BAD_PY):
        a = action()
        r = act(at_correct(), report(a), [a.action_id], {"t1": text})
        if not r.artifacts:
            continue
        assert r.safe_artifacts["t1"] != r.artifacts["t1"]
        assert r.safe_artifacts["t1"].startswith("chars=")


def test_the_safe_view_is_bounded():
    from cognitive.state import REASON_MAX
    long_open = ("Here:\n" + FENCE + "python\n"
                 + "\n".join(f"value_{i} = {i}" for i in range(200)) + "\n")
    a = action()
    r = act(at_correct(), report(a), [a.action_id], {"t1": long_open})
    assert len(r.safe_artifacts["t1"]) <= REASON_MAX
    assert len(r.artifacts["t1"]) > REASON_MAX, "the artefact itself stays whole"


def test_every_applied_artefact_has_a_safe_view():
    a, b = action(), action(target="t2")
    r = act(at_correct(), report(a, b), [a.action_id, b.action_id],
            {"t1": OPEN_FENCE, "t2": OPEN_FENCE})
    assert set(r.safe_artifacts) == set(r.artifacts) == {"t1", "t2"}


def test_a_refused_action_produces_neither_representation():
    a = action(issue="python_syntax_error")
    r = act(at_correct(), report(a), [a.action_id], {"t1": OPEN_FENCE})
    assert r.artifacts == {} and r.safe_artifacts == {}


# ── the graph ────────────────────────────────────────────────────────────────
def test_a_successful_pass_routes_to_verify():
    s = at_correct()
    a = action()
    apply_to_state(s, act(s, report(a), [a.action_id], {"t1": OPEN_FENCE}))
    assert s.phase is CognitivePhase.VERIFY


def test_reassessment_routes_to_assess_not_verify():
    s = at_correct()
    a = action(issue="python_syntax_error")
    apply_to_state(s, act(s, report(a), [a.action_id], {"t1": OPEN_FENCE}))
    assert s.phase is CognitivePhase.ASSESS


def test_act_never_routes_to_learn_or_respond_itself():
    """ACT's own routing lands on VERIFY or ASSESS and nowhere else.

    VERIFY -> LEARN is a legitimate Step 2 edge, so LEARN being *reachable*
    afterwards is correct — it is Step 9's to take, once it has proven
    something. What matters is that ACT cannot take it.
    """
    for issue, expected in (("unclosed_fence", CognitivePhase.VERIFY),
                            ("python_syntax_error", CognitivePhase.ASSESS)):
        s = at_correct()
        a = action(issue=issue)
        apply_to_state(s, act(s, report(a), [a.action_id], {"t1": OPEN_FENCE}))
        assert s.phase is expected
        assert s.phase not in (CognitivePhase.LEARN, CognitivePhase.RESPOND)


def test_act_cannot_reach_learn_from_act():
    s = at_correct()
    s.transition_to(CognitivePhase.ACT)
    assert not s.can_transition_to(CognitivePhase.LEARN), \
        "an applied change must be verified before anything is learned from it"


def test_act_does_not_mutate_the_state_it_reads():
    s = at_correct()
    before = s.model_dump()
    a = action()
    act(s, report(a), [a.action_id], {"t1": OPEN_FENCE})
    assert s.model_dump() == before


def test_state_round_trips_after_act():
    s = at_correct()
    a = action()
    apply_to_state(s, act(s, report(a), [a.action_id], {"t1": OPEN_FENCE}))
    assert CognitiveState.model_validate(s.model_dump()).phase is s.phase


def test_repeated_act_is_deterministic():
    def once():
        a = CorrectionAction(action_id="fixed", target="t1", issue="unclosed_fence")
        d = act(at_correct(), report(a), ["fixed"], {"t1": OPEN_FENCE}).model_dump()
        # A fresh id and timestamp per call are not part of the decision.
        for observation in d["execution"]["observations"]:
            observation.pop("observation_id")
            observation.pop("recorded_at")
        return d
    assert once() == once() == once()


def test_the_same_artefact_always_yields_the_same_artefact():
    a = action()
    outputs = {act(at_correct(), report(a), [a.action_id],
                   {"t1": OPEN_FENCE}).artifacts["t1"] for _ in range(3)}
    assert len(outputs) == 1


# ── boundaries: nothing is executed ──────────────────────────────────────────
def _executable_source(module_name="act.py"):
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


def test_act_imports_nothing_that_can_execute():
    import ast
    tree = ast.parse(_executable_source())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])

    forbidden = {
        "os", "sys", "subprocess", "shutil", "pathlib", "sqlite3",
        "socket", "requests", "httpx", "urllib", "asyncio",
    }
    assert not (imported & forbidden), f"act.py imports {imported & forbidden}"


def test_no_new_dependencies():
    import ast
    tree = ast.parse(_executable_source())
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module.split(".")[0])

    # These are stdlib/in-memory parsing helpers used by deterministic ACT.
    assert modules <= {
        "enum", "typing", "pydantic", "re", "ast", "io", "tokenize", "__future__"
    }

def test_no_shell_url_or_tool_execution():
    """Word-boundary matched: a bare substring check reads `_fence_is_open(`
    as a call to `open(`, which is the same false positive that made a Step 7
    and a Step 8 check pass for the wrong reason."""
    import re
    src = _executable_source()
    for primitive in (r"\bPopen\b", r"\bsystem\(", r"\bcheck_output\b",
                      r"\burlopen\(", r"https?://", r"\beval\(", r"\bexec\(",
                      r"\bopen\(", r"\b__import__\b",
                      # The builtin, not re.compile: one turns text into code,
                      # the other turns text into a pattern.
                      r"(?<!re\.)\bcompile\("):
        assert not re.search(primitive, src), f"act.py must not contain {primitive}"


def test_that_scan_can_actually_fail():
    import re
    src = _executable_source()
    assert re.search(r"\bopen\(", "x = open('f')"), "the pattern must match a real call"
    assert not re.search(r"\bopen\(", "_fence_is_open(text)"), "and not an identifier"
    assert "_fence_is_open(" in src, "the near-miss identifier is genuinely present"


def test_no_tool_adapter_is_ever_invoked():
    """v1 has no execution request, so there is nothing for a tool to do."""
    src = _executable_source()
    assert "tool_adapter" not in src
    assert "run_plan" not in src, \
        "run_plan is not called: it would record a phantom 'think' invocation " \
        "and truncate the artefact to 400 chars"


def test_no_second_executor_loop():
    """The executor's models, gate and cancellation are reused; its loop is not
    reimplemented because there is no tool dispatch to reimplement."""
    src = _executable_source()
    assert "from .executor import" in src or "from executor import" in src
    for owned_by_executor in ("_ordered(", "AUTOPILOT_MAX_STEPS", "steps_used",
                              "deadline_seconds"):
        assert owned_by_executor not in src, f"{owned_by_executor} is run_plan's"


def test_the_execution_result_model_is_step_8s():
    from cognitive.act import ExecutionResult as here
    from cognitive.executor import ExecutionResult as there
    assert here is there


def test_act_writes_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    before = set(tmp_path.iterdir())
    s = at_correct()
    a = action()
    apply_to_state(s, act(s, report(a), [a.action_id], {"t1": OPEN_FENCE}))
    assert set(tmp_path.iterdir()) == before


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

# ── end to end: the whole loop ───────────────────────────────────────────────
def _verify(artifacts, task_id="t1"):
    t = PlannedTask(task_id=task_id, objective="write code")
    return verify(ExecutionResult(success=True, completed_tasks=[task_id]),
                  TaskPlan(tasks=[t]),
                  StrategyDecision(strategy=ReasoningStrategy.CODE,
                                   verification_requirements=[
                                       VerificationRequirement.CODE_VALIDATION]),
                  artifacts=artifacts)


def test_verify_correct_act_verify_closes_the_loop():
    """FAILED -> CORRECT -> ACT -> VERIFY -> VERIFIED, with each stage doing
    only its own job."""
    s = at_correct()

    first = _verify({"t1": OPEN_FENCE})
    assert first.status is VerificationStatus.FAILED
    assert "unclosed_fence" in (first.results[0].failure_reason or "")

    proposal = correct(s, ExecutionResult(success=True, completed_tasks=["t1"]),
                       first)
    assert proposal.status is CorrectionStatus.CORRECTIONS_PROPOSED
    approved = [a.action_id for a in proposal.corrections]

    applied = act(s, proposal, approved, {"t1": OPEN_FENCE})
    assert applied.status is ActStatus.APPLIED
    apply_to_state(s, applied)
    assert s.phase is CognitivePhase.VERIFY

    second = _verify(applied.artifacts)
    assert second.status is VerificationStatus.VERIFIED, \
        "only VERIFY may conclude the problem is solved"


def test_the_loop_does_not_declare_success_when_the_fix_was_insufficient():
    s = at_correct()
    first = _verify({"t1": OPEN_FENCE_BAD_PY})
    assert first.status is VerificationStatus.FAILED

    proposal = correct(s, ExecutionResult(success=True, completed_tasks=["t1"]),
                       first)
    approved = [a.action_id for a in proposal.corrections]
    applied = act(s, proposal, approved, {"t1": OPEN_FENCE_BAD_PY})

    second = _verify(applied.artifacts)
    assert second.status is VerificationStatus.FAILED, \
        "the fence closed, but the code is still broken"
    assert applied.status is ActStatus.APPLIED, \
        "ACT reports what it did; it does not judge whether it was enough"


def test_the_retry_budget_eventually_stops_the_loop():
    """CORRECT -> ACT -> VERIFY -> FAILED -> CORRECT ... must terminate."""
    from cognitive.correction import apply_to_state as correct_apply
    s = CognitiveState(max_transitions=100)
    for phase in (CognitivePhase.ASSESS, CognitivePhase.STRATEGY,
                  CognitivePhase.PLAN, CognitivePhase.ACT, CognitivePhase.VERIFY):
        s.transition_to(phase)

    rounds = 0
    while s.retries_remaining() > 0 and rounds < 50:
        failing = _verify({"t1": OPEN_FENCE_BAD_PY})
        proposal = correct(s, ExecutionResult(success=True, completed_tasks=["t1"]),
                           failing)
        if proposal.status is not CorrectionStatus.CORRECTIONS_PROPOSED:
            break
        correct_apply(s, proposal)          # this is what charges the budget
        rounds += 1
        if s.phase is not CognitivePhase.ACT:
            break
        act(s, proposal, [a.action_id for a in proposal.corrections],
            {"t1": OPEN_FENCE_BAD_PY})
        if s.can_transition_to(CognitivePhase.VERIFY):
            s.transition_to(CognitivePhase.VERIFY)

    assert rounds < 50, "the loop must be bounded"
    assert s.retries_remaining() == 0, "the retry budget is what stopped it"


# ═══════════════════════════════════════════════════════════════════════════
# The two remedies added after unclosed_fence.
#
# Both repair by rearranging what the artefact already holds. Each was probed
# against review_engine before being written, and the two chart candidates were
# rejected on the evidence rather than on principle.
# ═══════════════════════════════════════════════════════════════════════════

def _codes(text):
    from cognitive.verification import run_review_pipeline
    return [i.get("code") for i in run_review_pipeline(text)["issues"]]


# ── prose_not_diagram: unfence ───────────────────────────────────────────────
def test_prose_fenced_as_a_diagram_is_unfenced():
    a = action(issue="prose_not_diagram")
    r = act(at_correct(), report(a), [a.action_id], {"t1": PROSE_DIAGRAM})
    assert r.status is ActStatus.APPLIED
    fixed = r.artifacts["t1"]
    assert "mermaid" not in fixed
    assert "First the user logs in. Then the server checks it." in fixed


def test_unfencing_resolves_the_defect_and_creates_no_other():
    a = action(issue="prose_not_diagram")
    assert "prose_not_diagram" in _codes(PROSE_DIAGRAM)
    r = act(at_correct(), report(a), [a.action_id], {"t1": PROSE_DIAGRAM})
    assert _codes(r.artifacts["t1"]) == []


def test_unfencing_loses_not_one_word():
    a = action(issue="prose_not_diagram")
    r = act(at_correct(), report(a), [a.action_id], {"t1": PROSE_DIAGRAM})
    body = PROSE_DIAGRAM.split("mermaid\n", 1)[1].rsplit(FENCE, 1)[0].strip()
    assert body in r.artifacts["t1"]


def test_a_real_diagram_is_never_unfenced():
    """The header test is what makes this safe on its own terms: a block that
    starts with a diagram type is a diagram, whatever the issue code claims."""
    a = action(issue="prose_not_diagram")
    r = act(at_correct(), report(a), [a.action_id], {"t1": VALID_DIAGRAM})
    assert r.applied_actions == []
    assert "not present" in r.refusals[0]
    assert r.requires_reassessment is True


@pytest.mark.parametrize("header", ["graph LR", "sequenceDiagram", "pie",
                                    "gantt", "classDiagram", "erDiagram",
                                    "stateDiagram-v2", "journey"])
def test_no_recognised_diagram_type_is_ever_unfenced(header):
    a = action(issue="prose_not_diagram")
    text = FENCE + "mermaid\n" + header + "\n  A --> B\n" + FENCE + "\n"
    r = act(at_correct(), report(a), [a.action_id], {"t1": text})
    assert r.applied_actions == [], header


def test_two_mermaid_blocks_are_refused_rather_than_guessed():
    """Step 10's action carries an issue code, never which block it came from."""
    a = action(issue="prose_not_diagram")
    two = PROSE_DIAGRAM + "\n" + PROSE_DIAGRAM
    r = act(at_correct(), report(a), [a.action_id], {"t1": two})
    assert r.applied_actions == []
    assert r.requires_reassessment is True


@pytest.mark.parametrize("issue", ["prose_not_diagram", "empty_diagram"])
def test_unpaired_fences_are_refused(issue):
    """The block regex is non-greedy, so with an odd number of markers it
    closes somewhere that is not the end of the block. Unfencing there removes
    two markers that were never a pair and leaves a stray one — creating the
    unclosed_fence this module exists to repair."""
    odd = FENCE + "mermaid\nsome prose " + FENCE + " more\n" + FENCE + "\n"
    assert odd.count(FENCE) % 2 == 1
    a = action(issue=issue)
    r = act(at_correct(), report(a), [a.action_id], {"t1": odd})
    assert r.applied_actions == []
    assert "not present" in r.refusals[0]


def test_a_mismatched_issue_code_against_an_empty_block_is_refused():
    """prose_not_diagram aimed at a block with no body. Without the empty-body
    guard this indexes into an empty list and raises out of act()."""
    a = action(issue="prose_not_diagram")
    r = act(at_correct(), report(a), [a.action_id], {"t1": EMPTY_DIAGRAM})
    assert r.applied_actions == []
    assert r.status is ActStatus.REFUSED


def test_the_empty_body_guard_refuses_without_raising():
    """Distinguishes a clean refusal from one that crashes into the catch.

    act()'s try/except would refuse either way, so the end-to-end test above
    cannot tell them apart — deleting the guard leaves observable behaviour
    identical. Calling the precondition directly is what pins it.
    """
    from cognitive.act import _is_prose_fenced_as_diagram
    assert _is_prose_fenced_as_diagram(EMPTY_DIAGRAM) is False


def test_a_raising_precondition_refuses_rather_than_crashing(monkeypatch):
    """Several remedies means several parsers. One malformed artefact must not
    take ACT down mid-run and lose the corrections already applied."""
    from cognitive.act import _Remedy
    import cognitive.act as m

    def boom(_):
        raise RuntimeError("parser exploded")

    monkeypatch.setitem(m._DETERMINISTIC, "unclosed_fence",
                        _Remedy(precondition=boom, transform=lambda t: t,
                                description="x"))
    a = action()
    r = act(at_correct(), report(a), [a.action_id], {"t1": OPEN_FENCE})
    assert r.applied_actions == []
    assert r.status is ActStatus.REFUSED
    assert r.requires_reassessment is True


def test_a_raising_transform_refuses_rather_than_crashing(monkeypatch):
    from cognitive.act import _Remedy
    import cognitive.act as m

    def boom(_):
        raise RuntimeError("transform exploded")

    monkeypatch.setitem(m._DETERMINISTIC, "unclosed_fence",
                        _Remedy(precondition=lambda t: True, transform=boom,
                                description="x"))
    a = action()
    r = act(at_correct(), report(a), [a.action_id], {"t1": OPEN_FENCE})
    assert r.applied_actions == []
    assert r.artifacts == {}


def test_one_failing_remedy_does_not_lose_the_others(monkeypatch):
    from cognitive.act import _Remedy
    import cognitive.act as m

    def boom(_):
        raise RuntimeError("nope")

    monkeypatch.setitem(m._DETERMINISTIC, "empty_diagram",
                        _Remedy(precondition=boom, transform=lambda t: t,
                                description="x"))
    good = action(issue="unclosed_fence", target="t1")
    bad = action(issue="empty_diagram", target="t2")
    r = act(at_correct(), report(good, bad), [good.action_id, bad.action_id],
            {"t1": OPEN_FENCE, "t2": EMPTY_DIAGRAM})
    assert r.applied_actions == [good.action_id]
    assert bad.action_id in r.refused_actions


def test_empty_diagram_with_unpaired_fences_is_refused():
    """Separated from the shared case above, which has a NON-empty body — so
    the body check fires first and the odd-fence guard is never reached. With
    only the shared test, deleting that guard passes everything."""
    odd_empty = (FENCE + "mermaid\n\n" + FENCE + "\nand more text\n"
                 + FENCE + "\n")
    assert odd_empty.count(FENCE) % 2 == 1
    a = action(issue="empty_diagram")
    r = act(at_correct(), report(a), [a.action_id], {"t1": odd_empty})
    assert r.applied_actions == []
    assert "not present" in r.refusals[0]


def test_dropping_that_block_would_manufacture_a_defect():
    from cognitive.act import _drop_empty_diagram, _sole_mermaid_block
    odd_empty = (FENCE + "mermaid\n\n" + FENCE + "\nand more text\n"
                 + FENCE + "\n")
    assert _sole_mermaid_block(odd_empty) is not None
    assert "unclosed_fence" in _codes(_drop_empty_diagram(odd_empty)), \
        "if this stops holding, the guard is guarding nothing"


def test_that_refusal_prevents_a_real_regression():
    """What the guard is worth: applying the repair anyway would manufacture a
    defect. Asserted against review_engine, not argued."""
    from cognitive.act import _sole_mermaid_block, _unfence_diagram
    odd = FENCE + "mermaid\nsome prose " + FENCE + " more\n" + FENCE + "\n"
    assert _sole_mermaid_block(odd) is not None, "the regex does match here"
    naive = _unfence_diagram(odd)
    assert "unclosed_fence" in _codes(naive), \
        "if this stops holding, the odd-fence guard is guarding nothing"


# ── empty_diagram: remove the block ──────────────────────────────────────────
def test_an_empty_mermaid_block_is_removed():
    a = action(issue="empty_diagram")
    assert "empty_diagram" in _codes(EMPTY_DIAGRAM)
    r = act(at_correct(), report(a), [a.action_id], {"t1": EMPTY_DIAGRAM})
    assert r.status is ActStatus.APPLIED
    assert "mermaid" not in r.artifacts["t1"]
    assert _codes(r.artifacts["t1"]) == []


def test_removing_an_empty_block_keeps_the_surrounding_prose():
    a = action(issue="empty_diagram")
    r = act(at_correct(), report(a), [a.action_id], {"t1": EMPTY_DIAGRAM})
    assert "Here is the diagram:" in r.artifacts["t1"]


def test_a_header_only_diagram_is_not_deleted():
    """review_engine calls this empty_diagram too, but a header is authored
    text. Deletion is the most destructive edit available, so ACT declines."""
    a = action(issue="empty_diagram")
    assert "empty_diagram" in _codes(HEADER_ONLY_DIAGRAM)
    r = act(at_correct(), report(a), [a.action_id], {"t1": HEADER_ONLY_DIAGRAM})
    assert r.applied_actions == []
    assert "not present" in r.refusals[0]
    assert r.requires_reassessment is True


def test_a_populated_diagram_is_never_removed():
    a = action(issue="empty_diagram")
    r = act(at_correct(), report(a), [a.action_id], {"t1": VALID_DIAGRAM})
    assert r.applied_actions == []


# ── the properties hold across every remedy ──────────────────────────────────
@pytest.mark.parametrize("issue,artefact", [
    ("unclosed_fence", OPEN_FENCE),
    ("prose_not_diagram", PROSE_DIAGRAM),
    ("empty_diagram", EMPTY_DIAGRAM),
])
def test_every_remedy_resolves_its_own_issue_code(issue, artefact):
    assert issue in _codes(artefact), "the fixture must actually carry the defect"
    a = action(issue=issue)
    r = act(at_correct(), report(a), [a.action_id], {"t1": artefact})
    assert r.status is ActStatus.APPLIED
    assert issue not in _codes(r.artifacts["t1"])


@pytest.mark.parametrize("issue,artefact", [
    ("unclosed_fence", OPEN_FENCE),
    ("prose_not_diagram", PROSE_DIAGRAM),
    ("empty_diagram", EMPTY_DIAGRAM),
])
def test_no_remedy_introduces_a_new_defect(issue, artefact):
    before = set(_codes(artefact))
    a = action(issue=issue)
    r = act(at_correct(), report(a), [a.action_id], {"t1": artefact})
    assert set(_codes(r.artifacts["t1"])) <= before, \
        "a repair that adds a defect is not a repair"


@pytest.mark.parametrize("issue", sorted(_DETERMINISTIC))
def test_every_remedy_is_idempotent_by_refusal(issue):
    """Applying a repair twice must refuse the second time, never compound."""
    artefact = {"unclosed_fence": OPEN_FENCE, "prose_not_diagram": PROSE_DIAGRAM,
                "empty_diagram": EMPTY_DIAGRAM}[issue]
    a = action(issue=issue)
    once = act(at_correct(), report(a), [a.action_id], {"t1": artefact})
    b = action(issue=issue)
    twice = act(at_correct(), report(b), [b.action_id], once.artifacts)
    assert twice.applied_actions == [], f"{issue} applied twice"
    assert "not present" in twice.refusals[0]


@pytest.mark.parametrize("issue", sorted(_DETERMINISTIC))
def test_no_remedy_touches_an_artefact_it_does_not_match(issue):
    """A clean, valid artefact must survive every remedy untouched."""
    a = action(issue=issue)
    r = act(at_correct(), report(a), [a.action_id], {"t1": VALID_DIAGRAM})
    assert r.applied_actions == [], issue
    assert r.artifacts == {}


@pytest.mark.parametrize("issue", sorted(_DETERMINISTIC))
def test_every_remedy_is_deterministic(issue):
    artefact = {"unclosed_fence": OPEN_FENCE, "prose_not_diagram": PROSE_DIAGRAM,
                "empty_diagram": EMPTY_DIAGRAM}[issue]
    outputs = {act(at_correct(), report(action(issue=issue)),
                   [x.action_id for x in report(action(issue=issue)).corrections]
                   or [], {"t1": artefact}).status for _ in range(3)}
    remedy = _DETERMINISTIC[issue]
    assert len({remedy.transform(artefact) for _ in range(3)}) == 1


@pytest.mark.parametrize("issue", sorted(_DETERMINISTIC))
def test_every_remedy_declares_a_description(issue):
    assert _DETERMINISTIC[issue].description.strip()


# ── the new remedies inherit every existing guarantee ────────────────────────
@pytest.mark.parametrize("issue,artefact", [
    ("prose_not_diagram", PROSE_DIAGRAM),
    ("empty_diagram", EMPTY_DIAGRAM),
])
def test_new_remedies_still_require_approval(issue, artefact):
    a = action(issue=issue)
    r = act(at_correct(), report(a), [], {"t1": artefact})
    assert r.applied_actions == []
    assert r.status is ActStatus.NOTHING_APPROVED


@pytest.mark.parametrize("issue,artefact", [
    ("prose_not_diagram", PROSE_DIAGRAM),
    ("empty_diagram", EMPTY_DIAGRAM),
])
def test_new_remedies_still_respect_denial(issue, artefact):
    a = action(issue=issue, target="t9")
    r = act(at_correct(), report(a, blocking=["t9: policy refused this task"]),
            [a.action_id], {"t9": artefact})
    assert r.applied_actions == []
    assert r.requires_reassessment is False


@pytest.mark.parametrize("issue,artefact", [
    ("prose_not_diagram", PROSE_DIAGRAM),
    ("empty_diagram", EMPTY_DIAGRAM),
])
def test_new_remedies_still_respect_cancellation(issue, artefact):
    a = action(issue=issue)
    r = act(at_correct(), report(a), [a.action_id], {"t1": artefact},
            is_cancelled=lambda: True)
    assert r.status is ActStatus.CANCELLED
    assert r.artifacts == {}


@pytest.mark.parametrize("issue,artefact", [
    ("prose_not_diagram", PROSE_DIAGRAM),
    ("empty_diagram", EMPTY_DIAGRAM),
])
def test_new_remedies_keep_the_artefact_exact_for_verify(issue, artefact):
    key = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    a = action(issue=issue)
    r = act(at_correct(), report(a), [a.action_id],
            {"t1": artefact.replace("Here", "Here " + key, 1)})
    if not r.artifacts:
        return
    assert key in r.artifacts["t1"], "VERIFY must judge the bytes ACT produced"
    assert key not in r.safe_artifacts["t1"], "the log-safe view still redacts"


def test_the_whole_loop_closes_on_a_prose_diagram():
    """VERIFY -> CORRECT -> ACT -> VERIFY, end to end, on the new remedy."""
    from cognitive.correction import correct as run_correct
    t = PlannedTask(task_id="t1", objective="draw a flow")
    first = verify(ExecutionResult(success=True, completed_tasks=["t1"]),
                   TaskPlan(tasks=[t]),
                   StrategyDecision(strategy=ReasoningStrategy.CODE,
                                    verification_requirements=[
                                        VerificationRequirement.DIAGRAM_VALIDATION]),
                   artifacts={"t1": PROSE_DIAGRAM})
    assert first.status is VerificationStatus.FAILED

    s = at_correct()
    proposal = run_correct(s, ExecutionResult(success=True, completed_tasks=["t1"]),
                           first)
    applied = act(s, proposal, [x.action_id for x in proposal.corrections],
                  {"t1": PROSE_DIAGRAM})
    assert applied.status is ActStatus.APPLIED

    second = verify(ExecutionResult(success=True, completed_tasks=["t1"]),
                    TaskPlan(tasks=[t]),
                    StrategyDecision(strategy=ReasoningStrategy.CODE,
                                     verification_requirements=[
                                         VerificationRequirement.DIAGRAM_VALIDATION]),
                    artifacts=applied.artifacts)
    assert second.status is not VerificationStatus.FAILED
