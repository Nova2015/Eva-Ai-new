"""App-level wiring for the provider contract — JARVIS 1B.

providers.py is unit-tested on its own; this file proves the three backend call
sites now DELEGATE to it while keeping the behaviour that lives around the
provider call: the deterministic-chart short-circuit that must run before any
LLM, the Groq-only helper's not-configured copy and error string, and
_llm_fallback returning "" when every provider fails.
"""

import asyncio
import os
import sys

import pytest


@pytest.fixture(scope="module")
def app_module():
    for rel in ("", "runtime_engine", "review_engine"):
        p = os.path.abspath(os.path.join(os.path.dirname(__file__), rel))
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
    try:
        import app
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"app.py not importable here: {type(exc).__name__}: {exc}")
    return app


def _no_chart(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "deterministic_chart_response", lambda q: None)


def _boom(*a, **k):
    raise AssertionError("LLM provider must not be reached here")


# ── _llm_fallback ─────────────────────────────────────────────────────────────
def test_llm_fallback_short_circuits_on_a_deterministic_chart(app_module, monkeypatch):
    """Deterministic-first: a chart the backend can draw itself must return
    BEFORE any provider is called."""
    monkeypatch.setattr(app_module, "deterministic_chart_response", lambda q: "CHART-BLOCK")
    monkeypatch.setattr(app_module.providers, "complete", _boom)
    out = asyncio.run(app_module._llm_fallback("pie chart of a 30 b 70", []))
    assert out == "CHART-BLOCK"


def test_llm_fallback_returns_the_provider_answer(app_module, monkeypatch):
    _no_chart(app_module, monkeypatch)
    monkeypatch.setattr(app_module.providers, "complete",
                        lambda msgs, **k: app_module.providers.ProviderResult(
                            text="THE-ANSWER", provider="groq", model="m", ok=True))
    out = asyncio.run(app_module._llm_fallback("what is 2+2", []))
    assert out == "THE-ANSWER"


def test_llm_fallback_returns_empty_when_all_providers_fail(app_module, monkeypatch):
    """The caller treats "" as "fallback produced nothing"; a non-empty string
    here would overwrite the RAG placeholder with junk."""
    _no_chart(app_module, monkeypatch)
    monkeypatch.setattr(app_module.providers, "complete",
                        lambda msgs, **k: app_module.providers.ProviderResult(
                            text="", provider="unavailable", model="", ok=False))
    out = asyncio.run(app_module._llm_fallback("anything", []))
    assert out == ""


def test_llm_fallback_passes_no_temperature(app_module, monkeypatch):
    """The old cascade sent no temperature; complete must be called with None so
    the adapter omits it."""
    _no_chart(app_module, monkeypatch)
    seen = {}

    def fake_complete(msgs, **k):
        seen.update(k)
        return app_module.providers.ProviderResult(text="A", provider="groq", model="m", ok=True)

    monkeypatch.setattr(app_module.providers, "complete", fake_complete)
    asyncio.run(app_module._llm_fallback("hello", []))
    assert seen.get("temperature") is None


# ── ask_groq ──────────────────────────────────────────────────────────────────
def test_ask_groq_short_circuits_on_a_deterministic_chart(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "deterministic_chart_response", lambda q: "CHART")
    monkeypatch.setattr(app_module.providers, "dispatch", _boom)
    assert app_module.ask_groq("bar chart of x 1 y 2") == "CHART"


def test_ask_groq_reports_when_unconfigured(app_module, monkeypatch):
    _no_chart(app_module, monkeypatch)
    monkeypatch.setattr(app_module.providers, "configured", lambda pid: False)
    assert "GROQ_API_KEY is not configured" in app_module.ask_groq("analyze this repo")


def test_ask_groq_returns_the_dispatch_content(app_module, monkeypatch):
    _no_chart(app_module, monkeypatch)
    monkeypatch.setattr(app_module.providers, "configured", lambda pid: True)
    monkeypatch.setattr(app_module.providers, "dispatch", lambda *a, **k: "REPO-ANALYSIS")
    assert app_module.ask_groq("analyze this repo") == "REPO-ANALYSIS"


def test_ask_groq_empty_becomes_no_response(app_module, monkeypatch):
    _no_chart(app_module, monkeypatch)
    monkeypatch.setattr(app_module.providers, "configured", lambda pid: True)
    monkeypatch.setattr(app_module.providers, "dispatch", lambda *a, **k: "")
    assert app_module.ask_groq("analyze") == "No response"


def test_ask_groq_returns_an_error_string_on_exception(app_module, monkeypatch):
    _no_chart(app_module, monkeypatch)
    monkeypatch.setattr(app_module.providers, "configured", lambda pid: True)

    def raise_it(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(app_module.providers, "dispatch", raise_it)
    out = app_module.ask_groq("analyze")
    assert out.startswith("Groq analysis failed:")


def test_ask_groq_passes_temperature_and_model(app_module, monkeypatch):
    """ask_groq's 0.2 temperature and GROQ_MODEL override must reach dispatch."""
    _no_chart(app_module, monkeypatch)
    monkeypatch.setattr(app_module.providers, "configured", lambda pid: True)
    monkeypatch.setenv("GROQ_MODEL", "env-model")
    seen = {}

    def fake_dispatch(pid, messages, **k):
        seen["pid"] = pid
        seen.update(k)
        return "OK"

    monkeypatch.setattr(app_module.providers, "dispatch", fake_dispatch)
    app_module.ask_groq("analyze")
    assert seen["pid"] == "groq"
    assert seen["temperature"] == 0.2
    assert seen["model"] == "env-model"


# ── Phase 2 Step 8: the agent-task call site no longer bypasses the router ────
def test_agent_task_llm_no_longer_makes_a_raw_groq_call():
    """The agent-task llm() helper used a raw POST to api.groq.com. Step 8 routes
    it through providers.dispatch. Source-level so it needs no live agent run."""
    src = os.path.join(os.path.dirname(__file__), "app.py")
    with open(src, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    # the raw agent Groq HTTP endpoint is gone from the whole module
    assert "api.groq.com/openai/v1/chat/completions" not in text
    # and the agent llm helper delegates to the provider abstraction
    llm_start = text.find("async def llm(system")
    assert llm_start != -1
    llm_body = text[llm_start:llm_start + 700]
    assert "providers.dispatch(" in llm_body
    assert "api.groq.com" not in llm_body


# ── Phase 2 Step 9: /chat/stream eva_local streaming (opt-in) ─────────────────
def _fake_memory(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "get_memory",
                        lambda: type("M", (), {"add_message": lambda *a, **k: None})())


def test_chat_stream_routes_to_eva_local_when_configured(app_module, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(app_module, "deterministic_chart_response", lambda q: None)
    _fake_memory(app_module, monkeypatch)
    monkeypatch.setattr(app_module.providers, "configured", lambda pid: pid == "eva_local")

    seen = {}

    def fake_stream(messages, **k):
        seen["called"] = True
        seen["kwargs"] = k
        for tok in ["EVA ", "LOCAL ", "OK"]:
            yield tok

    monkeypatch.setattr(app_module.providers, "stream_eva_local", fake_stream)
    # any cloud path use must blow up — it must NOT be reached
    monkeypatch.setattr(app_module.providers, "dispatch",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("cloud dispatch used")))

    client = TestClient(app_module.app)
    r = client.post("/chat/stream", json={"question": "hi", "user_id": "u"})
    assert r.status_code == 200
    body = r.text
    assert seen.get("called") is True
    assert '"token": "EVA "' in body and '"token": "OK"' in body   # SSE token frames
    assert "data: [DONE]" in body                                  # completion event
    assert "api.groq.com" not in body                              # no Groq


def test_chat_stream_disabled_preserves_cloud_path(app_module, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(app_module, "deterministic_chart_response", lambda q: None)
    monkeypatch.setattr(app_module.providers, "configured", lambda pid: False)   # eva_local NOT configured
    monkeypatch.setattr(app_module.providers, "stream_eva_local",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("eva_local streamed while disabled")))
    monkeypatch.delenv("GROQ_API_KEY", raising=False)              # existing no-key SSE branch

    client = TestClient(app_module.app)
    r = client.post("/chat/stream", json={"question": "hi", "user_id": "u"})
    assert r.status_code == 200
    assert "GROQ_API_KEY not set" in r.text                        # cloud path unchanged
    assert "data: [DONE]" in r.text


def test_chat_stream_eva_local_failure_is_a_streaming_error_no_groq(app_module, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(app_module, "deterministic_chart_response", lambda q: None)
    _fake_memory(app_module, monkeypatch)
    monkeypatch.setattr(app_module.providers, "configured", lambda pid: pid == "eva_local")

    def boom(messages, **k):
        raise RuntimeError("Machine A down")
        yield  # pragma: no cover — marks this a generator

    monkeypatch.setattr(app_module.providers, "stream_eva_local", boom)
    monkeypatch.setattr(app_module.providers, "dispatch",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("Groq fallback used")))

    client = TestClient(app_module.app)
    r = client.post("/chat/stream", json={"question": "hi", "user_id": "u"})
    assert r.status_code == 200
    # The existing streaming error event (json.dumps escapes the ❌ to ❌).
    assert "Error:" in r.text and "Machine A down" in r.text
    assert "data: [DONE]" in r.text
    assert "api.groq.com" not in r.text                           # no Groq fallback, no A->B

# ── Phase 2 Step 10: /api/health/providers exposes EVA local A/B safely ──────
def test_health_providers_exposes_eva_local_ab_status(app_module, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(app_module, "_shadow_supabase", lambda: None)   # no durable store in test
    monkeypatch.setenv("EVA_LOCAL_ENABLED", "true")
    monkeypatch.setenv("EVA_LOCAL_A_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("EVA_LOCAL_A_MODEL", "cfg-model-a")
    monkeypatch.delenv("EVA_LOCAL_B_URL", raising=False)
    monkeypatch.delenv("EVA_LOCAL_B_MODEL", raising=False)

    client = TestClient(app_module.app)
    r = client.get("/api/health/providers")
    assert r.status_code == 200
    body = r.json()

    assert "live" in body                       # existing field preserved
    eva = body["eva_local"]                     # additive Step 10 field
    assert eva["selected_machine"] == "A"
    by = {m["machine"]: m for m in eva["machines"]}
    assert by["A"]["configured"] is True
    assert by["A"]["base_url"] == "http://127.0.0.1:11434/v1"
    assert by["A"]["model"] == "cfg-model-a"
    assert by["B"]["configured"] is False       # B absent, not invented
    assert eva["probe"] == "unavailable"        # no probe → reachable stays None
    assert by["A"]["reachable"] is None

    # no secrets anywhere in the payload
    raw = r.text
    for secret in ("Bearer", "Authorization", "eva-local", "apikey"):
        assert secret not in raw


def test_health_providers_eva_local_absent_config_is_safe(app_module, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(app_module, "_shadow_supabase", lambda: None)
    for k in ("EVA_LOCAL_ENABLED", "EVA_LOCAL_A_URL", "EVA_LOCAL_A_MODEL",
              "EVA_LOCAL_B_URL", "EVA_LOCAL_B_MODEL"):
        monkeypatch.delenv(k, raising=False)

    client = TestClient(app_module.app)
    body = client.get("/api/health/providers").json()
    eva = body["eva_local"]
    assert eva["enabled"] is False and eva["available"] is False
    assert eva["selected_machine"] is None
    assert all(m["configured"] is False for m in eva["machines"])

# ── Phase 2 Step 12: recorded eva_local call outcomes reach the health endpoint ──
def test_health_providers_reports_eva_local_call_health(app_module, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(app_module, "_shadow_supabase", lambda: None)
    monkeypatch.setenv("EVA_LOCAL_ENABLED", "true")
    monkeypatch.setenv("EVA_LOCAL_A_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("EVA_LOCAL_A_MODEL", "cfg-model-a")

    providers = app_module.providers
    with providers._health_lock:
        providers._health.pop("eva_local", None)
    providers.record("eva_local", ok=True, latency_ms=12)
    providers.record("eva_local", ok=False, code="TIMEOUT", latency_ms=99)

    body = TestClient(app_module.app).get("/api/health/providers").json()
    health = body["eva_local"]["health"]
    assert health["requests"] == 2 and health["failures"] == 1
    assert health["last_error_code"] == "TIMEOUT"
    assert health["last_latency_ms"] == 99
    # eva_local still does not appear in the cloud-cascade `live` array
    assert "eva_local" not in [p["id"] for p in body["live"]]

    with providers._health_lock:
        providers._health.pop("eva_local", None)

# ── the internal steer never reaches the user turn (Local Production Readiness) ──
def test_the_steer_is_system_text_not_user_text(app_module):
    """It used to be appended to the user's message, so a small local model
    echoed "[Internal EVA prompt enhancement] ..." straight back into answers.
    Instructions for the assistant belong in the assistant's instructions."""
    guidance = app_module.enhancement_guidance("write me a haiku", {"intent": "writing"})
    assert guidance                                    # there is a steer
    assert "write me a haiku" not in guidance          # but it does not carry the user's words
    assert "Intent:" in guidance
    assert "[Internal EVA prompt enhancement]" not in guidance


def test_the_steer_is_empty_for_an_empty_prompt(app_module):
    assert app_module.enhancement_guidance("") == ""
    assert app_module.enhancement_guidance("   ") == ""


def test_the_steer_is_never_concatenated_onto_a_user_message(app_module):
    """The leak was structural: the marker was built into the string that became
    the user turn. Assert the concatenation is gone, and that the steer itself
    never carries the marker into any caller."""
    import os
    src = os.path.join(os.path.dirname(app_module.__file__), "app.py")
    with open(src, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    assert 'f"{original}' not in text          # the old user-turn concatenation

    marker = "[Internal EVA prompt enhancement]"
    for intent in ("writing", "code", "rag", "design", "data", "security", "general"):
        guidance = app_module.enhancement_guidance("do the thing", {"intent": intent})
        assert marker not in guidance
        assert "do the thing" not in guidance
