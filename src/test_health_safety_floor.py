"""Tests for the health safety floor.

The defect this closes: every safeguard EVA had — "not a clinician", emergency
guidance, no invented studies — lived only inside MODE_PROMPTS["medical"].
Nothing selects that persona. There is no classifier, and the mode selector was
removed deliberately, so a health question reached the model with none of it.

The property under test is therefore NOT "medical mode is safe". It is:

    the safeguard holds on every path, without anything having to classify
    the message first

A safety rule that only applies when a regex fires is a safety rule that fails
silently, and it fails on exactly the inputs nobody anticipated. So these tests
assert the floor is unconditional, and that it reaches all three prompts —
including vision, where a photo of a rash or a prescription label carries no
health words in the message text at all.
"""

import ast
import os
import re

import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "app.py")
ML_ROUTER = os.path.join(os.path.dirname(HERE), "eva-ml-service", "model_router.py")


@pytest.fixture(scope="module")
def app_module():
    import sys
    sys.path.insert(0, HERE)
    import app
    return app


@pytest.fixture(scope="module")
def app_tree():
    with open(APP, "r", encoding="utf-8-sig") as fh:
        return ast.parse(fh.read())


def _resolve(node):
    """A string built by adding literals together."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _resolve(node.left) + _resolve(node.right)
    return ""


# ── A: the floor says the things that matter ────────────────────────────────
@pytest.mark.parametrize("promise,pattern", [
    ("not a clinician",        r"not a clinician"),
    ("no diagnosis",           r"do not diagnose"),
    ("no prescribing",         r"prescrib"),
    ("emergency first",        r"emergency.*say that first|say that first.*emergency"),
    ("urgent care",            r"urgent care"),
    ("self-harm routed",       r"harm themselves"),
    ("crisis line",            r"crisis line|emergency services"),
    ("refer to a professional", r"qualified professional"),
    ("no invented evidence",   r"never invent a study"),
    ("no invented dose",       r"drug interaction, or dose"),
])
def test_the_floor_carries_each_safeguard(app_module, promise, pattern):
    assert re.search(pattern, app_module.HEALTH_SAFETY_FLOOR, re.S | re.I), \
        f"the floor lost its {promise} clause"


def test_the_floor_is_scoped_so_other_topics_are_unaffected(app_module):
    """A floor that made every answer defensive would be pulled within a week,
    and then it would protect nobody. The scope line is what keeps it in."""
    assert re.search(r"apply only when the message concerns health",
                     app_module.HEALTH_SAFETY_FLOOR)
    assert re.search(r"any other topic they change\s+nothing",
                     app_module.HEALTH_SAFETY_FLOOR)


def test_the_scope_line_comes_before_the_rules(app_module):
    """Ordering is load-bearing. The model reads the restriction before the
    instructions it restricts; reversed, it starts hedging about databases."""
    floor = app_module.HEALTH_SAFETY_FLOOR
    assert floor.index("apply only when") < floor.index("not a clinician")


# ── B: it is a floor, not a mode ────────────────────────────────────────────
def test_the_floor_is_not_conditional_on_anything(app_tree):
    """The whole point. If the floor were applied under an `if`, it would be a
    mode with extra steps, and it would be absent exactly when the classifier
    was wrong."""
    src = ast.unparse(app_tree)
    for use in re.findall(r".{80}HEALTH_SAFETY_FLOOR.{20}", src):
        assert " if " not in use, f"the floor is applied conditionally: {use}"


def test_the_floor_does_not_depend_on_a_mode_being_chosen(app_tree):
    """It must not be reachable only via _mode_prompt, which is empty for
    automatic — that is the bug being fixed, not the fix."""
    src = ast.unparse(app_tree)
    assert "_mode_prompt" not in src[src.index("HEALTH_SAFETY_FLOOR"):
                                     src.index("HEALTH_SAFETY_FLOOR") + 200]


@pytest.mark.parametrize("prompt_name", ["VISION_SYSTEM_PROMPT"])
def test_the_module_level_prompts_carry_the_floor(app_module, prompt_name):
    assert "HEALTH AND MEDICINE" in getattr(app_module, prompt_name)


def test_the_general_knowledge_identity_carries_the_floor(app_tree):
    """The branch that answers a plain typed question."""
    fn = next(n for n in ast.walk(app_tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "chat")
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "_identity":
            assert "HEALTH_SAFETY_FLOOR" in ast.unparse(node.value)
            return
    pytest.fail("_identity not found")


def test_the_fallback_inherits_the_floor(app_module):
    """_llm_fallback builds its prompt from VISION_SYSTEM_PROMPT, so it is
    covered by that one — but only for as long as that stays true."""
    src = open(APP, encoding="utf-8-sig").read()
    fn = re.search(r"async def _llm_fallback.*?\n(?=async def |def |@app)", src, re.S)
    assert fn, "_llm_fallback not found"
    assert "VISION_SYSTEM_PROMPT" in fn.group(0) or "HEALTH_SAFETY_FLOOR" in fn.group(0), \
        "the fallback no longer inherits the floor from VISION_SYSTEM_PROMPT"


def test_vision_carries_it_because_an_image_may_be_the_whole_question(app_module):
    """A photograph of a rash, a prescription label or a test report is a
    health question whose text contains no health words."""
    assert "HEALTH AND MEDICINE" in app_module.VISION_SYSTEM_PROMPT


# ── C: the two copies do not drift ──────────────────────────────────────────
def _ml_constant(name):
    if not os.path.isfile(ML_ROUTER):
        pytest.skip("eva-ml-service submodule not checked out")
    with open(ML_ROUTER, "r", encoding="utf-8-sig") as fh:
        tree = ast.parse(fh.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == name:
            text = _resolve(node.value)
            if text:
                return text
    pytest.fail(f"eva-ml-service has no {name}")


def test_the_service_defines_the_floor(app_module):
    assert _ml_constant("HEALTH_SAFETY_FLOOR")


def test_the_two_copies_do_not_drift(app_module):
    """The service answers most traffic, the backend answers the rest, and they
    deploy separately. Without this, a clause gets strengthened in whichever
    repo the problem was noticed in and health answers become safe or unsafe
    depending on which path happened to serve them."""
    def norm(t):
        return " ".join(t.split())
    assert norm(_ml_constant("HEALTH_SAFETY_FLOOR")) == \
        norm(app_module.HEALTH_SAFETY_FLOOR)


def test_the_service_actually_applies_it_to_eva_system():
    """Defining it is not applying it — the Update 21 failure, where a field
    was accepted and then ignored."""
    with open(ML_ROUTER, "r", encoding="utf-8-sig") as fh:
        src = fh.read()
    assert re.search(r"EVA_SYSTEM\s*=\s*EVA_SYSTEM\s*\+\s*HEALTH_SAFETY_FLOOR", src), \
        "the service defines the floor but never adds it to EVA_SYSTEM"


def test_the_service_applies_it_unconditionally():
    with open(ML_ROUTER, "r", encoding="utf-8-sig") as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "HEALTH_SAFETY_FLOOR" in ast.unparse(node):
            pytest.fail("the service applies the floor under a condition")


# ── D: what the floor must NOT do ───────────────────────────────────────────
def test_the_floor_does_not_refuse_health_questions(app_module):
    """EVA still answers. The floor adds care, it does not add a refusal —
    a general health question is a legitimate thing to answer."""
    floor = app_module.HEALTH_SAFETY_FLOOR.lower()
    for banned in ("refuse", "decline", "cannot help", "will not answer",
                   "do not answer"):
        assert banned not in floor, f"the floor turned into a refusal: {banned!r}"


def test_the_floor_does_not_touch_formatting(app_module):
    """Formatting belongs to the shape rules and the spoken directive. A floor
    that also had opinions about markdown would collide with them."""
    floor = app_module.HEALTH_SAFETY_FLOOR.lower()
    for word in ("markdown", "bullet", "heading", "latex", "fenced"):
        assert word not in floor


def test_the_medical_persona_still_exists(app_module):
    """The floor replaces nothing. Medical mode still adds clinical depth on
    top of it when Update 37 makes it reachable."""
    from modes.registry import MODES
    assert "medical" in MODES
    assert MODES["medical"]["system_prompt"].strip()
