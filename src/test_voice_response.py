"""Tests for ChatRequest.voice_response — the one thing that makes a spoken
question different from a typed one.

The property under test is narrow and worth stating plainly: **voice_response
shapes an answer, it does not choose a different pipeline to answer it.** The
field existed on the request model for a long time and nothing read it, so a
dictated question came back with fenced code and bullet lists for a speech
engine to read aloud character by character. The fix is a directive appended to
the system prompt, forwarded to the ML service, and nothing else.

The endpoints deleted alongside it — POST /voice and GET /voice/intents — were
the other answer to the same problem: a regex over the transcript that routed
to a second, weaker chat path. There are assertions here that they stay gone,
and assertions that the live ElevenLabs proxy at /api/voice/* was not caught in
the same sweep.

Everything here is offline. The Groq client is a stub, and nothing imports a
provider SDK or opens a socket.
"""

import ast
import asyncio
import inspect
import os
import sys
import types

import pytest

APP_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")


# ── the app module ───────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def app_module():
    """app.py takes ~30s to import. One module-scoped import, skipped on failure."""
    for rel in ("", "runtime_engine", "review_engine"):
        p = os.path.abspath(os.path.join(os.path.dirname(__file__), rel))
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
    try:
        import app
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"app.py not importable here: {type(exc).__name__}: {exc}")
    return app


@pytest.fixture(scope="module")
def app_tree():
    """app.py parsed. Used where behaviour is unreachable without a network.

    utf-8-sig, not utf-8: app.py is written with a BOM and ast.parse rejects a
    leading U+FEFF.
    """
    with open(APP_PY, "r", encoding="utf-8-sig") as fh:
        return ast.parse(fh.read())


# ── a Groq that records instead of calling ───────────────────────────────────
class _Captured:
    def __init__(self):
        self.messages = None

    @property
    def system(self):
        assert self.messages, "the provider was never called"
        return self.messages[0]["content"]


@pytest.fixture
def captured(monkeypatch):
    """Install a stub `groq` module and return what _llm_fallback sent it."""
    box = _Captured()

    class _Completions:
        def create(self, model=None, messages=None, max_tokens=None):
            box.messages = messages
            return types.SimpleNamespace(choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content="stub answer"))])

    class Groq:
        def __init__(self, api_key=None):
            self.chat = types.SimpleNamespace(completions=_Completions())

    mod = types.ModuleType("groq")
    mod.Groq = Groq
    monkeypatch.setitem(sys.modules, "groq", mod)
    monkeypatch.setenv("GROQ_API_KEY", "stub-key-not-a-secret")
    monkeypatch.setenv("EVA_LOCAL_ENABLED", "false")
    return box


PLAIN = "what is the capital of france"


def fallback(app, question=PLAIN, **kw):
    return asyncio.run(app._llm_fallback(question, [], **kw))


# ── A: the directive reaches the model, and only when asked for ──────────────
def test_spoken_appends_the_directive(app_module, captured):
    assert fallback(app_module, spoken=True) == "stub answer"
    assert "SPOKEN ANSWER" in captured.system


def test_typing_does_not_get_the_directive(app_module, captured):
    fallback(app_module, spoken=False)
    assert "SPOKEN ANSWER" not in captured.system


def test_the_default_is_typed(app_module, captured):
    """Every existing caller passes two arguments. None of them meant 'spoken'."""
    fallback(app_module)
    assert "SPOKEN ANSWER" not in captured.system
    assert inspect.signature(app_module._llm_fallback).parameters["spoken"].default is False


def test_the_directive_does_not_replace_the_normal_prompt(app_module, captured):
    """It is appended. Dropping the rest of the system prompt would silently
    strip vision, memory and chart handling from every spoken answer."""
    fallback(app_module, spoken=True)
    spoken = captured.system
    captured.messages = None
    fallback(app_module, spoken=False)
    typed = captured.system
    assert spoken.startswith(typed), "the spoken prompt must extend, not replace"
    assert len(spoken) > len(typed)


def test_the_directive_asks_for_speech_not_silence(app_module):
    """A directive that only said 'be brief' would not fix what was broken:
    markdown and code fences being read aloud."""
    d = app_module.SPOKEN_ANSWER_DIRECTIVE.lower()
    assert "markdown" in d
    assert "fenced code" in d or "no code" in d


def test_the_directive_forbids_latex(app_module):
    """The general-knowledge prompt says 'CRITICAL: for ALL math you MUST use
    LaTeX'. Read aloud, $$x^2$$ is noise, and 'no markdown' does not obviously
    cover it — so the directive has to name it."""
    assert "latex" in app_module.SPOKEN_ANSWER_DIRECTIVE.lower()


def test_the_directive_claims_precedence(app_module):
    """It is appended after instructions marked CRITICAL and MUST. Without an
    explicit precedence clause the stronger earlier wording wins."""
    d = app_module.SPOKEN_ANSWER_DIRECTIVE.lower()
    assert "wins" in d
    assert "critical" in d or "must" in d


# ── B: the ML service is told too ────────────────────────────────────────────
def _rag_payload(tree):
    """The dict literal posted to /rag/chat, found by its own required keys."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = {k.value for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        if {"message", "workspace_id", "history", "top_k"} <= keys:
            return node, keys
    pytest.fail("the /rag/chat payload was not found in app.py")


def test_the_rag_payload_forwards_spoken(app_tree):
    _, keys = _rag_payload(app_tree)
    assert "spoken" in keys


def test_spoken_is_forwarded_from_the_request_not_hardcoded(app_tree):
    node, _ = _rag_payload(app_tree)
    value = next(v for k, v in zip(node.keys, node.values)
                 if isinstance(k, ast.Constant) and k.value == "spoken")
    assert "voice_response" in ast.unparse(value), \
        f"'spoken' must come from the request, got {ast.unparse(value)}"


def _aliases(tree):
    """Simple `name = <expr>` bindings, so a guard spelled as a local variable
    can be read as the condition it stands for."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            out.setdefault(node.targets[0].id, ast.unparse(node.value))
    return out


def _directive_uses(tree):
    """Every use of SPOKEN_ANSWER_DIRECTIVE with the condition governing it.

    Deliberately not matched on one syntax. It is reached by an `if` guard in
    _llm_fallback and by a ternary in the general-knowledge branch, and a test
    that only understood `+=` would have quietly stopped covering the second
    the moment it was rewritten — which is exactly what happened.
    """
    alias = _aliases(tree)

    def condition(test):
        text = ast.unparse(test)
        return alias.get(text, text) if isinstance(test, ast.Name) else text

    uses = []
    for node in ast.walk(tree):
        if isinstance(node, ast.IfExp) and \
                "SPOKEN_ANSWER_DIRECTIVE" in ast.unparse(node.body):
            uses.append((condition(node.test), ast.unparse(node)))
        elif isinstance(node, ast.If):
            for stmt in node.body:
                if "SPOKEN_ANSWER_DIRECTIVE" in ast.unparse(stmt):
                    uses.append((condition(node.test), ast.unparse(stmt)))
    return uses


def test_the_general_knowledge_branch_is_wired(app_tree):
    """This is the branch most spoken questions take. use_rag is true only for
    the RAG agent or one of a few document phrases, so a plain question like
    'what is the capital of France' never reaches the RAG path or the fallback
    — it is answered here, and before this it was answered for a screen."""
    guards = [g for g, _ in _directive_uses(app_tree)]
    assert any("voice_response" in g for g in guards), \
        f"nothing uses the directive under a voice_response guard: {guards}"


def test_every_use_carves_out_chart_mode(app_tree):
    """A ```chart block IS the answer in chart mode. A rule forbidding fences
    would break what the frontend renders."""
    uses = _directive_uses(app_tree)
    assert uses, "the directive is never used anywhere"
    for guard, stmt in uses:
        assert "is_chart_request" in guard, \
            f"use without a chart carve-out: `{stmt}` guarded by `{guard}`"


# ── Update 23: the conflict is removed, not argued with ──────────────────────
# Appending "no LaTeX" after "CRITICAL: you MUST use LaTeX" lost in production:
# the model emitted $...$ exactly as the CRITICAL rule demanded, while obeying
# the same directive's brevity clause. The prompt now CHOOSES a shape.
def _module_constant(tree, name):
    """A module-level string constant, so a prompt built from named pieces can
    be read whole."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id == name:
            return _join(node.value, tree)
    return ""


def _join(node, tree):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _join(node.left, tree) + _join(node.right, tree)
    if isinstance(node, ast.Name):
        return _module_constant(tree, node.id)
    return ""


def _general_knowledge_literal(tree, name):
    """The full assembled prompt piece, following + and named constants.

    Previously this took only `BinOp.right` when it was a Constant, which held
    while _identity was exactly `agent_instruction + "..."`. The health safety
    floor made it `agent_instruction + "..." + HEALTH_SAFETY_FLOOR`, whose
    right operand is a Name — so the helper stopped finding _identity at all
    and four tests failed without anything being wrong with the prompt.
    Resolving names also means the floor's own text is now covered by the
    assertions below, which is what should have happened anyway.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id == name:
            text = _join(node.value, tree)
            if text:
                return text
    pytest.fail(f"{name} not found in app.py")


CONFLICTING = ["CRITICAL:", "LaTeX", "bullet points", "emojis"]


@pytest.mark.parametrize("banned", CONFLICTING)
def test_the_spoken_prompt_drops_the_conflicting_rules(app_tree, banned):
    identity = _general_knowledge_literal(app_tree, "_identity")
    assert banned not in identity, (
        f"{banned!r} survives into the spoken prompt; appending a contradiction "
        "after it is what failed in production")


@pytest.mark.parametrize("required", CONFLICTING)
def test_the_typed_prompt_keeps_them(app_tree, required):
    """Removing them for everyone would be a silent regression for every
    typed answer."""
    screen = _general_knowledge_literal(app_tree, "_screen_shape")
    assert required in screen


@pytest.mark.parametrize("guard", ["rich, detailed, helpful answers",
                                   "directly and thoroughly"])
def test_the_typed_prompt_keeps_its_scope_wording(app_tree, guard):
    """Removing these for everyone would be a silent regression on screen."""
    assert guard in _general_knowledge_literal(app_tree, "_screen_scope")


def test_each_branch_uses_its_own_half(app_tree):
    """Having the right text is not the same as using it. Swapping
    _spoken_scope for _screen_scope in the ternary hands the spoken branch the
    verbose wording while every literal stays perfectly correct — a mutation
    that survived until this test existed."""
    for node in ast.walk(app_tree):
        if not (isinstance(node, ast.IfExp)
                and "SPOKEN_ANSWER_DIRECTIVE" in ast.unparse(node.body)):
            continue
        spoken, screen = ast.unparse(node.body), ast.unparse(node.orelse)
        assert "_spoken_scope" in spoken, f"spoken branch: {spoken}"
        assert "_screen_scope" not in spoken, f"spoken branch got screen scope: {spoken}"
        assert "_screen_scope" in screen and "_screen_shape" in screen, \
            f"screen branch: {screen}"
        assert "SPOKEN_ANSWER_DIRECTIVE" not in screen
        return
    pytest.fail("the spoken/screen ternary was not found in app.py")


def test_speech_is_still_told_to_answer_completely(app_tree):
    """Shaping an answer for the ear must not become answering less of it."""
    assert "completely" in _general_knowledge_literal(app_tree, "_spoken_scope")


@pytest.mark.parametrize("volume", ["rich", "detailed", "thoroughly"])
def test_speech_is_not_told_to_be_verbose(app_tree, volume):
    """Update 27. Keeping "give rich, detailed answers" in the shared half
    backfired. Live, spoken replies came back LONGER than typed ones — 1200
    characters against 548 on the same question — because a standing demand
    for detail outweighs "a few sentences unless the question genuinely needs
    more". The guard was right; the wording was not."""
    assert volume not in _general_knowledge_literal(app_tree, "_spoken_scope")


def test_the_fallback_call_site_passes_spoken(app_tree):
    calls = [n for n in ast.walk(app_tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_llm_fallback"]
    assert calls, "no call to _llm_fallback found"
    for call in calls:
        assert any(kw.arg == "spoken" for kw in call.keywords), \
            f"call site drops voice_response: {ast.unparse(call)}"


# ── C: the deleted path stays deleted ────────────────────────────────────────
@pytest.mark.parametrize("name", ["VOICE_INTENTS", "_classify_voice_intent",
                                  "VoiceRequest", "voice_command"])
def test_the_regex_voice_path_is_gone(app_module, name):
    assert not hasattr(app_module, name), f"{name} came back"


def routes(app_module):
    return {getattr(r, "path", None) for r in app_module.app.routes}


@pytest.mark.parametrize("path", ["/voice", "/voice/intents"])
def test_the_orphaned_endpoints_are_unregistered(app_module, path):
    assert path not in routes(app_module)


# ── D: what was NOT deleted ──────────────────────────────────────────────────
@pytest.mark.parametrize("path", ["/api/voice/providers",
                                  "/api/voice/elevenlabs/voices",
                                  "/api/voice/elevenlabs/speak"])
def test_the_live_voice_proxy_survived(app_module, path):
    """These are the endpoints the frontend actually calls. A path-prefix sweep
    for '/voice' would have taken them with it."""
    assert path in routes(app_module)


# ── Update 28: an image question must not be answered by a text model ────────
# Routing rather than voice, but it lives here because it is what made the
# vision path unobservable: the RAG call is unconditional and returns as soon
# as the ML service answers, and the image is never sent to it. In production a
# user uploading a picture was told "I'm not able to view the image you're
# referring to", and _run_vision_agent was close to dead code.
def _chat_fn(tree):
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.AsyncFunctionDef) and n.name == "chat"), None)
    assert fn is not None, "chat() not found in app.py"
    return fn


def _first_line(fn, pred):
    lines = [n.lineno for n in ast.walk(fn) if pred(n)]
    assert lines, "node not found in chat()"
    return min(lines)


def _vision_line(fn):
    return _first_line(fn, lambda n: isinstance(n, ast.Name)
                       and n.id == "_run_vision_agent")


def _rag_post_line(fn):
    return _first_line(fn, lambda n: isinstance(n, ast.Constant)
                       and isinstance(n.value, str) and "/rag/chat" in n.value)


def test_the_image_branch_is_decided_before_the_text_rag_call(app_tree):
    fn = _chat_fn(app_tree)
    assert _vision_line(fn) < _rag_post_line(fn), (
        "the RAG call returns as soon as it has an answer, so anything after it "
        "is unreachable on the normal path")


def test_the_image_branch_is_decided_before_the_general_branch(app_tree):
    fn = _chat_fn(app_tree)
    use_rag = _first_line(fn, lambda n: isinstance(n, ast.Name) and n.id == "use_rag")
    assert _vision_line(fn) < use_rag


def test_the_image_branch_requires_actual_image_data(app_tree):
    """image=True with an empty payload fell through to the text path and got a
    text answer. Hoisting the branch on req.image alone would have turned that
    into "vision unavailable" — a regression introduced while fixing a bug."""
    fn = _chat_fn(app_tree)
    guards = [ast.unparse(n.test) for n in ast.walk(fn)
              if isinstance(n, ast.If) and "req.image" in ast.unparse(n.test)
              and "_run_vision_agent" in ast.unparse(n)]
    assert guards, "no if-branch guards the vision agent"
    for g in guards:
        assert "image_data" in g, f"guard ignores whether an image was sent: {g}"


# ── Update 24: the vision path ───────────────────────────────────────────────
def test_the_typed_vision_prompt_is_unchanged(app_module):
    """The five-point inventory is right for something you scan. Every typed
    image analysis must still get exactly it."""
    out = app_module._vision_prompt("what is this?")
    assert out == "what is this?" + app_module._VISION_SCREEN_TAIL
    assert "1. Visible objects" in out


def test_the_spoken_vision_prompt_drops_the_checklist(app_module):
    out = app_module._vision_prompt("what is this?", spoken=True)
    assert "1. Visible objects" not in out
    assert "numbered checklist" in out


@pytest.mark.parametrize("ground", ["objects", "people", "setting", "text",
                                    "cannot be determined", "generated"])
def test_the_spoken_vision_prompt_covers_the_same_ground(app_module, ground):
    """Shaping it for the ear must not mean describing less of the image."""
    assert ground in app_module._vision_prompt("x", spoken=True)


def test_the_empty_question_default_is_unchanged(app_module):
    assert app_module._vision_prompt("").startswith("Analyze this uploaded image.")
    assert app_module._vision_prompt("", spoken=True).startswith(
        "Analyze this uploaded image.")


def test_the_vision_system_prompt_gains_the_directive_only_when_spoken(app_module):
    base = app_module.VISION_SYSTEM_PROMPT
    assert app_module._vision_spoken(base, "describe it", False) == base
    assert app_module._vision_spoken(base, "describe it", True) == \
        base + app_module.SPOKEN_ANSWER_DIRECTIVE


def test_the_vision_directive_carves_out_chart_mode(app_module):
    base = app_module.VISION_SYSTEM_PROMPT
    q = "make a pie chart of this"
    assert app_module.is_chart_request(q), "fixture is not a chart request"
    assert app_module._vision_spoken(base, q, True) == base


def test_the_vision_call_site_forwards_voice_response(app_tree):
    calls = [n for n in ast.walk(app_tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_run_vision_agent"]
    assert calls, "no call to _run_vision_agent found"
    for call in calls:
        rendered = ast.unparse(call)
        assert "voice_response" in rendered, f"vision call drops it: {rendered}"


# ── Update 26: the deterministic reshape, and that no path escapes it ────────
def test_every_finalize_call_forwards_spoken(app_tree):
    """_finalize_response exists so no answer-bearing return can skip the
    outbound gate. The reshape lives there for the same reason — but only if
    every call site actually passes the flag. Two of the three are textually
    identical, which is exactly how one gets missed."""
    calls = [n for n in ast.walk(app_tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_finalize_response"]
    assert len(calls) >= 3, f"expected 3+ finalize calls, found {len(calls)}"
    for call in calls:
        passes = any(kw.arg == "spoken" for kw in call.keywords) or len(call.args) >= 8
        assert passes, f"finalize call drops spoken: {ast.unparse(call)[:90]}"


def _first_ref_line(app_module, name):
    """Line of the first reference to `name` inside _finalize_response.

    On the AST, not on the source text. Comments are not in the AST, so a
    sentence like "before the outbound gate" cannot be mistaken for the call
    it describes — which is exactly the kind of thing that makes an ordering
    assertion pass for the wrong reason.
    """
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(app_module._finalize_response)))
    lines = [n.lineno for n in ast.walk(tree)
             if isinstance(n, ast.Name) and n.id == name]
    assert lines, f"{name} is never referenced in _finalize_response"
    return min(lines)


def test_no_answer_bearing_return_bypasses_finalize(app_tree):
    """Update 29. The call-checking test above is structurally blind to a
    return that never calls _finalize_response at all, and one did: the
    deterministic chart shortcut returned a raw dict, skipping the outbound
    gate, the cognitive engine, learning capture and the spoken reshape.

    The inbound firewall had already been moved above this same shortcut
    because it returned before the check ran. The outbound half had the
    identical hole one direction later, and no test could see it, because
    checking every CALL is not the same as checking every RETURN.
    """
    fn = _chat_fn(app_tree)
    offenders, exempt = [], []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        src = ast.unparse(node.value)
        if '"answer"' not in src and "'answer'" not in src:
            continue
        if "_finalize_response" in src:
            continue
        # The firewall's own refusal is exempt: it is a fixed string produced
        # BY the security layer, and inspecting it on the way out would be
        # circular. Identified by its provider, not by position.
        if "'firewall'" in src or '"firewall"' in src:
            exempt.append(f"line {node.lineno}")
            continue
        offenders.append(f"line {node.lineno}: {src[:70]}")
    assert not offenders, (
        "answer-bearing returns bypassing the outbound gate:\n  "
        + "\n  ".join(offenders))
    # Exactly one, or the exemption stops being a carve-out and becomes a hole
    # anything can climb through by naming itself "firewall".
    assert len(exempt) == 1, f"expected 1 exempt return, found {len(exempt)}: {exempt}"


def test_a_chart_answer_survives_finalize_unchanged(app_module):
    """Routing charts through the choke point must not let the cognitive
    engine or anything else rewrite the block the frontend renders."""
    fence = "`" * 3
    block = fence + 'chart\n{"type":"pie","title":"S","data":[{"label":"A","value":1}]}\n' + fence
    out = asyncio.run(app_module._finalize_response(
        {"success": True, "answer": block, "response": block}, [], "t", None, ""))
    assert block in out["answer"]


def test_a_spoken_chart_answer_gains_its_sentence(app_module):
    """The defect that exposed the bypass: a chart asked for by voice came
    back as raw JSON with nothing to say."""
    fence = "`" * 3
    block = fence + 'chart\n{"type":"pie","title":"S","data":[{"label":"A","value":1}]}\n' + fence
    out = asyncio.run(app_module._finalize_response(
        {"success": True, "answer": block, "response": block}, [], "t", None, "",
        None, None, True))
    assert "S, a pie chart. A is 1." in out["answer"]
    assert block in out["answer"]


def test_the_reshape_runs_before_the_outbound_gate(app_module):
    """The firewall must inspect the text actually sent. Reshaping after it
    would put bytes on the wire that nothing inspected."""
    assert _first_ref_line(app_module, "to_spoken") < \
        _first_ref_line(app_module, "_outbound_gate")


def test_the_reshape_runs_after_the_cognitive_engine(app_module):
    """Its remedies are about fences and diagrams; they want the real markdown."""
    assert _first_ref_line(app_module, "cognitive_refine") < \
        _first_ref_line(app_module, "to_spoken")


def test_a_typed_answer_is_never_reshaped(app_module):
    src = inspect.getsource(app_module._finalize_response)
    assert "if spoken and SPOKEN_TEXT_AVAILABLE:" in src


def test_reshaping_is_available(app_module):
    assert app_module.SPOKEN_TEXT_AVAILABLE is True


def test_a_chart_block_survives_the_reshape(app_module):
    """The frontend renders ```chart. Stripping it would break the chart the
    user asked for — fenced blocks are parked, so this holds for free."""
    fence = "`" * 3
    block = fence + 'chart\n{"type":"pie","data":[{"label":"A","value":1}]}\n' + fence
    out = app_module.to_spoken("Here is the split:\n" + block)
    assert block in out


def test_chat_still_accepts_voice_response(app_module):
    assert app_module.ChatRequest().voice_response is False
    assert app_module.ChatRequest(voice_response=True).voice_response is True


# ── E: the cross-repo contract ───────────────────────────────────────────────
# This is the test that would have caught the Update 21 gap. The backend added
# "spoken" to the /rag/chat payload and every backend test passed, because the
# other side of the call lives in a different repository and a different
# process. eva-ml-service's ChatRequest does not forbid extra keys, so the
# service accepted the request, ignored the field, and returned a
# screen-formatted answer to a spoken question — silently, with a 200.
#
# Read-only, and skipped rather than failed when the submodule is absent: a
# checkout without submodules must not report a false defect.
ML_ROUTES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "eva-ml-service", "rag_routes_v2.py")


@pytest.fixture(scope="module")
def ml_chat_request_fields():
    if not os.path.isfile(ML_ROUTES):
        pytest.skip("eva-ml-service submodule not checked out")
    with open(ML_ROUTES, "r", encoding="utf-8-sig") as fh:
        tree = ast.parse(fh.read())
    cls = next((n for n in ast.walk(tree)
                if isinstance(n, ast.ClassDef) and n.name == "ChatRequest"), None)
    assert cls is not None, "eva-ml-service has no ChatRequest"
    return {t.target.id for t in cls.body if isinstance(t, ast.AnnAssign)
            and isinstance(t.target, ast.Name)}


def test_every_key_the_backend_sends_exists_on_the_service(app_tree,
                                                           ml_chat_request_fields):
    """Not just 'spoken' — any key added to the payload without a field on the
    other side is dropped on the floor exactly the same way."""
    _, keys = _rag_payload(app_tree)
    # "message" is the service's field name for what the backend calls the
    # question; the rest map one to one.
    unknown = keys - ml_chat_request_fields
    assert not unknown, (
        f"backend posts keys eva-ml-service will silently ignore: {sorted(unknown)}")


def test_the_service_declares_spoken(ml_chat_request_fields):
    assert "spoken" in ml_chat_request_fields


def _ml_spoken_directive():
    """The ML service's directive text, read without importing that package.

    Adjacent string literals are folded by the parser, so the whole return value
    arrives as one constant.
    """
    path = os.path.join(os.path.dirname(ML_ROUTES), "model_router.py")
    if not os.path.isfile(path):
        pytest.skip("eva-ml-service submodule not checked out")
    with open(path, "r", encoding="utf-8-sig") as fh:
        tree = ast.parse(fh.read())
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "spoken_directive"), None)
    assert fn is not None, "eva-ml-service has no spoken_directive"
    for node in ast.walk(fn):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str) and node.value.value.strip():
            return node.value.value
    pytest.fail("spoken_directive returns no string constant")


def _norm(text):
    """Collapse whitespace, so re-wrapping a line is not a difference."""
    return " ".join(text.split())


def test_the_two_directives_do_not_drift(app_module):
    """The same instruction exists in two repositories that deploy separately.
    Two copies of a prompt drift silently: a clause gets added to whichever one
    the bug was noticed in, and voice answers differ depending on which path
    happened to serve them. This compares the text, ignoring line wrapping."""
    assert _norm(app_module.SPOKEN_ANSWER_DIRECTIVE) == _norm(_ml_spoken_directive())
