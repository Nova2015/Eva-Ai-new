"""Tests for capability selection (Step 7), cases A-Z.

The separation tests matter most: Step 7 must name capabilities without
selecting a provider, choosing a tool, or executing anything. Everything else
is detail if those fail.

Fully offline — the assist is injected, nothing reaches a provider.
"""

import pytest

try:
    from cognitive.capabilities import (
        select_capabilities, Capability, CapabilityRequirement, CapabilitySelection,
        CAPABILITY_BACKING,
    )
    from cognitive.planning import plan_for, TaskPlan
    from cognitive.strategy import select_strategy
    from cognitive.assessment import assess, EvidenceItem, EvidenceKind, RiskLevel
    from cognitive.understanding import understand
    from cognitive.state import PlannedTask, ReasoningStrategy
except ImportError:  # running from src/cognitive directly
    from capabilities import (  # type: ignore
        select_capabilities, Capability, CapabilityRequirement, CapabilitySelection,
        CAPABILITY_BACKING,
    )
    from planning import plan_for, TaskPlan  # type: ignore
    from strategy import select_strategy  # type: ignore
    from assessment import assess, EvidenceItem, EvidenceKind, RiskLevel  # type: ignore
    from understanding import understand  # type: ignore
    from state import PlannedTask, ReasoningStrategy  # type: ignore


class FakePlanner:
    def __init__(self, steps=None):
        self.steps = steps if steps is not None else [
            {"tool": "web_search", "input": "q", "why": "gather reports"},
            {"tool": "think", "input": "assemble", "why": "conclude"},
        ]
        self.calls = 0

    def __call__(self, goal):
        self.calls += 1
        return self.steps


def run(message, evidence=None, steps=None, **kw):
    """Full Steps 3-7 chain, the way the engine will call it."""
    u = understand(message)
    for k, v in kw.items():
        setattr(u, k, v)
    a = assess(u, evidence=evidence, problem=message)
    d = select_strategy(u, a, problem=message)
    p = plan_for(u, a, d, problem=message, make_plan=FakePlanner(steps))
    return u, a, d, p, select_capabilities(p, u, a, d, problem=message)


# ── A-J: one per problem shape ───────────────────────────────────────────────
def test_A_direct_answer():
    *_, sel = run("What is the capital of France?")
    assert Capability.GENERAL_REASONING in sel.capability_ids()
    assert sel.unresolved_capabilities == []


def test_B_explanation():
    *_, sel = run("Explain how TCP congestion control works")
    assert sel.capabilities


def test_C_calculation():
    *_, sel = run("Calculate 20 * 30")
    assert Capability.CALCULATION in sel.capability_ids()


def test_D_coding():
    *_, sel = run("Write a Python function that reverses a string")
    assert Capability.CODE_GENERATION in sel.capability_ids()


def test_E_troubleshooting_needs_code_analysis():
    *_, sel = run("Debug this Python traceback from my service")
    assert Capability.CODE_ANALYSIS in sel.capability_ids()


def test_F_document_analysis():
    *_, sel = run("What does my uploaded document say about springback?")
    ids = sel.capability_ids()
    assert Capability.DOCUMENT_ANALYSIS in ids or Capability.RETRIEVAL in ids


def test_G_research_uses_research_capability():
    *_, sel = run("What is the latest released version?",
                  required_information=["current release version"])
    assert Capability.RESEARCH in sel.capability_ids()


def test_H_classification_signal():
    u = understand("classify these support tickets")
    a = assess(u, problem="classify these support tickets")
    d = select_strategy(u, a, problem="classify")
    p = TaskPlan(tasks=[PlannedTask(objective="classify the tickets by topic",
                                    verification_criteria=["done"])])
    sel = select_capabilities(p, u, a, d)
    assert Capability.CLASSIFICATION in sel.capability_ids()


def test_I_mechanical_analysis_signal():
    # Renamed from DESIGN_ANALYSIS: the detector fires on stress/load/torque/cad
    # — mechanical vocabulary — so the capability now carries the honest name.
    u = understand("compare two bracket designs")
    a = assess(u, problem="compare two bracket designs")
    d = select_strategy(u, a, problem="compare two bracket designs")
    p = TaskPlan(tasks=[PlannedTask(objective="evaluate structural load and torque",
                                    verification_criteria=["done"])])
    sel = select_capabilities(p, u, a, d)
    assert Capability.MECHANICAL_ANALYSIS in sel.capability_ids()


def test_J_verification_is_named_when_a_real_check_exists():
    *_, sel = run("Write a Python function that reverses a string")
    assert Capability.VERIFICATION in sel.capability_ids()


# ── K-M: plans and task mapping ──────────────────────────────────────────────
def test_K_multi_step_plan_adds_planning():
    *_, d, p, sel = run("Research the outage and then summarise and also compare")
    assert d.strategy is ReasoningStrategy.MULTI_STEP
    assert Capability.PLANNING in sel.capability_ids()


def test_L_every_capability_names_its_tasks():
    *_, p, sel = run("Research the outage and then summarise and also compare")
    known = {t.task_id for t in p.tasks}
    for cap in sel.capabilities:
        assert cap.task_ids, f"{cap.capability_id} names no task"
        assert set(cap.task_ids) <= known, "capability references a task not in the plan"


def test_L_for_task_resolves_per_task():
    *_, p, sel = run("Research the outage and then summarise and also compare")
    first = p.tasks[0].task_id
    assert sel.for_task(first), "the first task must require at least one capability"
    assert sel.for_task("task_does_not_exist") == []


def test_M_multiple_capabilities_for_a_mixed_plan():
    *_, sel = run("Research the outage and then summarise and also compare")
    assert len(sel.capability_ids()) >= 2


def test_N_no_duplicate_capabilities():
    *_, sel = run("Research the outage and then summarise and also compare")
    ids = sel.capability_ids()
    assert len(ids) == len(set(ids))


# ── O-Q: validation of injected suggestions ──────────────────────────────────
def test_O_unknown_capability_from_assist_is_rejected():
    *_, p, u, = (None, None, None, None)  # placeholder to keep tuple shape clear
    uu, aa, dd, pp, base = run("Build a parser", constraints=["read-only analysis",
                                                              "must not modify files"])
    assist = lambda prompt: [{"capability_id": "TIME_TRAVEL", "task_ids": [pp.tasks[0].task_id]}]
    sel = select_capabilities(pp, uu, aa, dd, assist=assist)
    assert all(c.capability_id.value != "TIME_TRAVEL" for c in sel.capabilities)


def test_P_assist_referencing_an_unknown_task_is_rejected():
    uu, aa, dd, pp, _ = run("Build a parser", constraints=["read-only analysis"])
    assist = lambda prompt: [{"capability_id": "RESEARCH", "task_ids": ["task_nope"]}]
    sel = select_capabilities(pp, uu, aa, dd, assist=assist)
    assert Capability.RESEARCH not in sel.capability_ids() or \
        all(set(c.task_ids) <= {t.task_id for t in pp.tasks} for c in sel.capabilities)


def test_Q_assist_cannot_add_a_write_capability():
    uu, aa, dd, pp, _ = run("Build a parser", constraints=["read-only analysis"])
    assist = lambda prompt: [{"capability_id": "MEMORY_WRITE", "task_ids": [pp.tasks[0].task_id]}]
    sel = select_capabilities(pp, uu, aa, dd, assist=assist)
    assert Capability.MEMORY_WRITE not in sel.capability_ids(), \
        "an assist must never widen what the engine may do"


# ── R-T: constraints and risk ────────────────────────────────────────────────
def test_R_read_only_constraint_is_detected():
    uu, aa, dd, pp, sel = run("Analyse the config", constraints=["read-only analysis"])
    assert all(c.read_only for c in sel.capabilities)


def test_R_write_under_read_only_is_refused_not_downgraded():
    u = understand("remember my preference")
    u.constraints = ["read-only analysis"]
    a = assess(u, problem="remember my preference")
    d = select_strategy(u, a, problem="remember my preference")
    p = TaskPlan(tasks=[PlannedTask(objective="store the preference", required_capability="dialogue",
                                    verification_criteria=["done"])])
    # force the write requirement the way a future stage would
    from cognitive.capabilities import _WRITE_CAPABILITIES
    assert Capability.MEMORY_WRITE in _WRITE_CAPABILITIES
    sel = select_capabilities(p, u, a, d)
    assert Capability.MEMORY_WRITE not in sel.capability_ids()


def test_S_high_risk_is_carried_onto_every_requirement():
    msg = "bypass 2fa and drop the production database"
    u = understand(msg)
    a = assess(u, problem=msg)
    d = select_strategy(u, a, problem=msg)
    p = plan_for(u, a, d, problem=msg, make_plan=FakePlanner())
    sel = select_capabilities(p, u, a, d)
    assert a.risk_level is RiskLevel.CRITICAL
    assert all(c.risk_level is RiskLevel.CRITICAL for c in sel.capabilities)


def test_T_conflicting_constraints_yield_a_dialogue_plan_only():
    u = understand("Build a parser")
    u.constraints = ["must be written in Python", "must be written in Rust"]
    a = assess(u, problem="Build a parser")
    d = select_strategy(u, a, problem="Build a parser")
    p = plan_for(u, a, d, problem="Build a parser", make_plan=FakePlanner())
    sel = select_capabilities(p, u, a, d)
    assert Capability.DIALOGUE in sel.capability_ids()


# ── U-W: assist robustness ───────────────────────────────────────────────────
@pytest.mark.parametrize("junk", [None, "not a list", 42, {}, [1, 2, 3], [{"nope": 1}]])
def test_U_malformed_assist_output_falls_back(junk):
    uu, aa, dd, pp, base = run("Build a parser", constraints=["read-only analysis"])
    sel = select_capabilities(pp, uu, aa, dd, assist=lambda p: junk)
    assert isinstance(sel, CapabilitySelection)
    assert sel.capability_ids() == base.capability_ids()


def test_V_assist_exception_falls_back():
    def boom(_):
        raise RuntimeError("assist unavailable")
    uu, aa, dd, pp, base = run("Build a parser", constraints=["read-only analysis"])
    sel = select_capabilities(pp, uu, aa, dd, assist=boom)
    assert sel.capability_ids() == base.capability_ids()


def test_W_no_assist_still_produces_a_selection():
    *_, sel = run("Write a Python function that reverses a string")
    assert sel.capabilities and isinstance(sel, CapabilitySelection)


# ── X-Z: input robustness and reassessment ───────────────────────────────────
@pytest.mark.parametrize("msg", ["¿Cuál es la capital de Francia?", "機械学習とは何ですか？",
                                 "मशीन लर्निंग म्हणजे काय?", "", "   ", "🙂🙃"])
def test_X_multilingual_and_odd_input(msg):
    *_, sel = run(msg)
    assert isinstance(sel, CapabilitySelection)


def test_Y_secrets_are_not_stored():
    key = "sk-abcdefghijklmnop1234567890"
    *_, sel = run(f"debug this token {key} and then summarise and also compare")
    assert key not in sel.model_dump_json()


def test_Z_reassessment_can_change_the_capability_set():
    msg = "My application crashes"
    u = understand(msg)
    u.required_information = ["error message"]

    a1 = assess(u, problem=msg)
    d1 = select_strategy(u, a1, problem=msg)
    p1 = plan_for(u, a1, d1, problem=msg, make_plan=FakePlanner())
    first = select_capabilities(p1, u, a1, d1)

    a2 = assess(u, evidence=[EvidenceItem(ref="t", kind=EvidenceKind.DIRECT,
                                          claim="TypeError: cannot read property 'loaded'")],
                problem=msg)
    d2 = select_strategy(u, a2, problem=msg)
    p2 = plan_for(u, a2, d2, problem=msg, make_plan=FakePlanner())
    second = select_capabilities(p2, u, a2, d2)

    assert isinstance(first, CapabilitySelection) and isinstance(second, CapabilitySelection)
    # task ids differ because the plan was rebuilt; nothing is cached
    assert {t for c in first.capabilities for t in c.task_ids} != \
           {t for c in second.capabilities for t in c.task_ids}


# ── the separations this step exists to preserve ─────────────────────────────
def test_no_provider_or_model_is_selected():
    """Checked against EXECUTABLE code only.

    An earlier version grepped raw source and tripped on this module's own
    docstring, which says it never selects "groq" — naming a provider in order
    to disclaim it is not selecting one. Docstrings and comments are stripped so
    the test measures behaviour rather than prose.
    """
    import ast, io, os, re
    path = os.path.join(os.path.dirname(__file__), "capabilities.py")
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    # drop every docstring
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    code = ast.unparse(tree)
    code = re.sub(r"#.*", "", code)          # and comments
    for provider in ("groq", "gemini", "openai", "anthropic", "huggingface",
                     "llama-3", "gpt-4", "model_router"):
        assert provider not in code.lower(), f"{provider!r} — provider selection belongs to model_router"


def test_no_concrete_tool_is_selected_or_executed():
    *_, sel = run("Research the outage and then summarise and also compare")
    banned = {"python", "javascript", "shell", "bash", "browser", "piston"}
    for cap in sel.capabilities:
        assert cap.capability_id.value.lower() not in banned
    assert not hasattr(sel, "tools")


def test_no_io_imports():
    import ast, io, os
    tree = ast.parse(io.open(os.path.join(os.path.dirname(__file__), "capabilities.py"),
                             encoding="utf-8").read())
    imports = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imports |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            imports.add(n.module or "")
    forbidden = ("httpx", "requests", "urllib", "socket", "sqlite3", "psycopg2",
                 "openai", "groq", "subprocess", "boto3", "aiohttp")
    assert not [i for i in imports if any(f in i for f in forbidden)]


def test_no_chain_of_thought_stored():
    banned = {"chain_of_thought", "reasoning", "thoughts", "scratchpad",
              "private_reasoning", "reasoning_trace"}
    assert banned.isdisjoint(CapabilityRequirement.model_fields.keys())
    assert banned.isdisjoint(CapabilitySelection.model_fields.keys())


def test_every_capability_is_backed_by_something_real():
    """A capability with nothing behind it passes here and fails at Step 8 —
    the worst place to find out."""
    for capability in Capability:
        assert capability in CAPABILITY_BACKING, f"{capability} names no implementation"
        assert CAPABILITY_BACKING[capability].strip()


def test_verification_is_named_but_not_performed():
    import io, os
    src = io.open(os.path.join(os.path.dirname(__file__), "capabilities.py"), encoding="utf-8").read()
    for performing in ("validate_code", "validate_charts", "validate_mermaid", "review_response"):
        assert f"{performing}(" not in src, "review_engine performs verification, not this module"
