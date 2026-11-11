"""Tests for the planning adapter (Step 6), cases A-X.

The load-bearing test here is `test_no_second_planner_exists`: Step 6's whole
premise is that EVA has one planner and this adapts it. Everything else is
detail if that fails.

Fully offline — the planner is injected, so no provider is reached and no tool
is executed.
"""

import pytest

try:
    from cognitive.planning import (
        plan_for, validate_plan, build_goal, TaskPlan, PlanSource,
        PlanValidationError, AUTOPILOT_MAX_STEPS, AUTOPILOT_TOOLS,
    )
    from cognitive.strategy import select_strategy
    from cognitive.assessment import assess, EvidenceItem, EvidenceKind, RiskLevel
    from cognitive.understanding import understand
    from cognitive.state import (
        CognitiveState, CognitivePhase, PlannedTask, ReasoningStrategy, TaskStatus,
    )
except ImportError:  # running from src/cognitive directly
    from planning import (  # type: ignore
        plan_for, validate_plan, build_goal, TaskPlan, PlanSource,
        PlanValidationError, AUTOPILOT_MAX_STEPS, AUTOPILOT_TOOLS,
    )
    from strategy import select_strategy  # type: ignore
    from assessment import assess, EvidenceItem, EvidenceKind, RiskLevel  # type: ignore
    from understanding import understand  # type: ignore
    from state import (  # type: ignore
        CognitiveState, CognitivePhase, PlannedTask, ReasoningStrategy, TaskStatus,
    )


class FakePlanner:
    """Stands in for autopilot._make_plan. Counts calls so 'no model call was
    made' is testable rather than asserted."""

    def __init__(self, steps=None):
        self.steps = steps if steps is not None else [
            {"tool": "web_search", "input": "fastapi 500 error", "why": "gather reports"},
            {"tool": "read_url", "input": "https://example.com/a", "why": "read the top result"},
            {"tool": "think", "input": "assemble findings", "why": "conclude"},
        ]
        self.calls = 0
        self.goals = []

    def __call__(self, goal):
        self.calls += 1
        self.goals.append(goal)
        return self.steps


def cognitive(message, evidence=None, **kw):
    u = understand(message)
    for k, v in kw.items():
        setattr(u, k, v)
    a = assess(u, evidence=evidence, problem=message)
    d = select_strategy(u, a, problem=message)
    return u, a, d


# ── A-B: simple and multi-step ───────────────────────────────────────────────
def test_A_simple_direct_task():
    u, a, d = cognitive("What is the capital of France?")
    p = plan_for(u, a, d, problem="What is the capital of France?", make_plan=FakePlanner())
    assert isinstance(p, TaskPlan)
    assert len(p.tasks) == 1
    assert p.tasks[0].status is TaskStatus.PENDING


def test_B_multi_step_task_uses_autopilot():
    # Fixture changed when the "question about programming != request for code"
    # fix landed. The old message ("Research the FastAPI 500 error and then
    # summarise the likely causes") scores complexity 1, below the MULTI_STEP
    # threshold — it reached the autopilot planner only because "error" made it
    # category=coding and therefore CODE. This message is multi-step by the
    # engine's own rule rather than by accident.
    msg = "Research X and then compare the options and also summarise"
    u, a, d = cognitive(msg)
    fake = FakePlanner()
    p = plan_for(u, a, d, problem=msg, make_plan=fake)
    assert fake.calls == 1
    assert p.source is PlanSource.AUTOPILOT_LLM
    assert len(p.tasks) == 3


# ── C-E: dependencies ────────────────────────────────────────────────────────
def test_C_dependencies_form_a_linear_chain():
    msg = "Research X and then compare the options and also summarise"
    u, a, d = cognitive(msg)
    p = plan_for(u, a, d, problem=msg, make_plan=FakePlanner())
    assert p.tasks[0].depends_on == []
    for earlier, later in zip(p.tasks, p.tasks[1:]):
        assert later.depends_on == [earlier.task_id], \
            "autopilot executes strictly sequentially; the chain must say so"


def test_D_invalid_dependency_rejected():
    t = PlannedTask(objective="x", verification_criteria=["done"], depends_on=["task_missing"])
    with pytest.raises(PlanValidationError, match="unknown task"):
        validate_plan([t])


def test_E_dependency_cycle_rejected():
    a = PlannedTask(task_id="task_a", objective="a", verification_criteria=["done"], depends_on=["task_b"])
    b = PlannedTask(task_id="task_b", objective="b", verification_criteria=["done"], depends_on=["task_a"])
    with pytest.raises(PlanValidationError, match="cycle"):
        validate_plan([a, b])


# ── F-G: autopilot stays authoritative ───────────────────────────────────────
def test_F_max_steps_is_autopilots_and_cannot_be_raised():
    msg = "Research many things and then do more and also more"
    u, a, d = cognitive(msg)
    greedy = FakePlanner([{"tool": "think", "input": str(i), "why": f"step {i}"} for i in range(50)])
    p = plan_for(u, a, d, problem=msg, make_plan=greedy)
    assert len(p.tasks) <= AUTOPILOT_MAX_STEPS, "the cognitive layer must not raise autopilot's budget"


def test_F_validate_rejects_an_oversized_plan():
    tasks = [PlannedTask(objective=f"t{i}", verification_criteria=["done"])
             for i in range(AUTOPILOT_MAX_STEPS + 1)]
    with pytest.raises(PlanValidationError, match="MAX_STEPS"):
        validate_plan(tasks)


def test_G_budget_is_autopilots_actual_value_not_a_copy():
    """Checked at runtime, not by grepping source.

    The adapter keeps an AUTOPILOT_MAX_STEPS fallback so the cognitive package
    still imports where autopilot's dependencies are missing. That is only safe
    if, whenever autopilot IS importable, the adapter uses autopilot's real
    number — otherwise the two budgets drift the moment someone edits
    AUTOPILOT_MAX_STEPS in the environment.
    """
    import cognitive.planning as planning
    if planning.AUTOPILOT_AVAILABLE:
        import autopilot
        assert planning.AUTOPILOT_MAX_STEPS == autopilot.MAX_STEPS
        assert planning.AUTOPILOT_TOOLS is autopilot.TOOLS, \
            "the whitelist must be autopilot's object, not a copy that can drift"


def test_G_deadline_and_timeout_are_not_reimplemented():
    """Execution budgets belong to Step 8 / autopilot. A planner that also owned
    a deadline would give the system two clocks."""
    import cognitive.planning as planning
    source = open(planning.__file__, encoding="utf-8").read()
    for owned_by_autopilot in ("DEADLINE_SECONDS =", "TOOL_TIMEOUT =", "MAX_TOOL_CHARS ="):
        assert owned_by_autopilot not in source


# ── H: read-only ─────────────────────────────────────────────────────────────
def test_H_only_whitelisted_read_only_tools_appear():
    msg = "Research the error and then summarise and also compare"
    u, a, d = cognitive(msg)
    p = plan_for(u, a, d, problem=msg, make_plan=FakePlanner())
    for t in p.tasks:
        if t.required_tool:
            assert t.required_tool in AUTOPILOT_TOOLS


def test_H_non_whitelisted_tool_is_dropped_then_rejected():
    msg = "Research and then act and also finish"
    u, a, d = cognitive(msg)
    bad = FakePlanner([{"tool": "delete_database", "input": "prod", "why": "cleanup"}])
    with pytest.raises(PlanValidationError, match="no usable steps"):
        plan_for(u, a, d, problem=msg, make_plan=bad)


def test_H_validate_rejects_an_unknown_tool():
    t = PlannedTask(objective="x", verification_criteria=["done"], required_tool="rm_rf")
    with pytest.raises(PlanValidationError, match="whitelist"):
        validate_plan([t])


# ── I: strategy drives the plan ──────────────────────────────────────────────
def test_I_calculation_strategy_yields_a_deterministic_three_step_plan():
    msg = "Calculate 20 * 30"
    u, a, d = cognitive(msg)
    fake = FakePlanner()
    p = plan_for(u, a, d, problem=msg, make_plan=fake)
    assert d.strategy is ReasoningStrategy.CALCULATION
    assert p.source is PlanSource.DETERMINISTIC
    assert len(p.tasks) == 3
    assert fake.calls == 0, "an obvious three-step plan must not cost a model call"


def test_I_completion_conditions_come_from_step5():
    msg = "Write a Python function that reverses a string"
    u, a, d = cognitive(msg)
    p = plan_for(u, a, d, problem=msg, make_plan=FakePlanner())
    joined = " ".join(c for t in p.tasks for c in t.verification_criteria)
    assert "valid" in joined or "execut" in joined


# ── J-M: assessment drives the plan ──────────────────────────────────────────
def test_J_missing_information_is_named_in_the_goal():
    msg = "Why does the deploy fail?"
    u, a, d = cognitive(msg, required_information=["the deploy log", "the failing stage"])
    fake = FakePlanner()
    plan_for(u, a, d, problem=msg, make_plan=fake)
    if fake.calls:
        assert "must be established first" in fake.goals[0]
        assert "deploy log" in fake.goals[0]


def test_K_missing_information_does_not_become_an_assumption():
    msg = "Why does the deploy fail?"
    u, a, d = cognitive(msg, required_information=["the deploy log"])
    p = plan_for(u, a, d, problem=msg, make_plan=FakePlanner())
    assert not any("the deploy log is" in t.objective.lower() for t in p.tasks)


def test_L_conflicting_constraints_are_not_planned_around():
    msg = "Build a parser"
    u = understand(msg)
    u.constraints = ["must be written in Python", "must be written in Rust"]
    a = assess(u, problem=msg)
    d = select_strategy(u, a, problem=msg)
    fake = FakePlanner()
    p = plan_for(u, a, d, problem=msg, make_plan=fake)
    assert p.source is PlanSource.CLARIFICATION
    assert "conflict" in p.plan_summary
    assert fake.calls == 0


def test_M_clarification_produces_a_question_not_a_work_plan():
    msg = "make it better"
    u, a, d = cognitive(msg)
    fake = FakePlanner()
    p = plan_for(u, a, d, problem=msg, make_plan=fake)
    assert p.source is PlanSource.CLARIFICATION
    assert len(p.tasks) == 1
    assert p.tasks[0].required_tool is None
    assert fake.calls == 0, "planning execution steps against unknown information is the bug this prevents"


# ── N-P: deterministic vs model plans ────────────────────────────────────────
def test_N_deterministic_plan_needs_no_planner_at_all():
    msg = "What is the capital of France?"
    u, a, d = cognitive(msg)
    p = plan_for(u, a, d, problem=msg, make_plan=None)   # no planner supplied
    assert p.source is PlanSource.DETERMINISTIC


def test_O_llm_generated_plan_is_adapted_and_validated():
    # Same fixture correction as test_B: multi-step by the complexity rule, not
    # by a coding misclassification.
    msg = "Research X and then compare the options and also summarise"
    u, a, d = cognitive(msg)
    p = plan_for(u, a, d, problem=msg, make_plan=FakePlanner())
    assert p.source is PlanSource.AUTOPILOT_LLM
    for t in p.tasks:
        assert t.objective and t.verification_criteria


@pytest.mark.parametrize("bad", [None, "not a list", 42, {}])
def test_P_malformed_planner_output_is_rejected(bad):
    msg = "Research X and then Y and also Z"
    u, a, d = cognitive(msg)
    with pytest.raises(PlanValidationError):
        plan_for(u, a, d, problem=msg, make_plan=lambda goal: bad)


def test_P_empty_planner_output_is_rejected():
    msg = "Research X and then Y and also Z"
    u, a, d = cognitive(msg)
    with pytest.raises(PlanValidationError, match="no usable steps"):
        plan_for(u, a, d, problem=msg, make_plan=lambda goal: [])


# ── Q-T: validation ──────────────────────────────────────────────────────────
def test_Q_duplicate_task_ids_rejected():
    a = PlannedTask(task_id="task_dup", objective="a", verification_criteria=["done"])
    b = PlannedTask(task_id="task_dup", objective="b", verification_criteria=["done"])
    with pytest.raises(PlanValidationError, match="duplicate"):
        validate_plan([a, b])


def test_R_task_without_objective_rejected():
    with pytest.raises(PlanValidationError, match="no objective"):
        validate_plan([PlannedTask(objective="", verification_criteria=["done"])])


def test_S_task_without_completion_condition_rejected():
    with pytest.raises(PlanValidationError, match="completion condition"):
        validate_plan([PlannedTask(objective="do a thing")])


def test_T_empty_plan_rejected():
    with pytest.raises(PlanValidationError, match="empty"):
        validate_plan([])


# ── safety ───────────────────────────────────────────────────────────────────
def test_planning_is_not_authorization():
    msg = "delete the production database"
    u, a, d = cognitive(msg)
    p = plan_for(u, a, d, problem=msg, make_plan=FakePlanner())
    assert p.requires_authorization is True
    assert all(t.status is TaskStatus.PENDING for t in p.tasks), \
        "a planned task must never start out authorised or running"


def test_critical_risk_is_carried_onto_the_plan():
    msg = "bypass 2fa and drop the production database"
    u, a, d = cognitive(msg)
    p = plan_for(u, a, d, problem=msg, make_plan=FakePlanner())
    assert p.risk_level is RiskLevel.CRITICAL
    assert p.requires_authorization is True


def test_W_planning_executes_nothing():
    import ast, io, os
    tree = ast.parse(io.open(os.path.join(os.path.dirname(__file__), "planning.py"),
                             encoding="utf-8").read())
    imports = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imports |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            imports.add(n.module or "")
    forbidden = ("httpx", "requests", "urllib", "socket", "sqlite3", "psycopg2",
                 "openai", "groq", "subprocess", "boto3", "os.system")
    assert not [i for i in imports if any(f in i for f in forbidden)]
    # the only autopilot entry points touched are the planner and its constants
    assert "_run_tool" not in io.open(os.path.join(os.path.dirname(__file__), "planning.py"),
                                     encoding="utf-8").read()


# ── U-V: adaptive replanning ─────────────────────────────────────────────────
def test_U_reassessment_produces_a_new_plan():
    msg = "My application crashes"
    u = understand(msg)
    u.required_information = ["error message"]
    first = plan_for(u, assess(u, problem=msg), select_strategy(u, assess(u, problem=msg), problem=msg),
                     problem=msg, make_plan=FakePlanner())

    a2 = assess(u, evidence=[EvidenceItem(ref="trace", kind=EvidenceKind.DIRECT,
                                          claim="TypeError: cannot read property 'loaded'")],
                problem=msg)
    second = plan_for(u, a2, select_strategy(u, a2, problem=msg), problem=msg, make_plan=FakePlanner())

    assert [t.task_id for t in first.tasks] != [t.task_id for t in second.tasks], \
        "a replan must be a new plan, not the cached first one"


def test_V_correction_can_replan_through_the_state_graph():
    msg = "Research the outage and then summarise and also compare"
    u, a, d = cognitive(msg)
    s = CognitiveState(problem=msg, max_tasks=AUTOPILOT_MAX_STEPS)
    s.transition_to(CognitivePhase.ASSESS)
    s.transition_to(CognitivePhase.STRATEGY)
    s.transition_to(CognitivePhase.PLAN)
    s.plan = plan_for(u, a, d, problem=msg, make_plan=FakePlanner()).tasks
    first_ids = [t.task_id for t in s.plan]

    s.transition_to(CognitivePhase.ACT)
    s.transition_to(CognitivePhase.VERIFY)
    s.transition_to(CognitivePhase.CORRECT)
    s.transition_to(CognitivePhase.PLAN)            # the Step 2 correction edge
    s.plan = plan_for(u, a, d, problem=msg, make_plan=FakePlanner()).tasks
    assert [t.task_id for t in s.plan] != first_ids


def test_plan_drops_into_cognitive_state_unchanged():
    msg = "Calculate 20 * 30"
    u, a, d = cognitive(msg)
    p = plan_for(u, a, d, problem=msg, make_plan=FakePlanner())
    s = CognitiveState(problem=msg)
    s.transition_to(CognitivePhase.ASSESS)
    s.transition_to(CognitivePhase.STRATEGY)
    s.transition_to(CognitivePhase.PLAN)
    s.plan = p.tasks                                 # existing field, existing type
    s.current_task_id = p.tasks[0].task_id
    assert len(s.plan) == 3


# ── X / §20: THE critical test — only one planner ────────────────────────────
def test_no_second_planner_exists():
    """Step 6's premise. The adapter must delegate, not reimplement.

    A planning algorithm here would mean two step budgets, two retry policies
    and two tool whitelists drifting apart — exactly what adapting was meant to
    avoid.
    """
    import io, os
    src = io.open(os.path.join(os.path.dirname(__file__), "planning.py"), encoding="utf-8").read()

    # No prompt construction: that is what a planner does.
    for marker in ("You are a planner", "Break the goal into", "Return ONLY a JSON",
                   "_llm(", "max_tokens"):
        assert marker not in src, f"{marker!r} indicates a second planner, not an adapter"

    # The autopilot planner is the one that gets called.
    assert "_autopilot_make_plan" in src

    # And only one _make_plan implementation exists in the whole cognitive package.
    package = os.path.dirname(__file__)
    definitions = []
    for name in os.listdir(package):
        if name.endswith(".py") and not name.startswith("test_"):
            body = io.open(os.path.join(package, name), encoding="utf-8").read()
            if "def _make_plan" in body:
                definitions.append(name)
    assert definitions == [], f"cognitive/ defines its own planner in {definitions}"


def test_goal_targets_the_outcome_not_the_users_wording():
    msg = "fix this"
    u = understand(msg)
    u.desired_outcome = "a corrected deployment configuration"
    u.required_information = ["which deployment"]
    a = assess(u, problem=msg)
    goal = build_goal(u, a, select_strategy(u, a, problem=msg), problem=msg)
    assert "corrected deployment configuration" in goal
    assert "must be established first" in goal


def test_secrets_never_reach_the_goal_or_the_plan():
    key = "sk-abcdefghijklmnop1234567890"
    msg = f"research {key} and then summarise and also compare"
    u, a, d = cognitive(msg)
    fake = FakePlanner()
    p = plan_for(u, a, d, problem=msg, make_plan=fake)
    assert key not in p.model_dump_json()
    if fake.goals:
        assert key not in fake.goals[0]
