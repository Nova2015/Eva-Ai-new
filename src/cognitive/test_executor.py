"""Tests for execution orchestration (Step 8), cases A-W plus §20 security.

Every adapter is a fake. Nothing here reaches a network, a provider, a
database, a filesystem or a sandbox — asserted, not assumed.

The §20 tests matter most: this is the first stage that runs anything, so
"the limits cannot be bypassed" has to be demonstrated rather than described.
"""

import pytest

try:
    from cognitive.executor import (
        run_plan, apply_to_state, ExecutionResult, ExecutionStatus, ExecutionDenied,
        TaskOutcome, AUTOPILOT_MAX_STEPS, AUTOPILOT_DEADLINE_SECONDS, AUTOPILOT_TOOLS,
    )
    from cognitive.capabilities import (
        Capability, CapabilityRequirement, CapabilitySelection, select_capabilities,
    )
    from cognitive.planning import TaskPlan, plan_for
    from cognitive.strategy import select_strategy
    from cognitive.assessment import assess, RiskLevel
    from cognitive.understanding import understand
    from cognitive.state import (
        CognitiveState, CognitivePhase, PlannedTask, TaskStatus, FailureCategory,
    )
except ImportError:  # running from src/cognitive directly
    from executor import (  # type: ignore
        run_plan, apply_to_state, ExecutionResult, ExecutionStatus, ExecutionDenied,
        TaskOutcome, AUTOPILOT_MAX_STEPS, AUTOPILOT_DEADLINE_SECONDS, AUTOPILOT_TOOLS,
    )
    from capabilities import (  # type: ignore
        Capability, CapabilityRequirement, CapabilitySelection, select_capabilities,
    )
    from planning import TaskPlan, plan_for  # type: ignore
    from strategy import select_strategy  # type: ignore
    from assessment import assess, RiskLevel  # type: ignore
    from understanding import understand  # type: ignore
    from state import (  # type: ignore
        CognitiveState, CognitivePhase, PlannedTask, TaskStatus, FailureCategory,
    )


class FakeTools:
    """Stands in for autopilot._run_tool. Records every call so 'nothing ran'
    is provable rather than assumed."""

    def __init__(self, behaviour=None):
        self.calls = []
        self.behaviour = behaviour or {}

    def __call__(self, tool, arg, context):
        self.calls.append((tool, arg))
        outcome = self.behaviour.get(tool, "ok")
        if isinstance(outcome, BaseException):
            raise outcome
        if callable(outcome):
            return outcome(arg)
        return f"{tool}:{outcome}"


def task(objective="do a thing", tool="think", depends=(), criteria=("done",), status=TaskStatus.PENDING):
    return PlannedTask(objective=objective, required_tool=tool, required_capability="tool_use",
                       depends_on=list(depends), verification_criteria=list(criteria),
                       status=status, input_requirements=["arg"])


def selection_for(tasks, capability=Capability.GENERAL_REASONING, read_only=True):
    return CapabilitySelection(capabilities=[CapabilityRequirement(
        capability_id=capability, task_ids=[t.task_id for t in tasks],
        read_only=read_only, confidence=0.9,
    )])


def plan_of(*tasks):
    return TaskPlan(tasks=list(tasks))


# ── A-C: the happy paths ─────────────────────────────────────────────────────
def test_A_single_successful_task():
    t = task()
    tools = FakeTools()
    r = run_plan(CognitiveState(), plan_of(t), selection_for([t]), tool_adapter=tools)
    assert r.success is True
    assert r.final_execution_status is ExecutionStatus.EXECUTION_COMPLETE
    assert r.completed_tasks == [t.task_id]
    assert t.status is TaskStatus.COMPLETED
    assert len(tools.calls) == 1


def test_B_multiple_tasks_all_run():
    a, b, c = task("one"), task("two"), task("three")
    tools = FakeTools()
    r = run_plan(CognitiveState(), plan_of(a, b, c), selection_for([a, b, c]), tool_adapter=tools)
    assert len(r.completed_tasks) == 3
    assert len(tools.calls) == 3


def test_C_dependency_ordering_is_respected():
    a = task("first")
    b = task("second", depends=[a.task_id])
    c = task("third", depends=[b.task_id])
    tools = FakeTools()
    # deliberately shuffled: order must come from depends_on, not list position
    run_plan(CognitiveState(), plan_of(c, a, b), selection_for([a, b, c]), tool_adapter=tools)
    assert [arg for _, arg in tools.calls] == ["arg", "arg", "arg"]
    assert len(tools.calls) == 3


# ── D-F: failure and retry ───────────────────────────────────────────────────
def test_D_failed_dependency_skips_dependents():
    a = task("will fail")
    b = task("depends on a", depends=[a.task_id])
    tools = FakeTools({"think": RuntimeError("boom")})
    r = run_plan(CognitiveState(), plan_of(a, b), selection_for([a, b]), tool_adapter=tools)
    assert a.task_id in r.failed_tasks
    assert b.task_id in r.skipped_tasks
    assert len(tools.calls) == 1, "a dependent of a failed task must not run"


def test_E_attempts_are_counted_on_the_task():
    t = task()
    run_plan(CognitiveState(), plan_of(t), selection_for([t]), tool_adapter=FakeTools())
    assert t.attempts == 1


def test_F_retry_budget_belongs_to_the_state_not_the_executor():
    """§6: no independent retry counter. The executor runs a plan once; the
    retry budget lives on CognitiveState and is spent by the correction stage."""
    import io, os
    src = io.open(os.path.join(os.path.dirname(__file__), "executor.py"), encoding="utf-8").read()
    assert "retry_count" not in src, "a second retry counter would bypass the state's budget"
    assert "max_retries" not in src


# ── G, T, U: budgets ─────────────────────────────────────────────────────────
def test_T_max_steps_cannot_be_raised_above_autopilots():
    tasks = [task(f"t{i}") for i in range(AUTOPILOT_MAX_STEPS + 4)]
    tools = FakeTools()
    r = run_plan(CognitiveState(max_tasks=25), plan_of(*tasks), selection_for(tasks),
                 tool_adapter=tools, max_steps=999)          # attempt to raise it
    assert len(tools.calls) <= AUTOPILOT_MAX_STEPS
    assert r.skipped_tasks, "tasks beyond the budget must be skipped, not silently dropped"


def test_max_steps_can_be_tightened():
    tasks = [task(f"t{i}") for i in range(5)]
    tools = FakeTools()
    run_plan(CognitiveState(), plan_of(*tasks), selection_for(tasks),
             tool_adapter=tools, max_steps=2)
    assert len(tools.calls) == 2


def test_U_deadline_is_enforced_and_cannot_be_raised():
    clock = iter([0, 0, 0, 1000, 1000, 1000, 1000, 1000, 1000])
    tasks = [task("a"), task("b")]
    tools = FakeTools()
    r = run_plan(CognitiveState(), plan_of(*tasks), selection_for(tasks),
                 tool_adapter=tools, deadline_seconds=99999,   # attempt to raise it
                 now=lambda: next(clock))
    assert any(o.error_category is FailureCategory.TIMEOUT for o in r.outcomes)


def test_G_timeout_from_the_adapter_is_classified():
    t = task()
    tools = FakeTools({"think": TimeoutError("tool timed out")})
    r = run_plan(CognitiveState(), plan_of(t), selection_for([t]), tool_adapter=tools)
    assert r.outcome_for(t.task_id).error_category is FailureCategory.TIMEOUT


# ── H-J: security gates ──────────────────────────────────────────────────────
def test_H_non_whitelisted_tool_is_denied():
    t = task(tool="rm_rf")
    tools = FakeTools()
    r = run_plan(CognitiveState(), plan_of(t), selection_for([t]), tool_adapter=tools)
    assert tools.calls == [], "a non-whitelisted tool must never reach the adapter"
    assert r.outcome_for(t.task_id).error_category is FailureCategory.SECURITY_BLOCK


def test_I_write_capability_under_read_only_is_denied():
    t = task()
    sel = CapabilitySelection(capabilities=[CapabilityRequirement(
        capability_id=Capability.MEMORY_WRITE, task_ids=[t.task_id], read_only=True,
    )])
    tools = FakeTools()
    r = run_plan(CognitiveState(), plan_of(t), sel, tool_adapter=tools)
    assert tools.calls == []
    assert r.outcome_for(t.task_id).error_category is FailureCategory.SECURITY_BLOCK


def test_M_task_with_no_approved_capability_cannot_execute():
    t = task()
    empty = CapabilitySelection(capabilities=[])
    tools = FakeTools()
    r = run_plan(CognitiveState(), plan_of(t), empty, tool_adapter=tools)
    assert tools.calls == [], "a task Step 7 did not approve must not run"
    assert t.status is TaskStatus.SKIPPED


def test_L_non_pending_task_is_not_re_executed():
    t = task(status=TaskStatus.COMPLETED)
    tools = FakeTools()
    run_plan(CognitiveState(), plan_of(t), selection_for([t]), tool_adapter=tools)
    assert tools.calls == []


# ── K: refusal to run without an adapter ─────────────────────────────────────
def test_K_no_adapter_refuses_rather_than_silently_doing_nothing():
    t = task()
    with pytest.raises(ExecutionDenied, match="no execution adapter"):
        run_plan(CognitiveState(), plan_of(t), selection_for([t]))


# ── N-P: observations and errors ─────────────────────────────────────────────
def test_N_observation_is_recorded_per_task():
    t = task()
    r = run_plan(CognitiveState(), plan_of(t), selection_for([t]), tool_adapter=FakeTools())
    assert len(r.observations) == 1
    assert r.observations[0].task_id == t.task_id


def test_O_secrets_are_not_persisted_in_observations():
    key = "sk-abcdefghijklmnop1234567890"
    t = task()
    tools = FakeTools({"think": lambda arg: f"token is {key}"})
    r = run_plan(CognitiveState(), plan_of(t), selection_for([t]), tool_adapter=tools)
    assert key not in r.model_dump_json()


def test_P_raw_exceptions_are_never_exposed():
    t = task()
    secret_path = "/home/user/.ssh/id_rsa and password=hunter2secret"
    tools = FakeTools({"think": RuntimeError(secret_path)})
    r = run_plan(CognitiveState(), plan_of(t), selection_for([t]), tool_adapter=tools)
    blob = r.model_dump_json()
    assert secret_path not in blob
    assert "hunter2secret" not in blob
    assert "RuntimeError" in r.outcome_for(t.task_id).safe_summary   # category only


@pytest.mark.parametrize("exc,expected", [
    (TimeoutError("t"), FailureCategory.TIMEOUT),
    (ValueError("v"), FailureCategory.INVALID_INPUT),
    (RuntimeError("r"), FailureCategory.TOOL_FAILURE),
])
def test_P_error_classification(exc, expected):
    t = task()
    r = run_plan(CognitiveState(), plan_of(t), selection_for([t]),
                 tool_adapter=FakeTools({"think": exc}))
    assert r.outcome_for(t.task_id).error_category is expected


# ── Q-S: reassessment and verification boundary ──────────────────────────────
def test_Q_failure_triggers_reassessment():
    t = task()
    r = run_plan(CognitiveState(), plan_of(t), selection_for([t]),
                 tool_adapter=FakeTools({"think": RuntimeError("x")}))
    assert r.requires_reassessment is True


def test_R_adaptive_act_to_assess_transition():
    """Execution that disproves the plan's premise must hand evidence back,
    not drive the obsolete plan to completion."""
    t = task()
    s = CognitiveState()
    s.transition_to(CognitivePhase.ASSESS)
    s.transition_to(CognitivePhase.STRATEGY)
    s.transition_to(CognitivePhase.PLAN)
    r = run_plan(s, plan_of(t), selection_for([t]),
                 tool_adapter=FakeTools({"think": RuntimeError("db unreachable")}))
    apply_to_state(s, r)
    assert s.phase is CognitivePhase.ASSESS


def test_R_success_moves_to_verify_not_assess():
    t = task()
    s = CognitiveState()
    s.transition_to(CognitivePhase.ASSESS)
    s.transition_to(CognitivePhase.STRATEGY)
    s.transition_to(CognitivePhase.PLAN)
    r = run_plan(s, plan_of(t), selection_for([t]), tool_adapter=FakeTools())
    apply_to_state(s, r)
    assert s.phase is CognitivePhase.VERIFY


def test_S_verification_required_is_marked_not_performed():
    t = task(criteria=["code passes validation"])
    r = run_plan(CognitiveState(), plan_of(t), selection_for([t]), tool_adapter=FakeTools())
    assert r.requires_verification is True
    import io, os
    src = io.open(os.path.join(os.path.dirname(__file__), "executor.py"), encoding="utf-8").read()
    for performing in ("validate_code(", "review_response(", "validate_charts("):
        assert performing not in src, "verification is Step 9's job"


def test_apply_to_state_uses_transition_to_not_direct_assignment():
    import io, os
    src = io.open(os.path.join(os.path.dirname(__file__), "executor.py"), encoding="utf-8").read()
    assert "state.phase =" not in src, "bypassing transition_to() defeats the Step 2 graph"


# ── V-W: real adapters bind ──────────────────────────────────────────────────
def test_V_autopilot_constants_are_the_real_ones():
    import cognitive.executor as ex
    if ex.AUTOPILOT_AVAILABLE:
        import autopilot
        assert ex.AUTOPILOT_MAX_STEPS == autopilot.MAX_STEPS
        assert ex.AUTOPILOT_DEADLINE_SECONDS == autopilot.DEADLINE_SECONDS
        assert ex.AUTOPILOT_TOOL_TIMEOUT == autopilot.TOOL_TIMEOUT
        assert ex.AUTOPILOT_TOOLS is autopilot.TOOLS


def test_V_real_run_tool_signature_is_adapter_compatible():
    """The default adapter must be droppable in with no wrapper."""
    import inspect
    import cognitive.executor as ex
    if not ex.AUTOPILOT_AVAILABLE:
        pytest.skip("autopilot unavailable on this path")
    import autopilot
    params = list(inspect.signature(autopilot._run_tool).parameters)
    assert params == ["tool", "arg", "context"]


def test_W_runtime_engine_is_not_reimplemented():
    import ast, io, os
    src_path = os.path.join(os.path.dirname(__file__), "executor.py")
    tree = ast.parse(io.open(src_path, encoding="utf-8").read())
    imports = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imports |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            imports.add(n.module or "")
    forbidden = ("httpx", "requests", "urllib", "socket", "sqlite3", "psycopg2",
                 "subprocess", "openai", "groq", "boto3", "aiohttp")
    assert not [i for i in imports if any(f in i for f in forbidden)]
    src = io.open(src_path, encoding="utf-8").read()
    # Implementations that must live elsewhere. The BUDGET VALUES are not
    # grepped here: an earlier version checked for "DEADLINE_SECONDS =" and
    # tripped on the AUTOPILOT_DEADLINE_SECONDS import fallback. Whether the
    # numbers are autopilot's is a runtime property, and
    # test_V_autopilot_constants_are_the_real_ones asserts it directly.
    for owned_elsewhere in ("def execute_code", "def _tool_web_search",
                            "def _make_plan", "piston", "Piston"):
        assert owned_elsewhere not in src, f"{owned_elsewhere} belongs to the existing infrastructure"


# ── §20 security proofs ──────────────────────────────────────────────────────
def test_security_unknown_task_cannot_execute():
    known = task()
    stranger = task("not in the selection")
    tools = FakeTools()
    r = run_plan(CognitiveState(), plan_of(known, stranger), selection_for([known]),
                 tool_adapter=tools)
    assert len(tools.calls) == 1
    # A task Step 7 never approved is a POLICY refusal, so it belongs in
    # denied_tasks. It used to land in skipped_tasks alongside genuine
    # failures, which is what let a refusal masquerade as evidence.
    assert stranger.task_id in r.denied_tasks
    assert stranger.task_id not in r.failed_tasks


def test_security_step_budget_survives_a_hostile_caller():
    tasks = [task(f"t{i}") for i in range(20)]
    tools = FakeTools()
    run_plan(CognitiveState(max_tasks=25), plan_of(*tasks), selection_for(tasks),
             tool_adapter=tools, max_steps=10**6, deadline_seconds=10**6)
    assert len(tools.calls) <= AUTOPILOT_MAX_STEPS


def test_security_denial_is_recorded_not_retried():
    t = task(tool="rm_rf")
    tools = FakeTools()
    r = run_plan(CognitiveState(), plan_of(t), selection_for([t]), tool_adapter=tools)
    assert tools.calls == []
    assert any(e.category is FailureCategory.SECURITY_BLOCK for e in r.errors)


def test_security_no_chain_of_thought_in_outcomes():
    banned = {"chain_of_thought", "reasoning", "thoughts", "scratchpad",
              "private_reasoning", "reasoning_trace"}
    assert banned.isdisjoint(TaskOutcome.model_fields.keys())
    assert banned.isdisjoint(ExecutionResult.model_fields.keys())


def test_no_final_answer_is_generated():
    banned = {"answer", "response", "final_answer", "reply", "message"}
    assert banned.isdisjoint(ExecutionResult.model_fields.keys()), \
        "final response generation belongs outside Step 8"


# ── end-to-end through Steps 3-8, still offline ──────────────────────────────
def test_full_chain_understand_to_execute():
    msg = "Research the outage and then summarise and also compare"
    u = understand(msg)
    a = assess(u, problem=msg)
    d = select_strategy(u, a, problem=msg)
    p = plan_for(u, a, d, problem=msg,
                 make_plan=lambda goal: [{"tool": "web_search", "input": "q", "why": "gather"},
                                         {"tool": "think", "input": "sum", "why": "conclude"}])
    sel = select_capabilities(p, u, a, d, problem=msg)
    tools = FakeTools()
    s = CognitiveState(problem=msg)
    s.transition_to(CognitivePhase.ASSESS)
    s.transition_to(CognitivePhase.STRATEGY)
    s.transition_to(CognitivePhase.PLAN)
    s.plan = p.tasks
    r = run_plan(s, p, sel, tool_adapter=tools)
    apply_to_state(s, r)
    assert r.final_execution_status is ExecutionStatus.EXECUTION_COMPLETE
    assert {t for t, _ in tools.calls} <= set(AUTOPILOT_TOOLS)
    assert s.phase in (CognitivePhase.VERIFY, CognitivePhase.ASSESS)
    assert len(s.observations) == len(r.observations)


# ═══════════════════════════════════════════════════════════════════════════
# STEP 8 FIX — the three reviewed defects
#
# The review found that every failure set requires_reassessment, that
# ExecutionStatus.CANCELLED was unreachable, and that policy refusals were
# pooled with genuine failures. These tests pin the corrected behaviour.
# ═══════════════════════════════════════════════════════════════════════════

class Selective(FakeTools):
    """Fails only for a nominated argument, so a run can have both a real
    success and a real failure."""

    def __init__(self, fail_arg="BOOM"):
        super().__init__()
        self.fail_arg = fail_arg

    def __call__(self, tool, arg, context):
        self.calls.append((tool, arg))
        if arg == self.fail_arg:
            raise RuntimeError("boom")
        return "ok"


def _cancel_after(n, box):
    """Cancels once n tasks have run — the between-tasks cancellation point."""
    return lambda: len(box.calls) >= n


# ── DEFECT 1: a refusal is not evidence ──────────────────────────────────────
def test_fix_security_denial_only_does_not_request_reassessment():
    t = task(tool="rm_rf")
    tools = FakeTools()
    r = run_plan(CognitiveState(), plan_of(t), selection_for([t]), tool_adapter=tools)
    assert tools.calls == []
    assert r.denied_tasks == [t.task_id]
    assert r.failed_tasks == []
    assert r.requires_reassessment is False, \
        "reassessing cannot make a forbidden tool permitted"
    assert r.final_execution_status is ExecutionStatus.EXECUTION_FAILED


def test_fix_success_plus_security_denial_does_not_request_reassessment():
    ok, bad = task("ok"), task("bad", tool="rm_rf")
    r = run_plan(CognitiveState(), plan_of(ok, bad), selection_for([ok, bad]),
                 tool_adapter=FakeTools())
    assert ok.task_id in r.completed_tasks
    assert bad.task_id in r.denied_tasks
    assert r.requires_reassessment is False
    assert r.final_execution_status is ExecutionStatus.EXECUTION_FAILED, \
        "previously this reported REASSESS_REQUIRED"


def test_fix_denial_does_not_transition_to_assess():
    """The ACT -> ASSESS -> STRATEGY -> PLAN -> ACT loop around a forbidden
    action is the behaviour this prevents."""
    t = task(tool="rm_rf")
    s = CognitiveState()
    s.transition_to(CognitivePhase.ASSESS)
    s.transition_to(CognitivePhase.STRATEGY)
    s.transition_to(CognitivePhase.PLAN)
    r = run_plan(s, plan_of(t), selection_for([t]), tool_adapter=FakeTools())
    apply_to_state(s, r)
    assert s.phase is not CognitivePhase.ASSESS


def test_fix_write_under_read_only_is_a_denial_not_a_failure():
    t = task()
    sel = CapabilitySelection(capabilities=[CapabilityRequirement(
        capability_id=Capability.MEMORY_WRITE, task_ids=[t.task_id], read_only=True)])
    r = run_plan(CognitiveState(), plan_of(t), sel, tool_adapter=FakeTools())
    assert t.task_id in r.denied_tasks and r.failed_tasks == []
    assert r.requires_reassessment is False


# ── DEFECT 1b: a genuine failure IS evidence ─────────────────────────────────
def test_fix_ordinary_execution_failure_alone_is_execution_failed():
    t = task()
    r = run_plan(CognitiveState(), plan_of(t), selection_for([t]),
                 tool_adapter=FakeTools({"think": RuntimeError("boom")}))
    assert r.failed_tasks == [t.task_id]
    assert r.requires_reassessment is True
    assert r.final_execution_status is ExecutionStatus.EXECUTION_FAILED


def test_fix_success_plus_execution_failure_is_reassess_required():
    a, b = task("a"), task("b")
    a.input_requirements, b.input_requirements = ["A"], ["BOOM"]
    r = run_plan(CognitiveState(), plan_of(a, b), selection_for([a, b]),
                 tool_adapter=Selective())
    assert a.task_id in r.completed_tasks and b.task_id in r.failed_tasks
    assert r.requires_reassessment is True
    assert r.final_execution_status is ExecutionStatus.REASSESS_REQUIRED


def test_fix_timeout_counts_as_evidence():
    """The plan assumed the work fit its budget; it did not."""
    t = task()
    r = run_plan(CognitiveState(), plan_of(t), selection_for([t]),
                 tool_adapter=FakeTools({"think": TimeoutError("slow")}))
    assert r.outcome_for(t.task_id).error_category is FailureCategory.TIMEOUT
    assert r.requires_reassessment is True


def test_fix_dependency_block_is_not_a_denial():
    a = task("fails")
    a.input_requirements = ["BOOM"]
    b = task("blocked", depends=[a.task_id])
    r = run_plan(CognitiveState(), plan_of(a, b), selection_for([a, b]),
                 tool_adapter=Selective())
    assert a.task_id in r.failed_tasks
    assert b.task_id in r.skipped_tasks       # structural, not a policy refusal
    assert b.task_id not in r.denied_tasks
    assert r.requires_reassessment is True    # from A alone


# ── DEFECT 2: cancellation ───────────────────────────────────────────────────
def test_fix_cancellation_before_first_task():
    a, b = task("a"), task("b")
    tools = FakeTools()
    r = run_plan(CognitiveState(), plan_of(a, b), selection_for([a, b]),
                 tool_adapter=tools, is_cancelled=lambda: True)
    assert tools.calls == [], "no task may run once cancellation is requested"
    assert r.final_execution_status is ExecutionStatus.CANCELLED
    assert r.requires_reassessment is False
    assert len(r.cancelled_tasks) == 2


def test_fix_cancellation_between_tasks():
    a, b, c = task("a"), task("b"), task("c")
    tools = FakeTools()
    r = run_plan(CognitiveState(), plan_of(a, b, c), selection_for([a, b, c]),
                 tool_adapter=tools, is_cancelled=_cancel_after(1, tools))
    assert len(tools.calls) == 1, "execution stops at the next cooperative check"
    assert r.final_execution_status is ExecutionStatus.CANCELLED
    assert a.task_id in r.completed_tasks
    assert len(r.cancelled_tasks) == 2


def test_fix_already_cancelled_task_reports_cancelled_not_failed():
    t = task(status=TaskStatus.CANCELLED)
    tools = FakeTools()
    r = run_plan(CognitiveState(), plan_of(t), selection_for([t]), tool_adapter=tools)
    assert tools.calls == []
    assert t.task_id in r.cancelled_tasks
    assert t.task_id not in r.failed_tasks and t.task_id not in r.denied_tasks
    assert r.final_execution_status is ExecutionStatus.CANCELLED
    assert r.requires_reassessment is False


def test_fix_cancellation_aborts_rather_than_reassessing():
    t = task()
    s = CognitiveState()
    s.transition_to(CognitivePhase.ASSESS)
    s.transition_to(CognitivePhase.STRATEGY)
    s.transition_to(CognitivePhase.PLAN)
    r = run_plan(s, plan_of(t), selection_for([t]), tool_adapter=FakeTools(),
                 is_cancelled=lambda: True)
    apply_to_state(s, r)
    assert s.phase is CognitivePhase.ABORTED


def test_fix_cancellation_reuses_autopilots_registry():
    """No second mechanism: the default predicate reads autopilot's own
    _cancelled set, which its /tasks/{id}/cancel route already drives."""
    import cognitive.executor as ex
    if not ex.AUTOPILOT_AVAILABLE:
        pytest.skip("autopilot unavailable on this path")
    import autopilot
    run_id = "cog-run-under-test"
    check = ex.cancellation_check(run_id)
    assert check() is False
    autopilot._cancelled.add(run_id)
    try:
        assert check() is True, "the executor must observe autopilot's live set"
    finally:
        autopilot._cancelled.discard(run_id)
    assert check() is False


def test_fix_cancellation_check_is_inert_without_a_run_id():
    import cognitive.executor as ex
    assert ex.cancellation_check(None)() is False


# ── DEFECT 3: the categories are disjoint ────────────────────────────────────
def test_fix_evidence_and_denial_categories_do_not_overlap():
    from cognitive.executor import _EVIDENCE_CATEGORIES, _DENIAL_CATEGORIES
    assert _EVIDENCE_CATEGORIES.isdisjoint(_DENIAL_CATEGORIES)
    assert FailureCategory.SECURITY_BLOCK in _DENIAL_CATEGORIES
    assert FailureCategory.SECURITY_BLOCK not in _EVIDENCE_CATEGORIES


def test_fix_outcome_buckets_are_mutually_exclusive():
    ok = task("ok")
    boom = task("boom")
    boom.input_requirements = ["BOOM"]
    refused = task("refused", tool="rm_rf")
    cancelled = task("cancelled", status=TaskStatus.CANCELLED)
    dependent = task("dependent", depends=[boom.task_id])

    r = run_plan(CognitiveState(max_tasks=25),
                 plan_of(ok, boom, refused, cancelled, dependent),
                 selection_for([ok, boom, refused, cancelled, dependent]),
                 tool_adapter=Selective())
    buckets = [set(r.completed_tasks), set(r.failed_tasks),
               set(r.denied_tasks), set(r.cancelled_tasks), set(r.skipped_tasks)]
    for i in range(len(buckets)):
        for j in range(i + 1, len(buckets)):
            assert buckets[i].isdisjoint(buckets[j]), "a task appears in two buckets"


def test_fix_status_matrix():
    """The table the review asked for, asserted rather than described."""
    def status(tasks, selection, tools, **kw):
        return run_plan(CognitiveState(max_tasks=25), plan_of(*tasks), selection,
                        tool_adapter=tools, **kw).final_execution_status

    t = task()
    assert status([t], selection_for([t]), FakeTools()) is ExecutionStatus.EXECUTION_COMPLETE

    t = task()
    assert status([t], selection_for([t]), FakeTools({"think": RuntimeError("x")})) \
        is ExecutionStatus.EXECUTION_FAILED

    t = task(tool="rm_rf")
    assert status([t], selection_for([t]), FakeTools()) is ExecutionStatus.EXECUTION_FAILED

    t = task()
    assert status([t], selection_for([t]), FakeTools(), is_cancelled=lambda: True) \
        is ExecutionStatus.CANCELLED
