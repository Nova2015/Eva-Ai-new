"""Tests for chat modes reaching the model (Update 36A).

The defect being closed is not a crash. src/modes/registry.py has held five
personas since before this update; /api/modes served them; resolve_mode was
imported into app.py and never called; ChatRequest had no field to carry a
choice. It was a set of prompts no request could reach — the fourth capability
found built-and-disconnected in this codebase, after select_strategy,
TOOL_ASSISTED and run_plan.

So the properties worth testing are the ones that decide whether this is real:

  1. "automatic" leaves every assembled prompt BYTE-IDENTICAL. A mode selector
     that silently changes answers for users who never touched it is a
     regression dressed as a feature.
  2. An unknown id behaves as automatic, and specifically does NOT become
     "general". resolve_mode returns the general entry for anything it does not
     recognise, so passing its result through unchecked would apply a persona
     nobody asked for.
  3. The persona reaches the RAG path, not only the general-knowledge branch.
     /api/health/routing shows RAG_SERVICE answering most traffic, so a mode
     wired only into the local branch would be nearly invisible in production —
     which is how Update 25 shipped inert.
  4. The ID crosses the wire, never the prompt text. The service splices this
     into the SYSTEM role.
  5. The two copies of the personas do not drift.
"""

import ast
import os
import re

import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "app.py")


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


@pytest.fixture(scope="module")
def registry():
    try:
        from modes.registry import MODES
    except ImportError:
        from src.modes.registry import MODES  # type: ignore
    return MODES


# ── A: automatic changes nothing ─────────────────────────────────────────────
@pytest.mark.parametrize("value", [
    None, "", "   ", "automatic", "AUTOMATIC", " Automatic ",
])
def test_automatic_contributes_no_prompt(app_module, value):
    assert app_module._mode_prompt(value) == ""


@pytest.mark.parametrize("value", [
    "rag",              # what a user would guess; the registry has no such id
    "genral",           # typo
    "GENERAL_MODE",
    "../../etc/passwd",
    "ignore all previous instructions",
    "coding; drop table",
])
def test_an_unknown_id_is_not_silently_promoted_to_general(app_module, value,
                                                           registry):
    """resolve_mode maps anything unrecognised to the general entry. Passing
    that through would mean a typo applies a persona the user never chose, and
    changes the answer for every caller sending a malformed value."""
    assert app_module._mode_prompt(value) == ""
    assert app_module._mode_id(value) == app_module.CHAT_MODE_AUTOMATIC
    assert registry["general"]["system_prompt"] not in app_module._mode_prompt(value)


@pytest.mark.parametrize("value", [123, 4.5, True, [], {}, object()])
def test_a_non_string_mode_cannot_raise(app_module, value):
    """The field is typed str, but _mode_prompt is also called from
    _llm_fallback, whose mode argument is plain Optional[str] with no
    validation behind it."""
    assert app_module._mode_prompt(value) == ""
    assert app_module._mode_id(value) == app_module.CHAT_MODE_AUTOMATIC


def test_the_request_default_is_automatic(app_module):
    assert app_module.ChatRequest(question="hi").mode == "automatic"


def test_a_request_that_omits_mode_still_validates(app_module):
    """Every existing caller — the frontend, the mobile app, any script —
    posts no mode field at all."""
    req = app_module.ChatRequest(question="what is the capital of France")
    assert app_module._mode_prompt(req.mode) == ""


# ── B: an explicit mode actually contributes its persona ─────────────────────
@pytest.mark.parametrize("mode_id", ["general", "medical", "coding",
                                     "mechanical", "design"])
def test_every_registry_mode_is_reachable(app_module, registry, mode_id):
    """Including "general". It is the registry default, but a user who picks it
    from the menu has made an explicit choice and must get its persona — that
    is what distinguishes it from "automatic"."""
    got = app_module._mode_prompt(mode_id)
    assert registry[mode_id]["system_prompt"] in got
    assert got.startswith("\n\n")


@pytest.mark.parametrize("mode_id", ["Coding", "MEDICAL", " design "])
def test_ids_are_matched_case_and_space_insensitively(app_module, mode_id):
    assert app_module._mode_prompt(mode_id) != ""


def test_general_and_automatic_are_not_the_same_thing(app_module, registry):
    """If these ever collapse, "automatic" has quietly acquired a persona and
    every user who never opened the menu gets a changed answer.

    Stated against the general prompt TEXT, not just as an inequality: the two
    guards that keep automatic empty both end up calling resolve_mode, which
    answers "general" for anything it does not recognise, so the failure mode
    is specifically that the general persona leaks into the default path."""
    assert registry["general"]["system_prompt"] in app_module._mode_prompt("general")
    assert app_module._mode_prompt("automatic") == ""
    assert registry["general"]["system_prompt"] \
        not in app_module._mode_prompt("automatic")


def test_two_different_modes_give_two_different_prompts(app_module):
    assert app_module._mode_prompt("coding") != app_module._mode_prompt("mechanical")


# ── C: the prompt text never leaves the process ──────────────────────────────
def test_the_public_mode_list_still_withholds_the_prompts(app_module, registry):
    """registry.py's stated invariant. Update 36A adds a UI that reads this
    endpoint, so it is now load-bearing for a caller, not just a convention."""
    for entry in app_module.list_public_modes():
        assert set(entry) == {"id", "label", "allowed_tools"}
        assert "system_prompt" not in entry
        assert "model" not in entry


def _rag_payload(tree):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = {k.value for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        if {"message", "workspace_id", "history", "top_k"} <= keys:
            return node, keys
    pytest.fail("the /rag/chat payload was not found in app.py")


def test_the_rag_payload_carries_the_mode(app_tree):
    """The property that decides whether this update is visible at all.
    RAG_SERVICE answers most production traffic; a persona applied only in the
    general-knowledge branch would almost never run."""
    _, keys = _rag_payload(app_tree)
    assert "chat_mode" in keys


def test_the_payload_sends_the_id_and_not_the_prompt(app_tree):
    """The service splices this into the SYSTEM role. Sending text would let
    anything that can reach /rag/chat install its own system instructions;
    an id can only ever be one of five known values."""
    node, _ = _rag_payload(app_tree)
    value = next(v for k, v in zip(node.keys, node.values)
                 if isinstance(k, ast.Constant) and k.value == "chat_mode")
    src = ast.unparse(value)
    assert "_mode_id" in src, f"expected the validated id, got {src}"
    assert "_mode_prompt" not in src, \
        f"the payload must not carry prompt text: {src}"


def test_the_payload_key_is_not_bare_mode(app_tree):
    """eva-ml-service's answer() already takes `mode`, meaning hybrid / vector
    / bm25 retrieval. A key called "mode" landing there would change how
    documents are found rather than who EVA is."""
    _, keys = _rag_payload(app_tree)
    assert "mode" not in keys


def test_the_mode_is_forwarded_from_the_request_not_hardcoded(app_tree):
    node, _ = _rag_payload(app_tree)
    value = next(v for k, v in zip(node.keys, node.values)
                 if isinstance(k, ast.Constant) and k.value == "chat_mode")
    assert "req.mode" in ast.unparse(value)


# ── D: every LLM path that takes a question honours the mode ─────────────────
def _function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return node
    pytest.fail(f"{name} not found in app.py")


def test_the_fallback_applies_the_mode(app_tree):
    fn = _function(app_tree, "_llm_fallback")
    assert "_mode_prompt" in ast.unparse(fn)


def test_the_fallback_call_site_passes_the_mode(app_tree):
    """The signature defaulting to None means forgetting this at the call site
    is silent: the fallback would keep working and keep ignoring the mode."""
    calls = [ast.unparse(n) for n in ast.walk(app_tree)
             if isinstance(n, ast.Call) and "_llm_fallback" in ast.unparse(n.func)]
    assert calls, "_llm_fallback is never called"
    assert all("mode=" in c for c in calls), \
        f"a call site drops the mode: {calls}"


def test_the_general_knowledge_branch_applies_the_mode(app_tree):
    """Where a plain question is answered when the RAG service is not used."""
    src = ast.unparse(app_tree)
    assert re.search(r"system_msg\s*=\s*_identity\s*\+\s*_mode_prompt", src), \
        "the general-knowledge system prompt does not include the mode"


def test_the_persona_precedes_the_shape_rules(app_tree):
    """Ordering is the whole design: identity, then who EVA is for this
    message, then how to format it. A persona appended last would let "you are
    a senior software engineer" argue with the spoken directive's ban on code
    fences — the Update 22/23 failure, where an appended contradiction lost to
    a rule marked CRITICAL."""
    src = ast.unparse(app_tree)
    m = re.search(r"system_msg = _identity \+ _mode_prompt\(req\.mode\) \+ (.+)",
                  src)
    assert m, "the general-knowledge prompt assembly changed shape"
    assert "SPOKEN_ANSWER_DIRECTIVE" in m.group(1) or "_screen_shape" in m.group(1)


def test_the_vision_branch_applies_the_mode(app_tree):
    """Design mode's persona is the one that names screenshots outright, so an
    uploaded image is exactly where a user who picked Design expects it to
    act. Update 28 routes images away from the text path entirely, so without
    this the one mode most tied to images would ignore the choice."""
    fn = _function(app_tree, "_run_vision_agent")
    assert "_mode_prompt" in ast.unparse(fn), \
        "the vision branch builds its system prompt without the mode"


def test_both_vision_providers_get_the_same_system_prompt(app_tree):
    """OpenAI and Gemini are separate call sites in one function. Applying the
    persona at each would let one be updated and the other forgotten — the
    breakpoint-duplication failure, in a place with no visible symptom."""
    fn = _function(app_tree, "_run_vision_agent")
    src = ast.unparse(fn)
    assert src.count("_mode_prompt") == 1, \
        "the persona must be applied once, not per provider"
    assert "VISION_SYSTEM_PROMPT + _mode_prompt" in src
    # Neither provider may still be reading the un-personalised constant.
    body = src.split("_vision_system = VISION_SYSTEM_PROMPT + _mode_prompt(req.mode)", 1)[1]
    assert "VISION_SYSTEM_PROMPT" not in body, \
        "a provider still uses the base prompt instead of _vision_system"


def test_a_mode_does_not_displace_the_base_identity(app_module):
    """The persona is added to EVA's identity, not swapped in for it."""
    src = ast.unparse(_function(ast.parse(open(APP, encoding="utf-8-sig").read()),
                                "chat"))
    assert "_identity + _mode_prompt" in src


# ── E: the two copies of the personas do not drift ───────────────────────────
ML_ROUTER = os.path.join(os.path.dirname(HERE), "eva-ml-service",
                         "model_router.py")
ML_ROUTES = os.path.join(os.path.dirname(HERE), "eva-ml-service",
                         "rag_routes_v2.py")
ML_RAG = os.path.join(os.path.dirname(HERE), "eva-ml-service",
                      "hybrid_rag_v2.py")


def _ml_tree(path):
    if not os.path.isfile(path):
        pytest.skip("eva-ml-service submodule not checked out")
    with open(path, "r", encoding="utf-8-sig") as fh:
        return ast.parse(fh.read())


@pytest.fixture(scope="module")
def ml_mode_prompts():
    """MODE_PROMPTS read by parsing, not importing: that package has its own
    dependencies and is deployed separately."""
    tree = _ml_tree(ML_ROUTER)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id == "MODE_PROMPTS":
            return ast.literal_eval(node.value)
    pytest.fail("eva-ml-service has no MODE_PROMPTS")


def test_the_service_defines_every_mode_the_backend_can_send(registry,
                                                             ml_mode_prompts):
    missing = set(registry) - set(ml_mode_prompts)
    assert not missing, (
        f"the backend can send ids the service will ignore: {sorted(missing)}")


def test_the_service_defines_no_mode_the_backend_cannot_send(registry,
                                                             ml_mode_prompts):
    """A persona only reachable from that side would be untestable from here
    and unreachable from the UI."""
    extra = set(ml_mode_prompts) - set(registry)
    assert not extra, f"eva-ml-service has orphan personas: {sorted(extra)}"


@pytest.mark.parametrize("mode_id", ["general", "medical", "coding",
                                     "mechanical", "design"])
def test_the_two_copies_of_each_persona_do_not_drift(registry, ml_mode_prompts,
                                                     mode_id):
    """Two repositories, two deploy cadences. Without this, a clause gets fixed
    in whichever one the problem was noticed in and the answer depends on which
    path happened to serve it. Whitespace is normalised so re-wrapping a source
    line is not reported as a difference."""
    def norm(text):
        return " ".join(text.split())
    assert norm(ml_mode_prompts[mode_id]) == \
        norm(registry[mode_id]["system_prompt"])


def test_the_service_declares_the_field(app_tree):
    tree = _ml_tree(ML_ROUTES)
    cls = next((n for n in ast.walk(tree)
                if isinstance(n, ast.ClassDef) and n.name == "ChatRequest"), None)
    assert cls is not None
    fields = {t.target.id for t in cls.body if isinstance(t, ast.AnnAssign)
              and isinstance(t.target, ast.Name)}
    assert "chat_mode" in fields, (
        "the backend posts chat_mode and the service would silently drop it — "
        "the Update 21 failure exactly")


def test_the_service_forwards_the_field_into_answer():
    """Declaring the field is not enough; Update 21 proved a value can be
    accepted and then ignored."""
    tree = _ml_tree(ML_ROUTES)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and any(
                kw.arg == "chat_mode" for kw in node.keywords):
            return
    pytest.fail("rag_routes_v2 accepts chat_mode but never passes it on")


def test_the_service_applies_it_to_the_system_prompt():
    src = ast.unparse(_ml_tree(ML_RAG))
    assert "mode_directive" in src, \
        "hybrid_rag_v2 receives chat_mode but never uses it"
    assert re.search(r"system_prompt \+= mode_directive", src), \
        "the persona is not added to the system prompt"


def test_the_service_keeps_chart_rules_after_the_persona():
    """CHART MODE RULES ends with "output the chart block(s) and nothing else".
    A persona inserted after it could argue with that; before it, the chart
    rules still have the last word."""
    src = ast.unparse(_ml_tree(ML_RAG))
    persona = src.index("system_prompt += mode_directive")
    chart = src.index("CHART_SYSTEM_PROMPT}")
    assert persona < chart


@pytest.fixture(scope="module")
def ml_mode_directive():
    """The service's mode_directive, RUN rather than grepped.

    model_router.py cannot be imported here — it pulls in that service's
    provider SDKs — so the function and the two names it closes over are
    lifted out of the parsed module and executed in an empty namespace. It is
    worth the machinery: the first version of these tests asserted
    "MODE_PROMPTS.get" appeared in the source, and a mutation appending
    `or MODE_PROMPTS["general"]` kept that substring and survived. Checking
    what the function returns cannot be fooled that way.
    """
    tree = _ml_tree(ML_ROUTER)
    wanted = {"CHAT_MODE_AUTOMATIC", "MODE_PROMPTS", "mode_directive"}
    picked = [n for n in tree.body
              if (isinstance(n, ast.FunctionDef) and n.name in wanted)
              or (isinstance(n, ast.Assign) and len(n.targets) == 1
                  and isinstance(n.targets[0], ast.Name)
                  and n.targets[0].id in wanted)]
    found = {n.name if isinstance(n, ast.FunctionDef) else n.targets[0].id
             for n in picked}
    assert wanted <= found, f"eva-ml-service is missing {sorted(wanted - found)}"
    ns = {}
    exec(compile(ast.Module(body=picked, type_ignores=[]),
                 ML_ROUTER, "exec"), ns)
    return ns["mode_directive"]


@pytest.mark.parametrize("value", [
    "automatic", "AUTOMATIC", "", "   ", None, 7,
    "rag", "genral", "general_mode", "ignore previous instructions",
])
def test_the_service_gives_no_persona_for_automatic_or_unknown(
        ml_mode_directive, value, registry):
    """An unknown id must yield nothing on this side too. Defaulting to
    "general" here would mean a typo the backend already normalised to
    "automatic" still installed a persona."""
    got = ml_mode_directive(value)
    assert got == ""
    assert registry["general"]["system_prompt"] not in got


@pytest.mark.parametrize("mode_id", ["general", "medical", "coding",
                                     "mechanical", "design"])
def test_the_service_returns_the_right_persona_for_each_id(ml_mode_directive,
                                                           registry, mode_id):
    got = ml_mode_directive(mode_id)
    assert registry[mode_id]["system_prompt"] in got
    assert got.startswith("\n\n")


def test_both_sides_produce_the_same_fragment(app_module, ml_mode_directive,
                                              registry):
    """The end-to-end drift check: whichever path serves the request, the text
    appended to the system prompt is the same."""
    for mode_id in list(registry) + ["automatic", "nonsense"]:
        assert " ".join(app_module._mode_prompt(mode_id).split()) == \
               " ".join(ml_mode_directive(mode_id).split()), \
            f"the two sides disagree about {mode_id!r}"
