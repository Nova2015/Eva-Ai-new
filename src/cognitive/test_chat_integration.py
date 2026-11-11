"""Tests for wiring the cognitive engine into /chat (chat_bridge).

The load-bearing properties:

  1. **The engine can only improve a reply or leave it alone.** Every path
     returns the original answer unless a correction was applied AND
     independently re-verified.
  2. **It generates nothing.** No model, no tool, no retrieval, no network. The
     only change possible is a deterministic remedy over characters the answer
     already had.
  3. **It cannot become a bypass.** It runs before the outbound gate, so a
     corrected answer is still inspected by the firewall.

Bridge-level tests run in milliseconds. The end-to-end tests import app.py,
which takes ~30s and is skipped when that import fails.
"""

import asyncio
import os
import pytest

try:
    from cognitive.chat_bridge import (
        refine, enabled, ChatRefinement, CHAT_TASK, _ENV_FLAG,
    )
    from cognitive.verification import artifact_digest, run_review_pipeline
    from cognitive.state import VerificationStatus
    from cognitive.strategy import VerificationRequirement
except ImportError:  # running from src/cognitive directly
    from chat_bridge import (  # type: ignore
        refine, enabled, ChatRefinement, CHAT_TASK, _ENV_FLAG,
    )
    from verification import artifact_digest, run_review_pipeline  # type: ignore
    from state import VerificationStatus  # type: ignore
    from strategy import VerificationRequirement  # type: ignore


FENCE = "`" * 3
PROSE = "The capital of France is Paris."
GOOD_CODE = "Here you go:\n" + FENCE + "python\ndef f(x):\n    return x[::-1]\n" + FENCE + "\n"
# Valid Python whose fence was cut off — ACT can repair this one.
CUT_FENCE = "Here you go:\n" + FENCE + "python\ndef f(x):\n    return x[::-1]\n"
# A genuine syntax error — no deterministic remedy exists.
BROKEN_CODE = "Here:\n" + FENCE + "python\ndef f(x)\n    return x\n" + FENCE + "\n"
# Prose fenced as a diagram — ACT can unfence it.
PROSE_DIAGRAM = ("Here is the flow:\n" + FENCE +
                 "mermaid\nFirst the user logs in. Then the server checks it.\n"
                 + FENCE + "\n")

QUESTION = "write a python function that reverses a string"


def codes(text):
    return [i.get("code") for i in run_review_pipeline(text)["issues"]]


def _results(answer, question=QUESTION):
    """The per-check verdicts behind a refine() run."""
    from cognitive.understanding import understand
    from cognitive.assessment import assess
    from cognitive.strategy import select_strategy
    from cognitive.verification import verify
    from cognitive.executor import ExecutionResult, ExecutionStatus
    from cognitive.planning import TaskPlan
    from cognitive.state import PlannedTask
    u = understand(question)
    d = select_strategy(u, assess(u, problem=question), problem=question)
    return verify(ExecutionResult(success=True, completed_tasks=[CHAT_TASK],
                                  final_execution_status=ExecutionStatus.EXECUTION_COMPLETE),
                  TaskPlan(tasks=[PlannedTask(task_id=CHAT_TASK, objective="x")]),
                  d, artifacts={CHAT_TASK: answer}).results


# ── A: normal chat is untouched ──────────────────────────────────────────────
def test_a_plain_prose_answer_passes_through_unchanged():
    r = refine("what is the capital of France?", PROSE)
    assert r.answer == PROSE
    assert r.changed is False
    assert r.ran is True
    assert r.remedy_applied is None


def test_a_simple_answer_needs_no_correction():
    """Most replies have nothing checkable in them; the engine says so rather
    than inventing something to do."""
    r = refine("hello", "Hi! How can I help?")
    assert r.answer == "Hi! How can I help?"
    assert r.verification_status in (VerificationStatus.NOT_REQUIRED.value,
                                     VerificationStatus.VERIFIED.value)


def test_an_empty_answer_is_left_alone():
    r = refine(QUESTION, "")
    assert r.answer == ""
    assert r.ran is False


def test_the_engine_reports_a_strategy_for_every_run():
    r = refine(QUESTION, GOOD_CODE)
    assert r.strategy, "LEARN attributes outcomes to a strategy"


# ── B: the answer goes through verification ──────────────────────────────────
def test_a_valid_code_answer_is_verified_and_left_alone():
    """Update 14 changed this verdict, and the change is the point.

    It used to read INCONCLUSIVE: the strategy also asked for EXECUTION_TEST,
    which has no runner here, and one unrunnable requirement dragged the whole
    aggregate down however good the code was. Now only runnable checks are
    requested, EXECUTION_TEST is recorded as unavailable, and CODE_VALIDATION
    passing means VERIFIED — a claim about what ran, not about execution.
    """
    r = refine(QUESTION, GOOD_CODE)
    assert r.verification_status == VerificationStatus.VERIFIED.value
    assert r.changed is False
    assert r.answer == GOOD_CODE


def test_verification_records_which_artefact_it_read():
    r = refine(QUESTION, GOOD_CODE)
    assert r.verified_digest == artifact_digest(GOOD_CODE)


def test_the_summary_carries_no_answer_content():
    """The block attached to the response body is statuses and a digest."""
    r = refine(QUESTION, GOOD_CODE)
    blob = str(r.summary())
    assert "def f" not in blob
    assert set(r.summary()) == {"ran", "status", "corrected", "remedy",
                                "strategy", "digest"}


# ── C: the ACT path, end to end ──────────────────────────────────────────────
def test_a_repairable_answer_is_corrected_and_reverified():
    assert "unclosed_fence" in codes(CUT_FENCE)
    r = refine(QUESTION, CUT_FENCE)
    assert r.changed is True
    assert r.remedy_applied == "unclosed_fence"
    assert codes(r.answer) == [], "the returned answer is clean"


def test_the_acceptance_rule_is_not_the_aggregate_status():
    """The rule still holds; this fixture no longer demonstrates it.

    It used to: the aggregate was INCONCLUSIVE (unrunnable EXECUTION_TEST) while
    the correction was accepted anyway, which proved acceptance was not gated on
    the aggregate. Update 14 makes that aggregate VERIFIED, so the two now agree
    and the case can no longer tell them apart. The rule itself is pinned
    directly by the _correction_is_an_improvement tests below, which construct
    the disagreement instead of relying on one occurring naturally.
    """
    from cognitive.chat_bridge import _correction_is_an_improvement
    r = refine(QUESTION, CUT_FENCE)
    assert r.changed is True
    assert callable(_correction_is_an_improvement),         "acceptance is decided by this predicate, not by report.status"


def test_the_corrected_answer_keeps_the_original_content():
    r = refine(QUESTION, CUT_FENCE)
    assert "def f(x):" in r.answer and "return x[::-1]" in r.answer


def test_diagram_validation_is_now_requested_from_chat():
    """This test asserted the opposite until Update 14.

    Step 5 keyed diagram detection on understanding.desired_outcome, which
    Step 3's deterministic path never fills with "diagram" — so the validator
    was unreachable however plainly the user asked. It now also reads the raw
    request, the same fix Steps 4 and 7 each needed.
    """
    from cognitive.understanding import understand
    from cognitive.assessment import assess
    from cognitive.strategy import select_strategy
    from cognitive.verification import available_requirements
    for question in ("draw a mermaid diagram of the login flow",
                     "show me a flowchart", "I need a diagram of the auth flow"):
        u = understand(question)
        d = select_strategy(u, assess(u, problem=question), problem=question,
                            available=available_requirements())
        assert "diagram" not in (u.desired_outcome or "").lower(),             "the old signal is still absent; the raw request is what carries it"
        assert VerificationRequirement.DIAGRAM_VALIDATION in             d.verification_requirements, question


def test_a_diagram_defect_is_found_and_its_remedy_is_now_accepted():
    """Update 15 completed what Update 14 unlocked.

    Update 14 made the defect findable. It was still discarded, because
    unfencing REMOVES the mermaid block, so re-verification reported
    NOT_REQUIRED rather than VERIFIED and the outcome rule could not tell
    "the block is gone because I deleted it" from "no verdict came back".
    Update 15 gave ACT's remedies a declared post-state, so a removal remedy
    can be proven by absence.
    """
    r = refine("draw a mermaid diagram of the login flow", PROSE_DIAGRAM)
    assert r.changed is True
    assert r.remedy_applied == "prose_not_diagram"
    assert "First the user logs in." in r.answer, "the prose is kept"
    assert FENCE + "mermaid" not in r.answer, "the false diagram claim is gone"
    assert r.verification_status == VerificationStatus.NOT_REQUIRED.value,         "honest: there is no diagram left to verify"


def test_an_empty_diagram_block_is_also_removed_and_accepted():
    empty = "Here is the diagram:\n" + FENCE + "mermaid\n\n" + FENCE + "\n"
    r = refine("draw a mermaid diagram of the login flow", empty)
    assert r.changed is True
    assert r.remedy_applied == "empty_diagram"
    assert "Here is the diagram:" in r.answer


def test_a_repair_in_place_remedy_still_needs_a_positive_verdict():
    """The two kinds are not treated alike: closing a fence must leave a block
    that VERIFIES, not one that vanished."""
    from cognitive.act import remedy_removes_construct
    assert remedy_removes_construct("unclosed_fence") is False
    r = refine(QUESTION, CUT_FENCE)
    assert r.changed is True
    assert r.verification_status == VerificationStatus.VERIFIED.value


def test_only_one_remedy_runs_per_cycle():
    """Two defects, one pass: the engine applies a single remedy and stops."""
    both = CUT_FENCE + "\n" + PROSE_DIAGRAM
    r = refine(QUESTION, both)
    if r.changed:
        assert r.remedy_applied is not None
        assert isinstance(r.remedy_applied, str)


# ── D: an unsupported defect is never guessed at ─────────────────────────────
def test_a_syntax_error_is_not_rewritten():
    assert "python_syntax_error" in codes(BROKEN_CODE)
    r = refine(QUESTION, BROKEN_CODE)
    assert r.answer == BROKEN_CODE, "the engine must not author a fix"
    assert r.changed is False
    assert r.remedy_applied is None


def test_a_failed_verification_without_a_remedy_still_reports_honestly():
    r = refine(QUESTION, BROKEN_CODE)
    assert r.verification_status == VerificationStatus.FAILED.value
    assert r.notes, "the refusal is stated, not silent"


def test_the_engine_never_invents_content():
    """Nothing the engine returns may contain a character the answer lacked,
    ignoring whitespace and fence markers."""
    for answer in (PROSE, GOOD_CODE, CUT_FENCE, BROKEN_CODE, PROSE_DIAGRAM):
        r = refine(QUESTION, answer)
        strip = lambda s: set("".join(s.split())) - set("`")
        assert strip(r.answer) <= strip(answer) | set("mermaid"), answer[:30]


# ── E: provenance survives the loop ──────────────────────────────────────────
def test_the_digest_matches_the_answer_actually_returned():
    for answer in (PROSE, GOOD_CODE, CUT_FENCE, PROSE_DIAGRAM):
        r = refine(QUESTION, answer)
        if r.verified_digest is None:
            continue
        assert r.verified_digest == artifact_digest(r.answer), \
            "the digest must describe what the user receives"


def test_a_corrected_answer_carries_the_corrected_digest():
    r = refine(QUESTION, CUT_FENCE)
    assert r.changed is True
    assert r.verified_digest == artifact_digest(r.answer)
    assert r.verified_digest != artifact_digest(CUT_FENCE), \
        "the pre-correction digest must not survive as the final one"


def test_verification_reads_exactly_what_act_produced():
    """No redaction, truncation or reformatting between ACT and VERIFY."""
    r = refine(QUESTION, CUT_FENCE)
    assert r.answer == CUT_FENCE.rstrip() + "\n" + FENCE


def test_a_secret_in_the_answer_survives_into_the_answer_but_not_the_summary():
    key = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    answer = "Here:\n" + FENCE + f"python\ntoken = '{key}'\n"
    r = refine(QUESTION, answer)
    assert key in r.answer, "the user's own answer is not rewritten"
    assert key not in str(r.summary())


# ── G: failure isolation ─────────────────────────────────────────────────────
def test_a_crash_inside_the_engine_returns_the_original_answer(monkeypatch):
    import cognitive.chat_bridge as bridge

    def boom(*a, **k):
        raise RuntimeError("stage exploded")

    monkeypatch.setattr(bridge, "understand", boom)
    r = refine(QUESTION, CUT_FENCE)
    assert r.answer == CUT_FENCE, "a broken engine must change nothing"
    assert r.changed is False
    assert any("skipped" in n for n in r.notes)


def test_a_crash_in_verification_returns_the_original_answer(monkeypatch):
    import cognitive.chat_bridge as bridge

    def boom(*a, **k):
        raise RuntimeError("verifier exploded")

    monkeypatch.setattr(bridge, "verify", boom)
    r = refine(QUESTION, CUT_FENCE)
    assert r.answer == CUT_FENCE
    assert r.changed is False


def test_a_correction_that_does_not_reverify_is_discarded(monkeypatch):
    """The rule that stops an unproven artefact reaching the user."""
    import cognitive.chat_bridge as bridge
    from cognitive.verification import VerificationReport

    real = bridge.verify
    calls = {"n": 0}

    def once_then_fail(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return real(*a, **k)
        return VerificationReport(status=VerificationStatus.FAILED, failed_count=1)

    monkeypatch.setattr(bridge, "verify", once_then_fail)
    r = refine(QUESTION, CUT_FENCE)
    assert r.answer == CUT_FENCE, "an unverified correction is never returned"
    assert r.changed is False
    assert any("not accepted" in n for n in r.notes)


def test_the_kill_switch_disables_the_engine(monkeypatch):
    monkeypatch.setenv(_ENV_FLAG, "false")
    assert enabled() is False
    r = refine(QUESTION, CUT_FENCE)
    assert r.answer == CUT_FENCE
    assert r.ran is False


def test_the_engine_is_on_by_default(monkeypatch):
    monkeypatch.delenv(_ENV_FLAG, raising=False)
    assert enabled() is True


def test_refine_never_raises():
    """Whatever it is handed, /chat gets an answer back."""
    for question, answer in ((None, None), ("", ""), (QUESTION, None),
                             (None, GOOD_CODE), ("x" * 5000, CUT_FENCE)):
        r = refine(question or "", answer or "")
        assert isinstance(r, ChatRefinement)
        assert isinstance(r.answer, str)


def test_refine_is_deterministic():
    a, b = refine(QUESTION, CUT_FENCE), refine(QUESTION, CUT_FENCE)
    assert a.answer == b.answer
    assert a.summary() == b.summary()


# ── the bridge orchestrates; it does not execute ─────────────────────────────
def _executable_source(module_name="chat_bridge.py"):
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


def test_the_bridge_performs_no_retrieval_model_call_or_tool_execution():
    import ast
    tree = ast.parse(_executable_source())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = {"requests", "httpx", "openai", "groq", "google", "anthropic",
                 "subprocess", "socket", "sqlite3", "urllib", "aiohttp"}
    assert not (imported & forbidden), f"bridge imports {imported & forbidden}"
    assert imported <= {"os", "typing", "pydantic", "__future__"}


def test_the_bridge_does_not_duplicate_execution_logic():
    src = _executable_source()
    for owned_elsewhere in ("run_plan", "rag", "HF_RAG_URL", "chat.completions",
                            "run_review_pipeline", "_outbound_gate"):
        assert owned_elsewhere not in src, f"{owned_elsewhere} belongs to app.py"


def test_learning_sink_is_injected_and_never_defaults_to_storage():
    """The bridge can emit only through an explicitly supplied sink."""
    src = _executable_source()
    assert "emit(lessons, sink=learning_sink)" in src
    assert "capture_candidate" not in src
    assert "learning_sink=None" in src


def test_app_requires_explicit_opt_in_for_cognitive_capture():
    from pathlib import Path
    app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text(
        encoding="utf-8"
    )
    assert "learning_opt_in=(getattr(req, \"learn\", None) is True)" in app_source
    assert "learning_sink=(pending_cognitive_candidates.append" in app_source
    assert "if (learning_opt_in and not learning_is_image and not would_block" in app_source


# ── the acceptance rule, tested where it can actually fail ───────────────────
# The end-to-end fixtures above do not discriminate: with CUT_FENCE the
# correction is genuinely good, so loosening any guard leaves the outcome
# identical and every test still passes. These drive the predicate directly.

def _cycle_and_reports(corrected_answer, post_status, post_reason=None):
    """A real ACT pass plus a chosen post-ACT verification."""
    from cognitive.act import act
    from cognitive.correction import CorrectionReport, CorrectionStatus, CorrectionAction
    from cognitive.learning import CorrectionCycle
    from cognitive.state import CognitiveState, CognitivePhase, VerificationResult
    from cognitive.verification import VerificationReport, artifact_digest

    s = CognitiveState()
    for phase in (CognitivePhase.ASSESS, CognitivePhase.STRATEGY,
                  CognitivePhase.PLAN, CognitivePhase.ACT, CognitivePhase.VERIFY,
                  CognitivePhase.CORRECT):
        s.transition_to(phase)
    action = CorrectionAction(target=CHAT_TASK, issue="unclosed_fence")
    proposal = CorrectionReport(status=CorrectionStatus.CORRECTIONS_PROPOSED,
                                corrections=[action])
    applied = act(s, proposal, [action.action_id], {CHAT_TASK: CUT_FENCE})
    assert applied.artifacts, "the fixture must actually apply something"

    post = VerificationReport(
        results=[VerificationResult(task_id=CHAT_TASK, status=post_status,
                                    verification_type="CODE_VALIDATION",
                                    criteria=["code"], failure_reason=post_reason)],
        status=post_status,
        artifact_digests={CHAT_TASK: artifact_digest(applied.artifacts[CHAT_TASK])},
    )
    return action, CorrectionCycle(act=applied, verification=post)


def test_acceptance_requires_the_defect_to_be_resolved():
    from cognitive.chat_bridge import _correction_is_an_improvement
    action, cycle = _cycle_and_reports(CUT_FENCE, VerificationStatus.FAILED,
                                       "unclosed_fence")
    assert _correction_is_an_improvement(
        action, cycle, {"unclosed_fence"}, {"unclosed_fence"}) is False, \
        "the very defect that was corrected is still reported"


def test_acceptance_requires_provenance():
    from cognitive.chat_bridge import _correction_is_an_improvement
    action, _ = _cycle_and_reports(CUT_FENCE, VerificationStatus.VERIFIED)
    assert _correction_is_an_improvement(action, None, set(), set()) is False, \
        "without a provenance-matched cycle nothing may be accepted"


def test_acceptance_rejects_a_correction_that_adds_a_defect():
    from cognitive.chat_bridge import _correction_is_an_improvement
    action, cycle = _cycle_and_reports(CUT_FENCE, VerificationStatus.VERIFIED)
    assert _correction_is_an_improvement(
        action, cycle, {"unclosed_fence"}, {"python_syntax_error"}) is False, \
        "one defect traded for another is not an improvement"


def test_acceptance_allows_a_genuine_repair():
    from cognitive.chat_bridge import _correction_is_an_improvement
    action, cycle = _cycle_and_reports(CUT_FENCE, VerificationStatus.VERIFIED)
    assert _correction_is_an_improvement(
        action, cycle, {"unclosed_fence"}, set()) is True


def test_acceptance_allows_a_repair_that_leaves_an_unrelated_defect():
    """Pre-existing defects do not block a genuine repair — only NEW ones do."""
    from cognitive.chat_bridge import _correction_is_an_improvement
    action, cycle = _cycle_and_reports(CUT_FENCE, VerificationStatus.VERIFIED)
    assert _correction_is_an_improvement(
        action, cycle, {"unclosed_fence", "empty_data"}, {"empty_data"}) is True


# ── exactly one remedy per cycle ─────────────────────────────────────────────
def test_only_one_action_is_ever_approved(monkeypatch):
    """Step 10 may propose several. The bridge approves the first and no more,
    so a chat turn can never chain repairs."""
    import cognitive.chat_bridge as bridge
    from cognitive.correction import CorrectionReport, CorrectionStatus, CorrectionAction

    proposal = CorrectionReport(
        status=CorrectionStatus.CORRECTIONS_PROPOSED,
        corrections=[CorrectionAction(target=CHAT_TASK, issue="unclosed_fence"),
                     CorrectionAction(target=CHAT_TASK, issue="empty_diagram"),
                     CorrectionAction(target=CHAT_TASK, issue="prose_not_diagram")])
    monkeypatch.setattr(bridge, "correct", lambda *a, **k: proposal)

    seen = {}
    real_act = bridge.act

    def spy(state, report, approved_action_ids, *a, **k):
        seen["approved"] = list(approved_action_ids)
        return real_act(state, report, approved_action_ids, *a, **k)

    monkeypatch.setattr(bridge, "act", spy)
    refine(QUESTION, CUT_FENCE)
    assert len(seen.get("approved", [])) == 1, \
        f"one remedy per cycle; approved {seen.get('approved')}"
    assert seen["approved"] == [proposal.corrections[0].action_id]


# ═══════════════════════════════════════════════════════════════════════════
# R1 / R3 — the two review findings.
#
# R1: refine() was called inline on the event loop. review_engine shells out to
#     `node --check` for JavaScript, so a single answer stalled every
#     concurrent request — measured at 274ms against a 1ms target, in the very
#     function whose design comment says the firewall must never hang /chat.
# R3: refine() raised ValidationError on a non-string answer, past a docstring
#     promising it never raises, because the model was built before the try.
# ═══════════════════════════════════════════════════════════════════════════

# ── R3: refine really never raises ───────────────────────────────────────────
@pytest.mark.parametrize("answer", [
    {"a": 1}, ["x"], 42, 3.5, object(), b"bytes", True, None,
])
def test_refine_never_raises_on_a_non_string_answer(answer):
    r = refine(QUESTION, answer)
    assert isinstance(r, ChatRefinement)
    assert isinstance(r.answer, str)


@pytest.mark.parametrize("answer", [{"a": 1}, ["x"], 42, object()])
def test_a_non_string_answer_is_never_reported_as_changed(answer):
    """`changed` is what app.py acts on, so False leaves the payload untouched.
    Coercing a dict to a string and returning it would be worse than useless."""
    r = refine(QUESTION, answer)
    assert r.changed is False
    assert r.ran is False


@pytest.mark.parametrize("question", [{"a": 1}, ["x"], 42, None, object()])
def test_a_non_string_question_degrades_cleanly_rather_than_crashing(question):
    """`answer` alone cannot tell the two apart — a crash and a clean run both
    return the original. `ran` can: the engine must still complete a pass with
    an empty question, not fall into the catch-all."""
    r = refine(question, CUT_FENCE)
    assert isinstance(r.answer, str)
    assert r.ran is True, "the engine ran; it did not crash into the handler"
    assert not any("skipped" in n for n in r.notes)


def test_the_model_is_built_before_anything_can_fail():
    """The specific shape of the bug: ChatRefinement(answer=...) sat OUTSIDE
    the try, so its own validation escaped the function."""
    import ast, inspect
    import cognitive.chat_bridge as bridge
    fn = ast.parse(inspect.getsource(bridge.refine)).body[0]
    try_index = next(i for i, node in enumerate(fn.body)
                     if isinstance(node, ast.Try))
    before = ast.unparse(ast.Module(body=fn.body[:try_index], type_ignores=[]))
    assert "isinstance(answer, str)" in before, \
        "the type must be settled before the model is constructed"


# ── R1: the caller must not run this on the event loop ───────────────────────
def test_the_bridge_declares_a_timeout():
    from cognitive.chat_bridge import timeout_seconds
    assert timeout_seconds() > 0


def test_the_timeout_is_configurable_and_sane(monkeypatch):
    from cognitive.chat_bridge import timeout_seconds, _ENV_TIMEOUT, _DEFAULT_TIMEOUT
    monkeypatch.setenv(_ENV_TIMEOUT, "5")
    assert timeout_seconds() == 5.0
    for junk in ("", "abc", "-1", "0"):
        monkeypatch.setenv(_ENV_TIMEOUT, junk)
        assert timeout_seconds() == _DEFAULT_TIMEOUT, junk


def test_refining_javascript_is_slow_enough_to_matter():
    """Guards the premise. If review_engine ever stops shelling out to node,
    the threading below becomes unnecessary rather than merely untested."""
    import shutil, time
    if not shutil.which("node"):
        pytest.skip("node not installed; the subprocess path cannot be timed")
    js = "Here:\n" + FENCE + "javascript\nfunction f(){return 1}\n" + FENCE + "\n"
    t0 = time.perf_counter()
    refine(QUESTION, js)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms > 10, (
        f"JavaScript refine took {elapsed_ms:.0f}ms — if this is now trivial, "
        "re-examine whether the worker thread is still earning its keep")


# ═══════════════════════════════════════════════════════════════════════════
# R2 — no duplicate review_engine execution for the same artefact.
#
# The point is to remove duplicate WORK, never a check. Reuse is keyed on the
# exact bytes, so every distinct artefact is still reviewed and a corrected one
# is reviewed again on its own account.
# ═══════════════════════════════════════════════════════════════════════════

class _Counter:
    """Counts real review_engine executions, wherever they are called from."""

    def __init__(self, monkeypatch):
        import cognitive.verification as v
        self.n = 0
        real = v.run_review_pipeline

        def counted(text, mode="standard", **kw):
            self.n += 1
            return real(text, mode, **kw)

        monkeypatch.setattr(v, "run_review_pipeline", counted)


def test_a_corrected_artefact_is_reviewed_again_not_reused(monkeypatch):
    """The rule that must survive the fix: different bytes, new review."""
    from cognitive.verification import new_review_cache
    c = _Counter(monkeypatch)
    cache = new_review_cache()
    r = refine(QUESTION, CUT_FENCE, review_cache=cache)
    assert r.changed is True
    assert c.n == 2, f"original and corrected each reviewed once; got {c.n}"


def test_reviewing_the_same_artefact_twice_runs_the_pipeline_once(monkeypatch):
    from cognitive.verification import new_review_cache
    c = _Counter(monkeypatch)
    cache = new_review_cache()
    refine(QUESTION, GOOD_CODE, review_cache=cache)
    first = c.n
    refine(QUESTION, GOOD_CODE, review_cache=cache)
    assert c.n == first, "identical bytes must not be reviewed twice"


def test_a_different_artefact_is_never_served_from_cache(monkeypatch):
    from cognitive.verification import new_review_cache
    c = _Counter(monkeypatch)
    cache = new_review_cache()
    refine(QUESTION, GOOD_CODE, review_cache=cache)
    n_after_first = c.n
    refine(QUESTION, BROKEN_CODE, review_cache=cache)
    assert c.n > n_after_first, "different bytes must be reviewed on their own"


def test_a_one_character_difference_is_a_different_artefact(monkeypatch):
    from cognitive.verification import new_review_cache, review_key
    assert review_key(GOOD_CODE) != review_key(GOOD_CODE + " ")
    c = _Counter(monkeypatch)
    cache = new_review_cache()
    refine(QUESTION, GOOD_CODE, review_cache=cache)
    n = c.n
    refine(QUESTION, GOOD_CODE + " ", review_cache=cache)
    assert c.n > n


def test_a_different_mode_is_a_different_key():
    """A future second mode must not inherit standard mode's payload."""
    from cognitive.verification import review_key
    assert review_key(GOOD_CODE, "standard") != review_key(GOOD_CODE, "strict")


def test_no_cache_still_verifies(monkeypatch):
    """Sharing is an optimisation. Without it, behaviour is unchanged."""
    c = _Counter(monkeypatch)
    r = refine(QUESTION, CUT_FENCE)          # no cache passed
    assert r.changed is True, "the loop still works with no cache at all"
    assert c.n >= 2


def test_a_broken_cache_falls_back_to_reviewing(monkeypatch):
    """Requirement: a cache failure must fall back to the review path, never
    bypass verification."""
    class Hostile(dict):
        def get(self, *a, **k):
            raise RuntimeError("cache exploded")

        def __setitem__(self, *a, **k):
            raise RuntimeError("cache exploded")

    r = refine(QUESTION, CUT_FENCE, review_cache=Hostile())
    assert r.changed is True, "verification still happened"
    assert codes(r.answer) == []


def test_the_cache_is_not_module_level():
    """Request-scoped by construction: two calls to the factory share nothing."""
    from cognitive.verification import new_review_cache
    a, b = new_review_cache(), new_review_cache()
    a["x"] = {"y": 1}
    assert b == {}, "a process-wide cache would key a verdict across users"


def test_the_cache_only_ever_holds_payloads_for_bytes_it_reviewed():
    from cognitive.verification import new_review_cache, review_key
    cache = new_review_cache()
    r = refine(QUESTION, CUT_FENCE, review_cache=cache)
    assert review_key(CUT_FENCE) in cache
    assert review_key(r.answer) in cache
    assert len(cache) == 2


def test_provenance_still_matches_the_returned_answer(monkeypatch):
    """Reuse must never let a digest drift from the artefact it describes."""
    from cognitive.verification import new_review_cache
    cache = new_review_cache()
    for answer in (GOOD_CODE, CUT_FENCE, PROSE):
        r = refine(QUESTION, answer, review_cache=cache)
        if r.verified_digest is not None:
            assert r.verified_digest == artifact_digest(r.answer)


# ═══════════════════════════════════════════════════════════════════════════
# Hardening from the R2 review. None of these were correctness defects; each
# removes a way a future change could become one.
# ═══════════════════════════════════════════════════════════════════════════

# ── the cache owns its payload ───────────────────────────────────────────────
def test_a_caller_cannot_edit_what_the_cache_stores():
    """app.py's review hook does `review.update(status)` on what it receives.
    Handing out the stored object let one consumer edit what the next reads."""
    from cognitive.verification import new_review_cache, review_once, review_key
    cache = new_review_cache()
    first = review_once(GOOD_CODE, cache)
    first["status"] = "TAMPERED"
    first["valid"] = "TAMPERED"
    second = review_once(GOOD_CODE, cache)
    assert second.get("status") != "TAMPERED"
    assert second.get("valid") != "TAMPERED"
    assert cache[review_key(GOOD_CODE)].get("status") != "TAMPERED"


def test_the_copy_is_deep_not_shallow():
    """A shallow copy still shares `issues` and `checks` — the very structures
    a verdict is derived from."""
    from cognitive.verification import new_review_cache, review_once
    cache = new_review_cache()
    first = review_once(BROKEN_CODE, cache)
    assert first["issues"], "the fixture must carry an issue to remove"
    first["issues"].clear()
    first["checks"]["code"]["passed"] = True
    second = review_once(BROKEN_CODE, cache)
    assert second["issues"], "nested lists must not be shared with the cache"
    assert second["checks"]["code"]["passed"] is False


def test_each_reader_gets_an_independent_object():
    from cognitive.verification import new_review_cache, review_once
    cache = new_review_cache()
    a = review_once(GOOD_CODE, cache)
    b = review_once(GOOD_CODE, cache)
    assert a is not b
    a["issues"].append({"code": "injected"})
    assert not b["issues"], "two readers must not share one list"


def test_mutating_a_cache_hit_does_not_corrupt_the_next_read():
    """The read side, isolated from the store side.

    Every other copy test mutates the MISS result, which the store-side copy
    already keeps separate — so with that in place they pass whether or not
    reads are copied. Only mutating a HIT and reading again distinguishes them.
    """
    from cognitive.verification import new_review_cache, review_once
    cache = new_review_cache()
    review_once(BROKEN_CODE, cache)                   # populate (miss)
    hit = review_once(BROKEN_CODE, cache)             # hit
    assert hit["issues"], "the fixture must carry an issue"
    hit["issues"].clear()
    hit["status"] = "TAMPERED"
    again = review_once(BROKEN_CODE, cache)           # hit again
    assert again["issues"], "a mutated hit must not corrupt the cache"
    assert "status" not in again


def test_the_stored_object_is_not_the_one_returned_on_a_miss():
    from cognitive.verification import new_review_cache, review_once, review_key
    cache = new_review_cache()
    fresh = review_once(GOOD_CODE, cache)
    assert fresh is not cache[review_key(GOOD_CODE)]


def test_copying_does_not_change_any_verdict():
    """The whole point: this is protection, not behaviour."""
    from cognitive.verification import new_review_cache
    for answer in (GOOD_CODE, BROKEN_CODE, CUT_FENCE, PROSE):
        cached = refine(QUESTION, answer, review_cache=new_review_cache())
        plain = refine(QUESTION, answer)
        assert cached.answer == plain.answer
        assert cached.verification_status == plain.verification_status
        assert cached.remedy_applied == plain.remedy_applied


def test_the_real_hook_mutation_no_longer_reaches_the_cache():
    """Reproduces app.py:4153 exactly, then checks the next reader."""
    from cognitive.verification import new_review_cache, review_once, derive_status
    cache = new_review_cache()
    review = review_once(BROKEN_CODE, cache)
    review.update(derive_status(review))          # what the hook does, verbatim
    assert "status" in review
    assert "status" not in review_once(BROKEN_CODE, cache), \
        "the cached payload must not carry the hook's injected keys"


# ═══════════════════════════════════════════════════════════════════════════
# Update 14 end to end — a truthful status, and a visible coverage gap.
#
# Before this, no answer in realistic traffic ever reached VERIFIED: every code
# reply asked for EXECUTION_TEST, which has no runner here, so the aggregate
# was INCONCLUSIVE however good the code was. Five of eight strategies asked
# only for checks that cannot run at all.
# ═══════════════════════════════════════════════════════════════════════════

def _decision(question):
    from cognitive.understanding import understand
    from cognitive.assessment import assess
    from cognitive.strategy import select_strategy
    from cognitive.verification import available_requirements
    u = understand(question)
    return select_strategy(u, assess(u, problem=question), problem=question,
                           available=available_requirements())


# ── Example 1: valid code becomes VERIFIED ───────────────────────────────────
def test_valid_code_is_verified_when_only_execution_test_is_unavailable():
    r = refine(QUESTION, GOOD_CODE)
    assert r.verification_status == VerificationStatus.VERIFIED.value
    assert r.changed is False


def test_that_verdict_makes_no_execution_claim():
    """VERIFIED means "every check that was asked for ran and passed", never
    "the code was executed"."""
    d = _decision(QUESTION)
    assert d.verification_requirements == [VerificationRequirement.CODE_VALIDATION]
    assert d.unavailable_requirements == [VerificationRequirement.EXECUTION_TEST]


def test_the_execution_test_is_never_executed():
    """Recorded as unavailable means exactly that: no runner is invoked and no
    EXECUTION_TEST result appears."""
    from cognitive.verification import verify, ExecutionResult
    from cognitive.planning import TaskPlan
    from cognitive.state import PlannedTask
    from cognitive.executor import ExecutionStatus
    called = []
    d = _decision(QUESTION)
    report = verify(
        ExecutionResult(success=True, completed_tasks=[CHAT_TASK],
                        final_execution_status=ExecutionStatus.EXECUTION_COMPLETE),
        TaskPlan(tasks=[PlannedTask(task_id=CHAT_TASK, objective="x")]),
        d, artifacts={CHAT_TASK: GOOD_CODE},
        code_runner=lambda text: called.append(text) or {"status": "SUCCESS"})
    assert called == [], "an unavailable requirement must never reach a runner"
    assert not any(x.verification_type == "EXECUTION_TEST" for x in report.results)


def test_a_correction_now_reaches_verified():
    r = refine(QUESTION, CUT_FENCE)
    assert r.changed is True
    assert r.verification_status == VerificationStatus.VERIFIED.value


def test_broken_code_still_fails():
    """Truthful in both directions — this is not a way of always saying yes."""
    r = refine(QUESTION, BROKEN_CODE)
    assert r.verification_status == VerificationStatus.FAILED.value
    assert r.changed is False


# ── Example 2: diagram validation is actually requested ──────────────────────
def test_a_diagram_request_asks_for_diagram_validation():
    d = _decision("draw a mermaid diagram of the login flow")
    assert VerificationRequirement.DIAGRAM_VALIDATION in d.verification_requirements


def test_a_prose_diagram_is_now_detected_through_chat():
    """Previously unreachable: the check was never requested, so a diagram
    defect could not be found however plainly wrong the block was.

    Update 14 made it findable and this asserted the final status was FAILED.
    Update 15 then made the remedy acceptable, so the defect is now REPAIRED
    and the final status describes the repaired answer. Detection is what this
    test is about, and the remedy firing is the proof it was detected.
    """
    r = refine("draw a mermaid diagram of the login flow", PROSE_DIAGRAM)
    assert r.ran is True
    assert r.remedy_applied == "prose_not_diagram", \
        "a remedy only fires on a defect that was actually found"
    assert codes(PROSE_DIAGRAM) == ["prose_not_diagram"], "the input was faulty"
    assert codes(r.answer) == [], "and the answer returned is not"


def test_a_valid_diagram_verifies():
    valid = ("Here:\n" + FENCE + "mermaid\nflowchart TD\n  A[Start] --> B[End]\n"
             + FENCE + "\n")
    r = refine("draw a mermaid diagram of the login flow", valid)
    assert r.verification_status == VerificationStatus.VERIFIED.value


# ── Example 3: no runnable check, no manufactured evidence ───────────────────
def test_a_retrieval_answer_claims_nothing():
    d = _decision("summarise the uploaded report")
    assert d.verification_requirements == []
    assert d.unavailable_requirements == [VerificationRequirement.CITATION_CHECK]
    r = refine("summarise the uploaded report", PROSE)
    assert r.verification_status == VerificationStatus.NOT_REQUIRED.value, \
        "nothing ran, so nothing is claimed — and certainly not VERIFIED"


def test_no_runnable_check_never_manufactures_verified():
    for question in ("summarise the uploaded report", "compare postgres and mysql",
                     "explain this in detail step by step"):
        r = refine(question, PROSE)
        assert r.verification_status != VerificationStatus.VERIFIED.value, question


# ── the coverage gap stays visible ───────────────────────────────────────────
def test_learning_can_still_see_the_verification_gap():
    """The reason unavailable requirements are recorded rather than dropped:
    Step 12's VERIFICATION_GAP lessons are built from `unverifiable`."""
    from cognitive.verification import verify
    from cognitive.executor import ExecutionResult, ExecutionStatus
    from cognitive.planning import TaskPlan
    from cognitive.state import PlannedTask
    import cognitive.chat_bridge as bridge
    d = _decision(QUESTION)
    report = bridge._verify(
        GOOD_CODE, d,
        TaskPlan(tasks=[PlannedTask(task_id=CHAT_TASK, objective="x")]))
    assert any("EXECUTION_TEST" in u for u in report.unverifiable), \
        "the gap must survive into the report Step 12 reads"
    assert report.status is VerificationStatus.VERIFIED, \
        "recording a gap must not poison the verdict"


def test_recording_the_gap_cannot_change_the_status():
    """VerificationReport.status is derived from results alone — that is what
    makes it safe to write the gap alongside a VERIFIED verdict."""
    from cognitive.verification import VerificationReport
    from cognitive.state import VerificationResult
    base = VerificationReport(
        results=[VerificationResult(task_id=CHAT_TASK,
                                    status=VerificationStatus.VERIFIED)],
        status=VerificationStatus.VERIFIED, verified_count=1)
    before = base.status
    base.unverifiable = base.unverifiable + ["EXECUTION_TEST: not executable"]
    assert base.status is before


def test_the_gap_names_the_requirement_not_a_reason_to_doubt_the_answer():
    import cognitive.chat_bridge as bridge
    from cognitive.planning import TaskPlan
    from cognitive.state import PlannedTask
    report = bridge._verify(
        GOOD_CODE, _decision(QUESTION),
        TaskPlan(tasks=[PlannedTask(task_id=CHAT_TASK, objective="x")]))
    entry = [u for u in report.unverifiable if "EXECUTION_TEST" in u][0]
    assert entry.startswith("EXECUTION_TEST:")
    assert bridge._UNAVAILABLE_NOTE in entry


# ── ACT is still driven only by real findings ────────────────────────────────
def test_act_is_not_triggered_by_an_unavailable_requirement():
    """An unavailable check produces no failure, so nothing to correct."""
    r = refine(QUESTION, GOOD_CODE)
    assert r.changed is False
    assert r.remedy_applied is None


def test_act_still_runs_on_a_real_finding():
    r = refine(QUESTION, CUT_FENCE)
    assert r.remedy_applied == "unclosed_fence"


def test_provenance_is_unchanged_by_the_alignment():
    for answer in (GOOD_CODE, CUT_FENCE, BROKEN_CODE):
        r = refine(QUESTION, answer)
        if r.verified_digest is not None:
            assert r.verified_digest == artifact_digest(r.answer)


def test_the_four_statuses_remain_distinct():
    """NOT_REQUIRED, VERIFIED and FAILED must all still be reachable — the
    alignment must not collapse them into one optimistic answer."""
    seen = {
        refine("what is the capital of France?", PROSE).verification_status,
        refine(QUESTION, GOOD_CODE).verification_status,
        refine(QUESTION, BROKEN_CODE).verification_status,
    }
    assert seen == {VerificationStatus.NOT_REQUIRED.value,
                    VerificationStatus.VERIFIED.value,
                    VerificationStatus.FAILED.value}


# ── F/G: the app.py wiring, end to end ───────────────────────────────────────
@pytest.fixture(scope="module")
def app_module():
    """app.py takes ~30s to import. One module-scoped import, skipped on failure."""
    import sys, os
    for rel in ("", "runtime_engine", "review_engine"):
        p = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", rel))
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
    try:
        import app
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"app.py not importable here: {type(exc).__name__}: {exc}")
    return app


def _finalize(app, payload, question=""):
    return asyncio.run(app._finalize_response(payload, [], "test_user", None, question))


def test_app_wires_the_engine_in(app_module):
    assert app_module.COGNITIVE_ENGINE_AVAILABLE is True
    assert "question" in __import__("inspect").signature(
        app_module._finalize_response).parameters


def test_finalize_response_runs_the_engine(app_module):
    out = _finalize(app_module, {"answer": GOOD_CODE}, QUESTION)
    assert out["cognitive"]["ran"] is True
    assert out["cognitive"]["corrected"] is False
    assert out["answer"] == GOOD_CODE


def test_finalize_response_applies_a_remedy(app_module):
    out = _finalize(app_module, {"answer": CUT_FENCE}, QUESTION)
    assert out["cognitive"]["corrected"] is True
    assert out["cognitive"]["remedy"] == "unclosed_fence"
    assert out["answer"] != CUT_FENCE
    assert codes(out["answer"]) == []


def test_the_corrected_answer_still_passes_the_outbound_gate(app_module):
    """The bypass this ordering exists to prevent: a corrected answer must
    still be inspected by the firewall."""
    out = _finalize(app_module, {"answer": CUT_FENCE}, QUESTION)
    assert "security" in out, "the outbound gate ran after the correction"
    assert "outbound" in out["security"]


def test_both_answer_and_response_keys_are_corrected(app_module):
    """The RAG return path sets both; they must not drift apart."""
    out = _finalize(app_module, {"answer": CUT_FENCE, "response": CUT_FENCE},
                    QUESTION)
    assert out["answer"] == out["response"]


def test_an_existing_payload_is_otherwise_untouched(app_module):
    payload = {"answer": PROSE, "sources": ["a"], "confidence": 0.9,
               "provider": "groq", "intent": "chat"}
    out = _finalize(app_module, dict(payload), QUESTION)
    for key, value in payload.items():
        if key == "answer":
            continue
        assert out[key] == value, key
    assert out["answer"] == PROSE


def test_an_empty_answer_short_circuits_before_the_engine(app_module):
    out = _finalize(app_module, {"answer": ""}, QUESTION)
    assert "cognitive" not in out
    assert out["security"] == {"inbound": [], "outbound": []}


def test_a_broken_engine_does_not_break_chat(app_module, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("bridge exploded")

    monkeypatch.setattr(app_module, "cognitive_refine", boom)
    out = _finalize(app_module, {"answer": GOOD_CODE}, QUESTION)
    assert out["answer"] == GOOD_CODE, "chat still answers"
    assert "security" in out, "and security still runs"


def test_the_engine_runs_before_the_outbound_gate(app_module):
    """Structural: order matters, and a later refactor could silently swap it."""
    import ast, io, inspect
    src = inspect.getsource(app_module._finalize_response)
    assert src.index("cognitive_refine") < src.index("_outbound_gate"), \
        "a correction that skipped outbound inspection would be a bypass"


def test_every_answer_bearing_return_passes_the_question(app_module):
    import inspect, re
    src = inspect.getsource(app_module.chat)
    calls = re.findall(r"_finalize_response\(", src)
    # \s* rather than a literal space: a compliant call that wraps its
    # arguments across lines is still compliant, and matching the line breaks
    # made this fail for a call site that did pass the question.
    passed = re.findall(r"_client_ip,\s*original_question", src)
    # EVERY call passes it — that is the property. The count itself is not:
    # this asserted exactly three until Update 29 routed the deterministic
    # chart return through the choke point as well, and a compliant fourth
    # return should not fail a test about compliance.
    assert calls, "chat() has no _finalize_response calls"
    assert len(calls) == len(passed), \
        f"{len(calls)} finalize calls but only {len(passed)} pass the question"


# ── R1 at the wiring: the call must be threaded and bounded ──────────────────
def test_the_engine_is_not_called_on_the_event_loop(app_module):
    """Structural, because the cost only shows up under concurrency and a
    refactor could quietly move it back inline."""
    import ast, inspect, textwrap
    src = inspect.getsource(app_module._finalize_response)
    tree = ast.parse(textwrap.dedent(src))

    # Parsed, not pattern-matched. A proximity window broke the moment a
    # comment was added between the two calls, and a regex then broke again
    # when the comment moved — the structure is what the test is about.
    def _name(node):
        return ast.unparse(node.func) if isinstance(node, ast.Call) else ""

    wrapped = [
        call for call in ast.walk(tree)
        if isinstance(call, ast.Call) and _name(call) == "asyncio.wait_for"
        and call.args and isinstance(call.args[0], ast.Call)
        and _name(call.args[0]) == "asyncio.to_thread"
        and call.args[0].args
        and ast.unparse(call.args[0].args[0]) == "cognitive_refine"
    ]
    assert wrapped, "refine() must run in a worker thread under a hard timeout"
    assert any(kw.arg == "timeout" for kw in wrapped[0].keywords), \
        "the timeout must be given, not defaulted away"
    assert "asyncio.TimeoutError" in src, "with the timeout actually handled"


def test_a_slow_engine_does_not_stall_the_reply(app_module, monkeypatch):
    """A hung node must cost the configured timeout, not review_engine's 10s.

    The elapsed time is measured around the AWAIT, not around asyncio.run:
    run() joins the default executor at loop shutdown, so it waits for the
    abandoned worker however fast the reply itself was. Production keeps one
    long-lived loop, so that join never happens per request — the thread simply
    lingers, exactly as the outbound gate already documents for its own.
    """
    import asyncio, time
    from cognitive.chat_bridge import ChatRefinement

    def crawl(question, answer):
        time.sleep(5)
        return ChatRefinement(answer="SHOULD NEVER BE USED", changed=True)

    monkeypatch.setattr(app_module, "cognitive_refine", crawl)
    monkeypatch.setattr(app_module, "cognitive_timeout_seconds", lambda: 0.2)

    async def scenario():
        t0 = time.perf_counter()
        out = await app_module._finalize_response(
            {"answer": GOOD_CODE}, [], "u", None, QUESTION)
        return out, time.perf_counter() - t0

    out, elapsed = asyncio.run(scenario())
    assert elapsed < 3, f"the reply waited {elapsed:.1f}s on a timed-out engine"
    assert out["answer"] == GOOD_CODE, "and the original answer was returned"
    assert "SHOULD NEVER BE USED" not in out["answer"]


def test_a_timed_out_engine_still_runs_the_outbound_gate(app_module, monkeypatch):
    """The failure must not become a security bypass."""
    import time
    from cognitive.chat_bridge import ChatRefinement

    def crawl(question, answer):
        time.sleep(5)
        return ChatRefinement(answer=answer)

    monkeypatch.setattr(app_module, "cognitive_refine", crawl)
    monkeypatch.setattr(app_module, "cognitive_timeout_seconds", lambda: 0.2)
    out = _finalize(app_module, {"answer": GOOD_CODE}, QUESTION)
    assert "security" in out and "outbound" in out["security"]


def test_the_event_loop_keeps_ticking_while_the_engine_runs(app_module):
    """Behavioural proof of the fix: other requests are still served."""
    import asyncio, time

    async def scenario():
        stalls = []

        async def heartbeat(stop):
            while not stop.is_set():
                t = time.perf_counter()
                await asyncio.sleep(0.001)
                stalls.append((time.perf_counter() - t) * 1000)

        stop = asyncio.Event()
        hb = asyncio.create_task(heartbeat(stop))
        await asyncio.sleep(0.05)
        js = "Here:\n" + FENCE + "javascript\nfunction f(){return 1}\n" + FENCE + "\n"
        await asyncio.gather(*[
            app_module._finalize_response({"answer": js}, [], "u", None, QUESTION)
            for _ in range(3)])
        await asyncio.sleep(0.05)
        stop.set()
        await hb
        return max(stalls)

    worst = asyncio.run(scenario())
    assert worst < 150, (
        f"worst event-loop stall {worst:.0f}ms — inline this measured 274ms")


# ── R2 at the wiring: the hook and the loop share one payload ────────────────
def _count_reviews(app_module, monkeypatch):
    """Counts real pipeline executions across BOTH callers."""
    import cognitive.verification as v
    box = {"n": 0}
    real = v.run_review_pipeline

    def counted(text, mode="standard", **kw):
        box["n"] += 1
        return real(text, mode, **kw)

    monkeypatch.setattr(v, "run_review_pipeline", counted)
    if getattr(app_module, "run_review_pipeline", None) is not None:
        monkeypatch.setattr(app_module, "run_review_pipeline", counted)
    return box


@pytest.fixture
def production_review(app_module, monkeypatch):
    """Bind review_engine the way production does.

    Under pytest, app.py's own `from review_engine.integration_adapter import ...`
    fails — src/review_engine/ is on sys.path, so the FILE shadows the PACKAGE
    (the Step 0.5 defect). REVIEW_ENGINE_AVAILABLE is therefore False here and
    derive_status is None, so app.py's review hook cannot run at all in tests.
    The cognitive module's dual import survives that, which is why the engine
    works where the hook does not. Production has only src/ on the path and
    both resolve, so these tests bind that configuration explicitly rather than
    asserting against an artefact of the test environment.
    """
    from cognitive.verification import derive_status as working_derive_status
    monkeypatch.setattr(app_module, "REVIEW_ENGINE_AVAILABLE", True)
    monkeypatch.setattr(app_module, "derive_status", working_derive_status)
    return app_module


def _chat_order(app_module, answer, cache):
    """Reproduces chat()'s real sequence: review hook, then _finalize_response."""
    from cognitive.verification import derive_status
    payload = {"answer": answer}
    review = app_module.cognitive_review_once(answer, cache)
    if review is not None:
        status = derive_status(review)
        payload["review"] = {"status": status["status"], "badge": status["badge"]}
    return asyncio.run(app_module._finalize_response(
        payload, [], "u", None, QUESTION, cache))


def test_a_normal_answer_is_reviewed_exactly_once(production_review, app_module, monkeypatch):
    box = _count_reviews(app_module, monkeypatch)
    cache = app_module.cognitive_new_review_cache()
    out = _chat_order(app_module, GOOD_CODE, cache)
    assert box["n"] == 1, f"one artefact, one review; got {box['n']}"
    assert out["answer"] == GOOD_CODE


def test_a_corrected_answer_is_reviewed_exactly_twice(production_review, app_module, monkeypatch):
    """Two distinct artefacts, two reviews — not three. The saving is the
    duplicate, never a check."""
    box = _count_reviews(app_module, monkeypatch)
    cache = app_module.cognitive_new_review_cache()
    out = _chat_order(app_module, CUT_FENCE, cache)
    assert box["n"] == 2, f"original + corrected; got {box['n']}"
    assert out["cognitive"]["corrected"] is True


def test_the_badge_describes_the_answer_actually_returned(production_review, app_module, monkeypatch):
    """The bug the shared cache also fixes: chat()'s review hook runs BEFORE
    the correction, so the attached badge said FAILED for an answer that had
    since been repaired."""
    cache = app_module.cognitive_new_review_cache()
    out = _chat_order(app_module, CUT_FENCE, cache)
    assert out["answer"] != CUT_FENCE, "the answer was corrected"
    assert out["review"]["status"] != "FAILED", \
        "the badge must not describe the superseded artefact"
    assert codes(out["answer"]) == []


def test_an_uncorrected_answer_keeps_its_original_badge(production_review, app_module):
    cache = app_module.cognitive_new_review_cache()
    out = _chat_order(app_module, BROKEN_CODE, cache)
    assert out["answer"] == BROKEN_CODE
    assert out["review"]["status"] == "FAILED", "a real defect is still reported"


def test_a_full_debug_review_keeps_its_shape_after_a_refresh(production_review, app_module):
    """Refreshing must not turn a debug payload into the minimal badge."""
    cache = app_module.cognitive_new_review_cache()
    review = app_module.cognitive_review_once(CUT_FENCE, cache)
    full = dict(review)
    full.update(app_module.derive_status(review))
    payload = {"answer": CUT_FENCE, "review": full}
    out = asyncio.run(app_module._finalize_response(
        payload, [], "u", None, QUESTION, cache))
    assert set(out["review"]) > {"status", "badge"}, "the debug object survived"
    assert "review_meta" in out["review"]


def test_sharing_survives_the_engine_being_unavailable(app_module, monkeypatch):
    """Fail-open: with no cognitive engine the hook runs the pipeline itself."""
    monkeypatch.setattr(app_module, "COGNITIVE_ENGINE_AVAILABLE", False)
    box = _count_reviews(app_module, monkeypatch)
    out = asyncio.run(app_module._finalize_response(
        {"answer": GOOD_CODE}, [], "u", None, QUESTION, None))
    assert out["answer"] == GOOD_CODE
    assert "security" in out, "and security still runs"


def test_a_timeout_leaves_the_original_answer_and_its_badge(production_review, app_module, monkeypatch):
    import time
    from cognitive.chat_bridge import ChatRefinement

    def crawl(question, answer, *a, **k):
        time.sleep(5)
        return ChatRefinement(answer=answer)

    monkeypatch.setattr(app_module, "cognitive_refine", crawl)
    monkeypatch.setattr(app_module, "cognitive_timeout_seconds", lambda: 0.2)
    cache = app_module.cognitive_new_review_cache()
    out = _chat_order(app_module, CUT_FENCE, cache)
    assert out["answer"] == CUT_FENCE, "the original answer continues"
    assert out["review"]["status"] == "FAILED", "with the badge it already had"
    assert "security" in out


def test_the_outbound_gate_still_runs_last(production_review, app_module):
    cache = app_module.cognitive_new_review_cache()
    out = _chat_order(app_module, CUT_FENCE, cache)
    assert "security" in out and "outbound" in out["security"]


def test_the_response_shape_gained_nothing_beyond_cognitive(production_review, app_module):
    cache = app_module.cognitive_new_review_cache()
    out = _chat_order(app_module, GOOD_CODE, cache)
    assert set(out) == {"answer", "review", "cognitive", "security"}, sorted(out)


# ── the cache reaches refine() by keyword, not by position ───────────────────
def test_the_cache_is_passed_by_keyword(app_module):
    """Positionally it sat behind `context` and `has_image`, so reordering
    refine()'s signature would have passed the cache as a bool in silence."""
    import ast, inspect, textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(app_module._finalize_response)))
    # Parsed, not sliced: the previous regex stopped at the first ")", which
    # now lands inside _history_context(history) rather than at the call's end.
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and ast.unparse(n.func) == "asyncio.to_thread"
             and n.args and ast.unparse(n.args[0]) == "cognitive_refine"]
    assert calls, "the threaded call must exist"
    keywords = {kw.arg for kw in calls[0].keywords}
    assert "review_cache" in keywords, "the cache must be passed by keyword"
    assert "context" in keywords, "and so must the conversation context"
    positional = [ast.unparse(a) for a in calls[0].args[1:]]
    assert "None" not in positional and "False" not in positional,         "no positional placeholders"


def test_reordering_refine_signature_cannot_misroute_the_cache(app_module, monkeypatch):
    """Behavioural: whatever the parameter order, the cache lands on the cache
    parameter."""
    seen = {}

    def spy(question, answer, context=None, has_image=False, review_cache=None):
        seen["review_cache"] = review_cache
        seen["has_image"] = has_image
        seen["context"] = context
        seen["called"] = True
        from cognitive.chat_bridge import ChatRefinement
        return ChatRefinement(answer=answer)

    monkeypatch.setattr(app_module, "cognitive_refine", spy)
    cache = app_module.cognitive_new_review_cache()
    asyncio.run(app_module._finalize_response(
        {"answer": GOOD_CODE}, [], "u", None, QUESTION, cache))
    assert seen["review_cache"] is cache
    assert seen["has_image"] is False
    assert seen["context"] == [], "history is now passed, and empty means none"


# ── an unavailable review leaves the badge alone ─────────────────────────────
def test_an_unavailable_review_leaves_the_existing_badge(production_review, app_module,
                                                         monkeypatch):
    """`if not fresh` also swallowed an empty payload; `is None` is exact, and
    None is the only value that means 'could not review'."""
    monkeypatch.setattr(app_module, "cognitive_review_once", lambda *a, **k: None)
    payload = {"answer": CUT_FENCE, "review": {"status": "FAILED", "badge": True}}
    app_module._refresh_review(payload, "anything", None)
    assert payload["review"] == {"status": "FAILED", "badge": True}


def test_an_empty_payload_is_a_result_not_an_absence(production_review, app_module,
                                                     monkeypatch):
    """What separates `is None` from `not fresh`.

    None means "could not review" — leave the badge alone. An empty payload
    means "reviewed, nothing to report", which should update the badge rather
    than leave a stale FAILED standing. review_once never returns {} today, so
    this pins the intent rather than a reachable path.
    """
    monkeypatch.setattr(app_module, "cognitive_review_once", lambda *a, **k: {})
    payload = {"answer": GOOD_CODE, "review": {"status": "FAILED", "badge": True}}
    app_module._refresh_review(payload, GOOD_CODE, None)
    assert payload["review"] != {"status": "FAILED", "badge": True}, \
        "an empty verdict is still a verdict; the stale badge must not survive"


def test_a_present_review_still_refreshes_the_badge(production_review, app_module):
    cache = app_module.cognitive_new_review_cache()
    out = _chat_order(app_module, CUT_FENCE, cache)
    assert out["review"]["status"] != "FAILED"


def test_refresh_is_a_no_op_when_nothing_was_attached(production_review, app_module):
    payload = {"answer": GOOD_CODE}
    app_module._refresh_review(payload, GOOD_CODE, None)
    assert "review" not in payload


# ═══════════════════════════════════════════════════════════════════════════
# Conversation context reaches the engine.
#
# Found by replaying 906 real user messages: 42% classified CLARIFICATION for
# "refers to something not present in this conversation" — on messages with a
# median of 56 words. Long messages do not lack referents; they lacked HISTORY.
# The bridge was called without any, so every turn was judged as if it were the
# first in the conversation. 282 of 906 (31%) flip once history is passed.
#
# No unit test could have caught this: every test constructs its own context.
# ═══════════════════════════════════════════════════════════════════════════

FOLLOW_UP = "make it faster"
PRIOR = ["how do I sort a list in python?",
         "Use sorted(), which returns a new list."]


def test_a_follow_up_without_history_is_ambiguous():
    """The premise. Alone, this genuinely does refer to something absent."""
    r = refine(FOLLOW_UP, "Use sorted() with a key function.")
    assert r.needs_clarification is True


def test_the_same_follow_up_with_history_is_not():
    r = refine(FOLLOW_UP, "Use sorted() with a key function.", context=PRIOR)
    assert r.needs_clarification is False, \
        "the referent is in the conversation the engine was finally shown"


def test_context_changes_the_strategy_not_just_the_flag():
    from cognitive.understanding import understand
    from cognitive.assessment import assess
    from cognitive.strategy import select_strategy
    from cognitive.verification import available_requirements
    avail = available_requirements()
    without = select_strategy(understand(FOLLOW_UP),
                              assess(understand(FOLLOW_UP), problem=FOLLOW_UP),
                              problem=FOLLOW_UP, available=avail)
    u = understand(FOLLOW_UP, context=PRIOR)
    with_ = select_strategy(u, assess(u, context=PRIOR, problem=FOLLOW_UP),
                            problem=FOLLOW_UP, available=avail)
    assert without.strategy is not with_.strategy


def test_context_never_reaches_the_response():
    """History is a presence signal, not material to reason over. None of it
    may travel into what /chat returns."""
    private = "my bank sort code is 40-11-22"
    r = refine(FOLLOW_UP, "Use sorted() with a key function.",
               context=[private, "ok"])
    assert private not in r.model_dump_json()
    assert "40-11-22" not in str(r.summary())


def test_refine_survives_malformed_context():
    for junk in ([None], [{}], [123], ["", "   "], [object()]):
        r = refine(FOLLOW_UP, "an answer", context=junk)
        assert isinstance(r.answer, str)


# ── the app.py wiring ────────────────────────────────────────────────────────
def test_history_is_converted_to_the_shape_the_engine_declares(app_module):
    got = app_module._history_context([
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "second"},
    ])
    assert got == ["first", "second"]
    assert all(isinstance(x, str) for x in got)


def test_history_conversion_survives_junk(app_module):
    assert app_module._history_context(None) == []
    assert app_module._history_context([]) == []
    assert app_module._history_context([{}, {"content": ""},
                                        {"content": "   "}]) == []
    assert app_module._history_context([{"content": "kept"}, None, 42]) == \
        ["kept", "42"]


def test_history_is_bounded(app_module):
    many = [{"role": "user", "content": f"turn {i}"} for i in range(50)]
    assert len(app_module._history_context(many)) <= 8


def test_finalize_response_passes_history_to_the_engine(app_module, monkeypatch):
    seen = {}

    def spy(question, answer, context=None, has_image=False, review_cache=None):
        seen["context"] = context
        from cognitive.chat_bridge import ChatRefinement
        return ChatRefinement(answer=answer)

    monkeypatch.setattr(app_module, "cognitive_refine", spy)
    asyncio.run(app_module._finalize_response(
        {"answer": GOOD_CODE}, [], "u", None, QUESTION, None,
        [{"role": "user", "content": "earlier turn"}]))
    assert seen["context"] == ["earlier turn"]


def test_every_chat_return_passes_its_history(app_module):
    """Every answer-bearing return, the same funnel the question and the
    review cache already travel through.

    The count is deliberately not pinned. It was three until Update 29 routed
    the deterministic chart return through the choke point too, and a test
    about whether each call complies should not fail because a fourth
    compliant one appeared.
    """
    import ast, inspect, textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(app_module.chat)))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and ast.unparse(n.func) == "_finalize_response"]
    assert calls, "chat() has no answer-bearing returns"
    for call in calls:
        # Counting "req.history" anywhere in the source is not enough — chat()
        # uses it for the RAG payload too, so one call site could drop it and
        # the count would still pass.
        passed = [ast.unparse(a) for a in call.args] + \
                 [ast.unparse(kw.value) for kw in call.keywords]
        assert "req.history" in passed, \
            f"a /chat return reaches the engine without its history: {passed}"


def test_no_history_still_works(app_module, monkeypatch):
    """Absent history must behave exactly as before — a first message really is
    a first message."""
    seen = {}

    def spy(question, answer, context=None, has_image=False, review_cache=None):
        seen["context"] = context
        from cognitive.chat_bridge import ChatRefinement
        return ChatRefinement(answer=answer)

    monkeypatch.setattr(app_module, "cognitive_refine", spy)
    out = asyncio.run(app_module._finalize_response(
        {"answer": GOOD_CODE}, [], "u", None, QUESTION))
    assert seen["context"] == []
    assert out["answer"] == GOOD_CODE
