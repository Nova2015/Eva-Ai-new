"""Tests for the CognitiveState model (Step 2).

Covers the six areas the step requires — valid state, invalid state,
serialization, state transitions, retry limits, verification status — plus the
two safety rules the model claims to enforce (no secrets, no chain-of-thought
field), because a claim that is documented but untested is just a comment.

Fully offline: no model calls, no network, no database.
"""

import pytest
from pydantic import ValidationError

try:
    from cognitive.state import (
        CognitivePhase, CognitiveState, ReasoningStrategy, TaskStatus,
        VerificationStatus, FailureCategory, ProblemUnderstanding,
        KnowledgeAssessment, StrategySelection, PlannedTask, ActionRecord,
        Observation, VerificationResult, LearningCandidate,
        redact_secrets, REDACTED, MAX_RETRIES_CEILING, MAX_TASKS_CEILING,
        REASON_MAX,
    )
except ImportError:  # running from src/cognitive directly
    from state import (  # type: ignore
        CognitivePhase, CognitiveState, ReasoningStrategy, TaskStatus,
        VerificationStatus, FailureCategory, ProblemUnderstanding,
        KnowledgeAssessment, StrategySelection, PlannedTask, ActionRecord,
        Observation, VerificationResult, LearningCandidate,
        redact_secrets, REDACTED, MAX_RETRIES_CEILING, MAX_TASKS_CEILING,
        REASON_MAX,
    )


# ── valid state ──────────────────────────────────────────────────────────────
def test_default_state_is_valid_and_starts_at_understand():
    s = CognitiveState()
    assert s.phase is CognitivePhase.UNDERSTAND
    assert s.retry_count == 0
    assert s.plan == []
    assert not s.is_terminal()
    assert s.session_id.startswith("cog_")


def test_fully_populated_state_is_valid():
    task = PlannedTask(objective="compute the total", required_capability="calculation")
    s = CognitiveState(
        problem="add up the invoice",
        understanding=ProblemUnderstanding(intent="calculate", confidence=0.9),
        assessment=KnowledgeAssessment(evidence_sufficient=True, confidence=0.8),
        strategy=StrategySelection(strategy=ReasoningStrategy.CALCULATION, reason="arithmetic"),
        plan=[task],
        current_task_id=task.task_id,
    )
    assert s.strategy.strategy is ReasoningStrategy.CALCULATION
    assert s.plan[0].status is TaskStatus.PENDING


def test_confidence_is_clamped_not_rejected():
    assert CognitiveState(confidence=5.0).confidence == 1.0
    assert CognitiveState(confidence=-2.0).confidence == 0.0


# ── invalid state ────────────────────────────────────────────────────────────
def test_unknown_field_is_rejected():
    # extra='forbid': a typo must fail loudly, not vanish between stages.
    with pytest.raises(ValidationError):
        CognitiveState(problm="typo")


def test_current_task_must_exist_in_plan():
    with pytest.raises(ValidationError):
        CognitiveState(current_task_id="task_does_not_exist")


def test_duplicate_task_ids_rejected():
    a = PlannedTask(task_id="task_dup", objective="one")
    b = PlannedTask(task_id="task_dup", objective="two")
    with pytest.raises(ValidationError):
        CognitiveState(plan=[a, b])


def test_dependency_on_unknown_task_rejected():
    t = PlannedTask(objective="second", depends_on=["task_missing"])
    with pytest.raises(ValidationError):
        CognitiveState(plan=[t])


def test_task_cannot_depend_on_itself():
    with pytest.raises(ValidationError):
        PlannedTask(task_id="task_self", depends_on=["task_self"])


def test_plan_longer_than_max_tasks_rejected():
    tasks = [PlannedTask(objective=f"t{i}") for i in range(4)]
    with pytest.raises(ValidationError):
        CognitiveState(plan=tasks, max_tasks=3)


@pytest.mark.parametrize("bad", [-1, MAX_RETRIES_CEILING + 1])
def test_max_retries_bounds_enforced(bad):
    with pytest.raises(ValidationError):
        CognitiveState(max_retries=bad)


@pytest.mark.parametrize("bad", [0, MAX_TASKS_CEILING + 1])
def test_max_tasks_bounds_enforced(bad):
    with pytest.raises(ValidationError):
        CognitiveState(max_tasks=bad)


# ── serialization ────────────────────────────────────────────────────────────
def test_roundtrip_preserves_state():
    task = PlannedTask(objective="fetch docs", required_capability="retrieval")
    s = CognitiveState(
        problem="what does the manual say",
        plan=[task],
        current_task_id=task.task_id,
        strategy=StrategySelection(strategy=ReasoningStrategy.RETRIEVAL, reason="doc question"),
    )
    s.transition_to(CognitivePhase.ASSESS)
    restored = CognitiveState.from_dict(s.to_dict())
    assert restored.problem == s.problem
    assert restored.phase is CognitivePhase.ASSESS
    assert restored.plan[0].task_id == task.task_id
    assert restored.strategy.strategy is ReasoningStrategy.RETRIEVAL


def test_to_dict_is_json_safe():
    import json
    s = CognitiveState(problem="x")
    s.record_error(FailureCategory.TIMEOUT, "took too long")
    json.dumps(s.to_dict())  # must not raise — enums/datetimes already coerced


def test_enums_serialize_as_their_string_values():
    s = CognitiveState()
    s.transition_to(CognitivePhase.ASSESS)
    assert s.to_dict()["phase"] == "ASSESS"


# ── state transitions ────────────────────────────────────────────────────────
def test_happy_path_sequence():
    s = CognitiveState()
    for nxt in (CognitivePhase.ASSESS, CognitivePhase.STRATEGY, CognitivePhase.PLAN,
                CognitivePhase.ACT, CognitivePhase.VERIFY, CognitivePhase.LEARN):
        s.transition_to(nxt)
    assert s.phase is CognitivePhase.LEARN


def test_illegal_transition_rejected():
    s = CognitiveState()
    with pytest.raises(ValueError):
        s.transition_to(CognitivePhase.VERIFY)   # UNDERSTAND -> VERIFY skips everything


def test_adaptive_loop_explore_reassess_restrategise():
    """The architecture requires an adaptive mind, not a one-pass pipeline:
    act, discover something, reassess, change strategy, act differently.
    An earlier version of the graph blocked all three feedback edges."""
    s = CognitiveState()
    s.transition_to(CognitivePhase.ASSESS)
    s.transition_to(CognitivePhase.STRATEGY)
    s.transition_to(CognitivePhase.ACT)
    s.transition_to(CognitivePhase.ASSESS)      # evidence gathered -> reassess
    s.transition_to(CognitivePhase.STRATEGY)    # pick a different approach
    s.transition_to(CognitivePhase.ACT)         # try another capability
    s.transition_to(CognitivePhase.VERIFY)
    assert s.phase is CognitivePhase.VERIFY


@pytest.mark.parametrize("start,target", [
    (CognitivePhase.ACT, CognitivePhase.ASSESS),        # gather -> reassess
    (CognitivePhase.VERIFY, CognitivePhase.ASSESS),     # gap, not wrong answer
    (CognitivePhase.CORRECT, CognitivePhase.ASSESS),    # rethink evidence
    (CognitivePhase.CORRECT, CognitivePhase.STRATEGY),  # approach was wrong
    (CognitivePhase.CORRECT, CognitivePhase.UNDERSTAND),# problem was misread
    (CognitivePhase.PLAN, CognitivePhase.STRATEGY),     # plan exposed a bad strategy
])
def test_feedback_edges_exist(start, target):
    assert CognitiveState(phase=start).can_transition_to(target)


def test_cyclic_graph_still_terminates():
    """The graph is cyclic, so termination cannot come from the graph. A
    caller that never touches the retry budget must still be stopped."""
    s = CognitiveState(max_transitions=10)
    cycle = [CognitivePhase.ASSESS, CognitivePhase.STRATEGY, CognitivePhase.ACT]
    with pytest.raises(ValueError, match="transition budget exhausted"):
        for _ in range(20):                      # would loop forever unbounded
            for step in cycle:
                s.transition_to(step)
    assert s.transition_count == 10
    assert s.retry_count == 0                    # never consumed a retry


def test_terminating_is_always_possible_after_budget_exhausted():
    s = CognitiveState(max_transitions=2)
    s.transition_to(CognitivePhase.ASSESS)
    s.transition_to(CognitivePhase.STRATEGY)
    assert s.transitions_remaining() == 0
    assert not s.can_transition_to(CognitivePhase.ACT)
    assert s.can_transition_to(CognitivePhase.ABORTED)   # must remain reachable
    s.transition_to(CognitivePhase.ABORTED)
    assert s.is_terminal()


def test_transition_count_is_independent_of_retry_count():
    s = CognitiveState()
    s.transition_to(CognitivePhase.ASSESS)
    s.transition_to(CognitivePhase.STRATEGY)
    assert s.transition_count == 2 and s.retry_count == 0


@pytest.mark.parametrize("bad", [0, 101])
def test_max_transitions_bounds_enforced(bad):
    with pytest.raises(ValidationError):
        CognitiveState(max_transitions=bad)


# The budget has to be a ratchet, not a range check. validate_assignment only
# verifies type and ceiling, so without these an engine could raise its own
# budget or reset the counter and re-open the unbounded loop the budget exists
# to prevent — the graph is cyclic, so nothing else would stop it.
def test_budget_cannot_be_raised_after_creation():
    s = CognitiveState(max_transitions=5)
    s.transition_to(CognitivePhase.ASSESS)
    with pytest.raises(ValidationError):
        s.max_transitions = 99


def test_transition_count_cannot_be_reset():
    s = CognitiveState(max_transitions=5)
    s.transition_to(CognitivePhase.ASSESS)
    with pytest.raises(ValidationError):
        s.transition_count = 0


def test_transition_count_cannot_be_rewound():
    s = CognitiveState(max_transitions=5)
    s.transition_to(CognitivePhase.ASSESS)
    s.transition_to(CognitivePhase.STRATEGY)
    with pytest.raises(ValidationError):
        s.transition_count = 1


def test_budget_may_still_be_lowered():
    # Tightening is always safe; only loosening re-opens the loop.
    s = CognitiveState(max_transitions=6)
    s.transition_to(CognitivePhase.ASSESS)
    s.max_transitions = 3
    assert s.max_transitions == 3


def test_ratchet_survives_deserialization():
    s = CognitiveState(max_transitions=5)
    s.transition_to(CognitivePhase.ASSESS)
    s.transition_to(CognitivePhase.STRATEGY)
    restored = CognitiveState.from_dict(s.to_dict())
    assert restored.transition_count == 2
    with pytest.raises(ValidationError):
        restored.transition_count = 0
    with pytest.raises(ValidationError):
        restored.max_transitions = 100


def test_ratchet_internals_are_not_serialized():
    dumped = CognitiveState().to_dict()
    assert "_budget_ceiling" not in dumped and "_count_floor" not in dumped


def test_correct_loops_back_to_plan():
    s = CognitiveState()
    for nxt in (CognitivePhase.ASSESS, CognitivePhase.STRATEGY, CognitivePhase.PLAN,
                CognitivePhase.ACT, CognitivePhase.VERIFY, CognitivePhase.CORRECT):
        s.transition_to(nxt)
    s.transition_to(CognitivePhase.PLAN)         # the retry loop
    assert s.phase is CognitivePhase.PLAN


def test_act_can_repeat_for_multi_step_plans():
    s = CognitiveState()
    for nxt in (CognitivePhase.ASSESS, CognitivePhase.STRATEGY, CognitivePhase.ACT):
        s.transition_to(nxt)
    s.transition_to(CognitivePhase.ACT)
    assert s.phase is CognitivePhase.ACT


def test_abort_is_reachable_from_any_live_phase():
    for start in (CognitivePhase.UNDERSTAND, CognitivePhase.ASSESS, CognitivePhase.ACT,
                  CognitivePhase.VERIFY, CognitivePhase.CORRECT):
        s = CognitiveState(phase=start)
        assert s.can_transition_to(CognitivePhase.ABORTED)


def test_terminal_phases_are_final():
    for terminal in (CognitivePhase.RESPOND, CognitivePhase.ABORTED):
        s = CognitiveState(phase=terminal)
        assert s.is_terminal()
        assert not s.can_transition_to(CognitivePhase.ACT)
        with pytest.raises(ValueError):
            s.transition_to(CognitivePhase.RESPOND)


# ── retry limits ─────────────────────────────────────────────────────────────
def test_retry_budget_is_consumed_then_refused():
    s = CognitiveState(max_retries=2)
    assert s.register_retry() is True
    assert s.register_retry() is True
    assert s.register_retry() is False        # exhausted, and says so rather than raising
    assert s.retry_count == 2                 # never exceeds the budget
    assert s.retries_remaining() == 0


def test_zero_retry_budget_refuses_immediately():
    s = CognitiveState(max_retries=0)
    assert s.register_retry() is False
    assert s.retry_count == 0


def test_retry_cannot_be_bypassed_by_assignment():
    # validate_assignment=True — the ceiling holds after construction too.
    s = CognitiveState(max_retries=1)
    with pytest.raises(ValidationError):
        s.max_retries = MAX_RETRIES_CEILING + 5


# ── verification status ──────────────────────────────────────────────────────
def test_no_verifications_means_not_required():
    assert CognitiveState().verification_status() is VerificationStatus.NOT_REQUIRED


def test_all_verified_reports_verified():
    s = CognitiveState(verifications=[
        VerificationResult(status=VerificationStatus.VERIFIED),
        VerificationResult(status=VerificationStatus.VERIFIED),
    ])
    assert s.verification_status() is VerificationStatus.VERIFIED


def test_any_failure_dominates():
    s = CognitiveState(verifications=[
        VerificationResult(status=VerificationStatus.VERIFIED),
        VerificationResult(status=VerificationStatus.FAILED),
        VerificationResult(status=VerificationStatus.INCONCLUSIVE),
    ])
    assert s.verification_status() is VerificationStatus.FAILED


def test_inconclusive_beats_verified():
    s = CognitiveState(verifications=[
        VerificationResult(status=VerificationStatus.VERIFIED),
        VerificationResult(status=VerificationStatus.INCONCLUSIVE),
    ])
    assert s.verification_status() is VerificationStatus.INCONCLUSIVE


# ── safety rule 1: no secrets stored ─────────────────────────────────────────
@pytest.mark.parametrize("secret", [
    "sk-abcdefghijklmnop1234567890",
    "AKIAIOSFODNN7EXAMPLE",
    "ghp_abcdefghijklmnopqrstuvwxyz0123",
    "xoxb-1234567890-abcdefghij",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
    "api_key: hunter2secret",
    "Bearer abcdefghijklmnopqrstuvwxyz123456",
])
def test_secrets_are_redacted_from_free_text(secret):
    s = CognitiveState(problem=f"please debug this: {secret}")
    assert secret not in s.problem
    assert REDACTED in s.problem


def test_redaction_applies_across_nested_models_and_lists():
    s = CognitiveState(
        problem="ok",
        context=["token=abcdefghijklmnop", "harmless line"],
        understanding=ProblemUnderstanding(intent="use sk-abcdefghijklmnop1234567890"),
    )
    assert "abcdefghijklmnop" not in s.context[0]
    assert s.context[1] == "harmless line"
    assert "sk-abcdefghijklmnop1234567890" not in s.understanding.intent


def test_redaction_survives_serialization_roundtrip():
    s = CognitiveState(problem="key sk-abcdefghijklmnop1234567890 here")
    assert "sk-abcdefghijklmnop1234567890" not in CognitiveState.from_dict(s.to_dict()).problem


def test_every_free_text_field_is_scrubbed_not_just_the_obvious_ones():
    """A planner writing "verify key sk-... is valid" into a criterion would
    otherwise persist a live credential. 'No secrets in state' is unqualified,
    so identifier-ish list fields are covered too."""
    key = "sk-abcdefghijklmnop1234567890"
    task = PlannedTask(
        objective="check", required_tool=f"tool {key}",
        input_requirements=[f"needs {key}"],
        verification_criteria=[f"assert {key} works"],
    )
    sel = StrategySelection(required_capabilities=[f"cap {key}"], required_tools=[f"t {key}"])
    obs = Observation(evidence_refs=[f"doc {key}"])
    ver = VerificationResult(criteria=[f"criterion {key}"])
    for blob in (task.model_dump_json(), sel.model_dump_json(),
                 obs.model_dump_json(), ver.model_dump_json()):
        assert key not in blob


def test_ordinary_text_is_untouched():
    text = "How do I reverse a string in Python?"
    assert redact_secrets(text) == text
    assert CognitiveState(problem=text).problem == text


def test_redaction_never_raises_on_odd_input():
    for value in ("", "-----BEGIN PRIVATE KEY-----", "a" * 5000):
        redact_secrets(value)


# ── safety rule 2: no chain-of-thought storage ───────────────────────────────
def test_no_field_invites_a_reasoning_trace():
    banned = {"chain_of_thought", "reasoning", "thoughts", "scratchpad", "deliberation", "rationale_full"}
    for model in (CognitiveState, ProblemUnderstanding, KnowledgeAssessment,
                  StrategySelection, PlannedTask, ActionRecord, Observation,
                  VerificationResult, LearningCandidate):
        assert banned.isdisjoint(model.model_fields.keys()), f"{model.__name__} exposes a CoT field"


def test_rationale_fields_are_length_capped():
    long_trace = "step one, then step two, " * 500
    sel = StrategySelection(reason=long_trace)
    assert len(sel.reason) <= REASON_MAX


# ── learning safety ──────────────────────────────────────────────────────────
def test_learning_candidate_is_never_pre_approved():
    assert LearningCandidate().approved is False
    s = CognitiveState(learning_candidates=[LearningCandidate(summary="worked well")])
    assert all(c.approved is False for c in s.learning_candidates)


# ── misc helpers ─────────────────────────────────────────────────────────────
def test_record_error_appends_and_returns():
    s = CognitiveState()
    err = s.record_error(FailureCategory.TOOL_FAILURE, "web_search timed out", task_id=None)
    assert err.category is FailureCategory.TOOL_FAILURE
    assert len(s.errors) == 1


def test_action_and_observation_defaults_are_safe():
    a = ActionRecord(tool="rag_query")
    o = Observation(summary="found 3 chunks")
    assert a.authorized is False        # must be granted explicitly, never assumed
    assert a.ok is False
    assert o.observation_id.startswith("obs_")
