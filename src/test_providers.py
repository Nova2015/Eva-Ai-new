"""Unit tests for the backend provider contract — JARVIS 1B.

The contract's job is to be the ONE door to the LLM providers while changing no
behaviour the old three hand-written cascades had. So the properties guarded
here are the ones a refactor could silently break: the failover ORDER, that an
empty response falls through, that a None temperature is not sent, that the
error label is a fixed enum, and that health is recorded without ever storing a
prompt or a key.

No network and no provider SDKs: adapters are faked in-process.
"""

import sys
import types

import pytest

try:
    import providers
except ImportError:  # running from the repo root
    from src import providers  # type: ignore


# ── fakes ─────────────────────────────────────────────────────────────────────
class _FakeMessage:
    def __init__(self, content): self.content = content


class _FakeChoice:
    def __init__(self, content): self.message = _FakeMessage(content)


class _FakeCompletion:
    def __init__(self, content): self.choices = [_FakeChoice(content)]


def _openai_style_client(captured, content="OK"):
    """A stand-in for groq.Groq / openai.OpenAI that records the create() kwargs."""
    class _Completions:
        def create(self, **kwargs):
            captured.clear(); captured.update(kwargs)
            return _FakeCompletion(content)

    class _Chat:
        def __init__(self): self.completions = _Completions()

    class _Client:
        last_kwargs: dict = {}

        def __init__(self, api_key=None, **kwargs):
            type(self).last_kwargs = dict(kwargs)
            self.chat = _Chat()
    return _Client


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Every provider configured, health cleared, adapters restored after."""
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.delenv("EVA_LOCAL_ENABLED", raising=False)
    monkeypatch.delenv("EVA_LOCAL_A_URL", raising=False)
    monkeypatch.delenv("EVA_LOCAL_B_URL", raising=False)
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    saved = dict(providers._ADAPTERS)
    with providers._health_lock:
        providers._health.clear()
    yield
    providers._ADAPTERS.clear()
    providers._ADAPTERS.update(saved)
    with providers._health_lock:
        providers._health.clear()


def _adapter(pid, out=None, exc=None):
    def f(messages, model, max_tokens, temperature):
        if exc:
            raise exc
        return out
    return providers._ADAPTERS.__setitem__(pid, f)


MSG = [{"role": "user", "content": "hi"}]


# ── A: failover chain — the order is the whole point ─────────────────────────
def test_failover_order_is_groq_openai_gemini():
    assert [pid for pid, _ in providers.failover_chain()] == ["groq", "openai", "gemini"]


def test_failover_skips_an_unconfigured_provider(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert [pid for pid, _ in providers.failover_chain()] == ["groq", "gemini"]


def test_failover_pairs_each_provider_with_its_model():
    chain = dict(providers.failover_chain())
    assert chain["groq"] == "openai/gpt-oss-120b"
    assert chain["openai"] == "gpt-4o-mini"
    assert chain["gemini"] == providers.PROVIDER_SPECS["gemini"]["model"]


def test_a_custom_order_is_honoured():
    order = ["gemini", "groq"]
    assert [pid for pid, _ in providers.failover_chain(order)] == ["gemini", "groq"]


# ── B: error classification is a fixed enum ──────────────────────────────────
@pytest.mark.parametrize("text,code", [
    ("Error code: 429 rate limit exceeded", "RATE_LIMITED"),
    ("quota exceeded", "RATE_LIMITED"),
    ("resource_exhausted", "RATE_LIMITED"),
    ("401 unauthorized", "AUTH"),
    ("invalid api key", "AUTH"),
    ("request timed out", "TIMEOUT"),
    ("deadline exceeded", "TIMEOUT"),
    ("model not found: 404", "MODEL_NOT_FOUND"),
    ("empty response", "EMPTY_RESPONSE"),
    ("something else entirely", "ERROR"),
])
def test_classify_error_maps_to_the_enum(text, code):
    assert providers.classify_error(Exception(text)) == code
    assert providers.classify_error(Exception(text)) in providers.ERROR_CODES


# ── C: dispatch — pure, raises on error, resolves the model ──────────────────
def test_dispatch_unknown_provider_raises():
    with pytest.raises(RuntimeError):
        providers.dispatch("kimi", MSG)


def test_dispatch_calls_the_named_adapter_and_returns_text():
    _adapter("groq", out="GROQ-SAYS")
    assert providers.dispatch("groq", MSG) == "GROQ-SAYS"


def test_dispatch_uses_the_callers_model_over_the_default():
    seen = {}
    providers._ADAPTERS["groq"] = lambda m, model, mt, t: seen.setdefault("model", model) or "x"
    providers.dispatch("groq", MSG, model="my-custom-model")
    assert seen["model"] == "my-custom-model"


def test_dispatch_falls_back_to_the_registry_model():
    seen = {}
    providers._ADAPTERS["groq"] = lambda m, model, mt, t: seen.setdefault("model", model) or "x"
    providers.dispatch("groq", MSG)
    assert seen["model"] == "openai/gpt-oss-120b"


def test_dispatch_propagates_a_provider_error():
    _adapter("groq", exc=RuntimeError("429 rate limit"))
    with pytest.raises(RuntimeError):
        providers.dispatch("groq", MSG)


# ── D: the temperature is only sent when the caller supplies it ──────────────
def _install_fake_module(monkeypatch, name, attr, client):
    mod = types.ModuleType(name)
    setattr(mod, attr, client)
    monkeypatch.setitem(sys.modules, name, mod)


def test_groq_adapter_omits_temperature_when_none(monkeypatch):
    captured = {}
    _install_fake_module(monkeypatch, "groq", "Groq", _openai_style_client(captured))
    providers._call_groq(MSG, "m", 100, None)
    assert "temperature" not in captured           # old no-temp call preserved
    providers._call_groq(MSG, "m", 100, 0.7)
    assert captured["temperature"] == 0.7           # and passed when supplied


def test_openai_adapter_omits_temperature_when_none(monkeypatch):
    captured = {}
    _install_fake_module(monkeypatch, "openai", "OpenAI", _openai_style_client(captured))
    providers._call_openai(MSG, "gpt-4o-mini", 1024, None)
    assert "temperature" not in captured
    assert captured["max_tokens"] == 1024 and captured["model"] == "gpt-4o-mini"


def test_gemini_adapter_sends_system_and_last_message_only(monkeypatch):
    captured = {}

    class _GM:
        def __init__(self, model): captured["model"] = model
        def generate_content(self, parts):
            captured["parts"] = parts
            return types.SimpleNamespace(text="GEM")

    fake = types.ModuleType("google.generativeai")
    fake.configure = lambda api_key=None: None
    fake.GenerativeModel = _GM
    google_mod = sys.modules.get("google") or types.ModuleType("google")
    monkeypatch.setitem(sys.modules, "google", google_mod)
    monkeypatch.setitem(sys.modules, "google.generativeai", fake)

    three = [{"role": "system", "content": "SYS"},
             {"role": "user", "content": "MIDDLE"},
             {"role": "user", "content": "LAST"}]
    assert providers._call_gemini(three, "gemini-3.5-flash", 1024, None) == "GEM"
    # The old backend call dropped the middle: system + last only.
    assert captured["parts"] == ["SYS", "LAST"]
    assert captured["model"] == "gemini-3.5-flash"


# ── E: complete — the cascade semantics ──────────────────────────────────────
def test_complete_returns_the_first_provider_that_answers():
    _adapter("groq", out="GROQ")
    _adapter("openai", out="OPENAI")
    r = providers.complete(MSG)
    assert (r.provider, r.text, r.ok) == ("groq", "GROQ", True)


def test_an_empty_answer_falls_through_to_the_next_provider():
    # The single most important behaviour: an empty groq answer must NOT be
    # returned; it hands off to openai, exactly as the old cascade did.
    _adapter("groq", out="")
    _adapter("openai", out="OPENAI")
    r = providers.complete(MSG)
    assert (r.provider, r.text) == ("openai", "OPENAI")


def test_a_raising_provider_is_skipped_and_recorded():
    _adapter("groq", exc=RuntimeError("429 rate limit"))
    _adapter("openai", out="OPENAI")
    r = providers.complete(MSG)
    assert r.provider == "openai"
    assert r.errors == ["groq: RATE_LIMITED"]


def test_all_providers_failing_yields_an_unavailable_result():
    _adapter("groq", exc=RuntimeError("boom"))
    _adapter("openai", exc=RuntimeError("boom"))
    _adapter("gemini", exc=RuntimeError("boom"))
    r = providers.complete(MSG)
    assert r.ok is False and r.provider == "unavailable" and r.text == ""


def test_complete_respects_a_custom_order():
    _adapter("groq", out="GROQ")
    _adapter("gemini", out="GEMINI")
    r = providers.complete(MSG, order=["gemini", "groq"])
    assert r.provider == "gemini"


# ── F: health recording — counts and enums only, no prompt, no key ───────────
def test_a_success_is_recorded_healthy():
    _adapter("groq", out="OK")
    providers.complete(MSG)
    st = {s["id"]: s for s in providers.status()}
    assert st["groq"]["status"] == "healthy"
    assert st["groq"]["requests"] == 1 and st["groq"]["failures"] == 0


def test_a_rate_limit_shows_rate_limited_then_clears_on_success():
    _adapter("groq", exc=RuntimeError("429 rate limit"))
    _adapter("openai", out="OK")
    providers.complete(MSG)
    assert {s["id"]: s for s in providers.status()}["groq"]["status"] == "rate_limited"
    # A later success clears it.
    _adapter("groq", out="OK")
    providers.complete(MSG)
    assert {s["id"]: s for s in providers.status()}["groq"]["status"] == "healthy"


def test_an_unconfigured_provider_reads_no_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert {s["id"]: s for s in providers.status()}["gemini"]["status"] == "no_key"


def test_status_never_leaks_a_prompt_or_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "sk-SECRET-KEY-VALUE")
    _adapter("groq", out="OK")
    providers.complete([{"role": "user", "content": "SECRET-PROMPT-TEXT"}])
    blob = repr(providers.status())
    assert "SECRET-PROMPT-TEXT" not in blob
    assert "sk-SECRET-KEY-VALUE" not in blob


# ── G: the Local Ollama backstop (JARVIS 3) ──────────────────────────────────
def test_local_is_last_in_the_order():
    # A pure floor: the cloud providers ahead of it are untouched.
    assert providers.PROVIDER_ORDER[-1] == "local"
    assert providers.PROVIDER_ORDER[:3] == ["groq", "openai", "gemini"]


def test_local_is_skipped_cleanly_when_ollama_url_is_unset(monkeypatch):
    monkeypatch.delenv("OLLAMA_URL", raising=False)
    assert "local" not in [pid for pid, _ in providers.failover_chain()]


def test_local_joins_the_chain_last_when_ollama_url_is_set(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://host:11434")
    chain = [pid for pid, _ in providers.failover_chain()]
    assert "local" in chain and chain[-1] == "local"


def test_local_adapter_targets_the_ollama_openai_endpoint(monkeypatch):
    seen = {}

    class _Completions:
        def create(self, **kwargs):
            seen["create_kwargs"] = kwargs
            return _FakeCompletion("LOCAL-OK")

    class _Chat:
        def __init__(self): self.completions = _Completions()

    class _Client:
        def __init__(self, api_key=None, base_url=None):
            seen["api_key"] = api_key
            seen["base_url"] = base_url
            self.chat = _Chat()

    fake = types.ModuleType("openai")
    fake.OpenAI = _Client
    monkeypatch.setenv("OLLAMA_URL", "http://myhost:11434/")   # trailing slash
    monkeypatch.setitem(sys.modules, "openai", fake)

    out = providers._call_local(MSG, "llama3.1", 100, None)
    assert out == "LOCAL-OK"
    assert seen["base_url"] == "http://myhost:11434/v1"        # slash stripped, /v1 appended
    assert seen["api_key"]                                     # non-empty (Ollama ignores it)
    assert seen["create_kwargs"]["model"] == "llama3.1"
    assert "temperature" not in seen["create_kwargs"]          # None omitted, as elsewhere


def test_local_is_a_valid_dispatch_target():
    # Registered like any other provider; dispatch resolves it (adapter faked
    # so no real HTTP), rather than raising "unknown provider".
    providers._ADAPTERS["local"] = lambda m, model, mt, t: "LOCAL"
    assert providers.dispatch("local", MSG, model="llama3.1") == "LOCAL"


# ── EVA Server Local (Phase 2 Step 8) ─────────────────────────────────────────
def _fake_openai_module(captured, content="EVA-LOCAL-OK"):
    mod = types.ModuleType("openai")

    class _Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _FakeCompletion(content)

    class _Chat:
        def __init__(self): self.completions = _Completions()

    class _OpenAI:
        def __init__(self, api_key=None, base_url=None, **kwargs):
            captured["_api_key"] = api_key
            captured["_base_url"] = base_url
            captured["_client_kwargs"] = dict(kwargs)
            self.chat = _Chat()

    mod.OpenAI = _OpenAI
    return mod


def _clear_eva_env(monkeypatch):
    for k in ("EVA_LOCAL_ENABLED", "EVA_LOCAL_RUNTIME", "EVA_LOCAL_A_URL", "EVA_LOCAL_B_URL",
              "EVA_LOCAL_A_MODEL", "EVA_LOCAL_B_MODEL"):
        monkeypatch.delenv(k, raising=False)


def test_eva_local_is_registered_but_not_in_the_order():
    assert "eva_local" in providers.PROVIDER_SPECS
    assert "eva_local" not in providers.PROVIDER_ORDER          # never in the cascade / never default
    assert providers.PROVIDER_ORDER == ["groq", "openai", "gemini", "local"]


def test_eva_local_configured_requires_enabled_and_a_machine(monkeypatch):
    _clear_eva_env(monkeypatch)
    assert providers.configured("eva_local") is False           # disabled + unconfigured
    monkeypatch.setenv("EVA_LOCAL_A_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("EVA_LOCAL_A_MODEL", "gemma3:12b")
    assert providers.configured("eva_local") is False           # configured but NOT enabled
    monkeypatch.setenv("EVA_LOCAL_ENABLED", "true")
    assert providers.configured("eva_local") is True


def test_eva_local_disabled_leaves_cloud_cascade_intact(monkeypatch):
    _clear_eva_env(monkeypatch)                                 # EVA_LOCAL_ENABLED unset
    chain_ids = [pid for pid, _ in providers.failover_chain()]
    assert chain_ids == ["groq", "openai", "gemini"]           # local skipped (no OLLAMA_URL); eva_local absent
    assert "eva_local" not in chain_ids


def test_eva_local_resolve_env_and_registry_first(monkeypatch):
    _clear_eva_env(monkeypatch)
    monkeypatch.setenv("EVA_LOCAL_A_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("EVA_LOCAL_A_MODEL", "env-model")
    assert providers.eva_local_resolve() == {
        "machine": "A", "base_url": "http://127.0.0.1:11434/v1", "model": "env-model"}
    # registry-first: a registry machine overrides env, no source change
    monkeypatch.setattr(providers, "_eva_local_registry",
                        lambda: {"machines": {"A": {"base_url": "http://192.168.1.5:8000/v1", "model": "reg-model"}}})
    cfg = providers.eva_local_resolve()
    assert cfg["base_url"] == "http://192.168.1.5:8000/v1" and cfg["model"] == "reg-model"


def test_eva_local_machine_b_optional_and_not_invented(monkeypatch):
    _clear_eva_env(monkeypatch)
    monkeypatch.setenv("EVA_LOCAL_B_URL", "http://192.168.1.20:11434/v1")   # B only
    monkeypatch.setenv("EVA_LOCAL_B_MODEL", "model-b")
    assert providers.eva_local_resolve()["machine"] == "B"
    monkeypatch.setenv("EVA_LOCAL_A_URL", "http://127.0.0.1:11434/v1")      # A + B
    monkeypatch.setenv("EVA_LOCAL_A_MODEL", "model-a")
    assert providers.eva_local_resolve()["machine"] == "A"                  # A preferred
    monkeypatch.delenv("EVA_LOCAL_B_URL")
    monkeypatch.delenv("EVA_LOCAL_B_MODEL")
    assert providers.eva_local_resolve()["machine"] == "A"                  # B absent, not invented


def test_eva_local_ssrf_rejects_unsafe_base_urls(monkeypatch):
    _clear_eva_env(monkeypatch)
    monkeypatch.setenv("EVA_LOCAL_A_MODEL", "m")
    for bad in ("http://8.8.8.8/v1", "ftp://127.0.0.1", "http://169.254.169.254/v1", "http://u:p@127.0.0.1/v1"):
        monkeypatch.setenv("EVA_LOCAL_A_URL", bad)
        assert providers.eva_local_resolve() is None
    assert providers.validate_base_url("http://192.168.1.5:8000/v1") == "http://192.168.1.5:8000/v1"


def test_eva_local_dispatch_is_config_driven_and_needs_no_cloud_key(monkeypatch):
    _clear_eva_env(monkeypatch)
    for k in ("GROQ_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(k, raising=False)                    # NO cloud keys
    monkeypatch.setenv("EVA_LOCAL_ENABLED", "true")
    monkeypatch.setenv("EVA_LOCAL_A_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("EVA_LOCAL_A_MODEL", "cfg-model-1")
    captured = {}
    monkeypatch.setitem(sys.modules, "openai", _fake_openai_module(captured, "local-answer"))

    assert providers.dispatch("eva_local", MSG) == "local-answer"
    assert captured["_base_url"] == "http://127.0.0.1:11434/v1"
    assert captured["model"] == "cfg-model-1"                   # config model, not the import-time spec
    assert captured["_api_key"] == "eva-local"                 # static non-secret; no cloud key

    # change ONLY config → outgoing request changes, no source edit
    captured.clear()
    monkeypatch.setenv("EVA_LOCAL_A_MODEL", "cfg-model-2")
    monkeypatch.setenv("EVA_LOCAL_A_URL", "http://192.168.1.50:9000/v1")
    providers.dispatch("eva_local", MSG)
    assert captured["model"] == "cfg-model-2"
    assert captured["_base_url"] == "http://192.168.1.50:9000/v1"


def test_eva_local_dispatch_refuses_when_disabled(monkeypatch):
    _clear_eva_env(monkeypatch)
    monkeypatch.setenv("EVA_LOCAL_A_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("EVA_LOCAL_A_MODEL", "m")               # configured but NOT enabled
    with pytest.raises(RuntimeError):
        providers.dispatch("eva_local", MSG)


# ── EVA Server Local STREAMING (Phase 2 Step 9) ───────────────────────────────
class _FakeDelta:
    def __init__(self, content): self.content = content


class _FakeStreamChoice:
    def __init__(self, content): self.delta = _FakeDelta(content)


class _FakeChunk:
    def __init__(self, choices): self.choices = choices


def _fake_openai_streaming_module(captured, chunks):
    """chunks: list where each item is a content str, None (empty delta), or []
    (a frame with no choices). Records create() kwargs incl. stream + base_url."""
    mod = types.ModuleType("openai")

    def _to_chunk(item):
        if item == []:
            return _FakeChunk([])                       # no choices (keepalive/role)
        return _FakeChunk([_FakeStreamChoice(item)])    # item is a str or None

    class _Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            if kwargs.get("stream"):
                return iter([_to_chunk(c) for c in chunks])
            return _FakeCompletion("".join(c for c in chunks if isinstance(c, str)))

    class _Chat:
        def __init__(self): self.completions = _Completions()

    class _OpenAI:
        def __init__(self, api_key=None, base_url=None, **kwargs):
            captured["_api_key"] = api_key
            captured["_base_url"] = base_url
            captured["_client_kwargs"] = dict(kwargs)
            self.chat = _Chat()

    mod.OpenAI = _OpenAI
    return mod


def test_eva_local_stream_uses_stream_true_config_and_no_cloud_key(monkeypatch):
    _clear_eva_env(monkeypatch)
    for k in ("GROQ_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(k, raising=False)                    # NO cloud keys
    monkeypatch.setenv("EVA_LOCAL_ENABLED", "true")
    monkeypatch.setenv("EVA_LOCAL_A_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("EVA_LOCAL_A_MODEL", "cfg-model-1")
    captured = {}
    monkeypatch.setitem(sys.modules, "openai",
                        _fake_openai_streaming_module(captured, ["EVA ", None, [], "OK"]))

    out = list(providers.stream_eva_local(MSG))
    assert out == ["EVA ", "OK"]                               # None + no-choices frames skipped
    assert captured["stream"] is True
    assert captured["model"] == "cfg-model-1"                  # configured model
    assert captured["_base_url"] == "http://127.0.0.1:11434/v1"  # configured base_url
    assert captured["_api_key"] == "eva-local"                 # static non-secret; no cloud key


def test_eva_local_stream_config_substitution(monkeypatch):
    _clear_eva_env(monkeypatch)
    monkeypatch.setenv("EVA_LOCAL_ENABLED", "true")
    monkeypatch.setenv("EVA_LOCAL_A_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("EVA_LOCAL_A_MODEL", "model-X")
    captured = {}
    monkeypatch.setitem(sys.modules, "openai", _fake_openai_streaming_module(captured, ["x"]))
    list(providers.stream_eva_local(MSG))
    assert captured["model"] == "model-X" and captured["_base_url"] == "http://127.0.0.1:11434/v1"

    # change ONLY config → next stream targets the new model/url, no code change
    monkeypatch.setenv("EVA_LOCAL_A_MODEL", "model-Y")
    monkeypatch.setenv("EVA_LOCAL_A_URL", "http://192.168.1.50:9000/v1")
    monkeypatch.setitem(sys.modules, "openai", _fake_openai_streaming_module(captured, ["y"]))
    list(providers.stream_eva_local(MSG))
    assert captured["model"] == "model-Y" and captured["_base_url"] == "http://192.168.1.50:9000/v1"


def test_eva_local_stream_refuses_when_disabled_or_unconfigured(monkeypatch):
    _clear_eva_env(monkeypatch)
    monkeypatch.setenv("EVA_LOCAL_A_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("EVA_LOCAL_A_MODEL", "m")               # configured but NOT enabled
    with pytest.raises(RuntimeError):
        list(providers.stream_eva_local(MSG))
    # enabled but no machine
    monkeypatch.setenv("EVA_LOCAL_ENABLED", "true")
    monkeypatch.delenv("EVA_LOCAL_A_URL")
    with pytest.raises(RuntimeError):
        list(providers.stream_eva_local(MSG))


def test_eva_local_stream_error_propagates_no_fallback(monkeypatch):
    _clear_eva_env(monkeypatch)
    monkeypatch.setenv("EVA_LOCAL_ENABLED", "true")
    monkeypatch.setenv("EVA_LOCAL_A_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("EVA_LOCAL_A_MODEL", "m")

    mod = types.ModuleType("openai")

    class _BoomStream:
        def __iter__(self): return self
        def __next__(self): raise RuntimeError("Machine A down mid-stream")

    class _Completions:
        def create(self, **k): return _BoomStream()

    class _Chat:
        def __init__(self): self.completions = _Completions()

    class _OpenAI:
        def __init__(self, api_key=None, base_url=None, **kw): self.chat = _Chat()

    mod.OpenAI = _OpenAI
    monkeypatch.setitem(sys.modules, "openai", mod)
    with pytest.raises(RuntimeError):                          # propagates; NO A->B, NO Groq here
        list(providers.stream_eva_local(MSG))

# ── EVA Server Local A/B health/status (Phase 2 Step 10) ─────────────────────
def _by_machine(status):
    return {m["machine"]: m for m in status["machines"]}


def test_eva_local_status_neither_configured(monkeypatch):
    _clear_eva_env(monkeypatch)
    s = providers.eva_local_status()
    assert s["enabled"] is False and s["available"] is False
    assert s["selected_machine"] is None
    assert s["probe"] == "unavailable"                  # no backend probe exists
    for m in s["machines"]:
        assert m["configured"] is False
        assert m["detail"] == "unconfigured"
        assert m["base_url"] is None and m["model"] is None
        assert m["reachable"] is None                   # never guessed


def test_eva_local_status_a_configured(monkeypatch):
    _clear_eva_env(monkeypatch)
    monkeypatch.setenv("EVA_LOCAL_ENABLED", "true")
    monkeypatch.setenv("EVA_LOCAL_A_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("EVA_LOCAL_A_MODEL", "cfg-model-a")
    s = providers.eva_local_status()
    by = _by_machine(s)
    assert s["enabled"] is True and s["available"] is True
    assert s["selected_machine"] == "A"
    assert by["A"]["configured"] is True and by["A"]["detail"] == "configured"
    assert by["A"]["base_url"] == "http://127.0.0.1:11434/v1"
    assert by["A"]["model"] == "cfg-model-a"
    assert by["B"]["configured"] is False               # B absent, not invented
    assert by["B"]["base_url"] is None and by["B"]["model"] is None


def test_eva_local_status_b_configured(monkeypatch):
    _clear_eva_env(monkeypatch)
    monkeypatch.setenv("EVA_LOCAL_ENABLED", "true")
    monkeypatch.setenv("EVA_LOCAL_B_URL", "http://192.168.1.20:11434/v1")
    monkeypatch.setenv("EVA_LOCAL_B_MODEL", "cfg-model-b")
    s = providers.eva_local_status()
    by = _by_machine(s)
    assert s["selected_machine"] == "B"                 # B-only is valid
    assert by["B"]["configured"] is True
    assert by["B"]["base_url"] == "http://192.168.1.20:11434/v1"
    assert by["B"]["model"] == "cfg-model-b"
    assert by["A"]["configured"] is False and by["A"]["detail"] == "unconfigured"


def test_eva_local_status_a_preferred_when_both_configured(monkeypatch):
    _clear_eva_env(monkeypatch)
    monkeypatch.setenv("EVA_LOCAL_ENABLED", "true")
    monkeypatch.setenv("EVA_LOCAL_A_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("EVA_LOCAL_A_MODEL", "model-a")
    monkeypatch.setenv("EVA_LOCAL_B_URL", "http://192.168.1.20:11434/v1")
    monkeypatch.setenv("EVA_LOCAL_B_MODEL", "model-b")
    s = providers.eva_local_status()
    by = _by_machine(s)
    assert s["selected_machine"] == "A"                 # A preferred
    assert by["A"]["configured"] is True and by["B"]["configured"] is True
    # reporting B does NOT introduce failover: resolve still returns only A
    assert providers.eva_local_resolve()["machine"] == "A"


def test_eva_local_status_rejects_unsafe_url_without_echoing_it(monkeypatch):
    _clear_eva_env(monkeypatch)
    monkeypatch.setenv("EVA_LOCAL_ENABLED", "true")
    monkeypatch.setenv("EVA_LOCAL_A_MODEL", "m")
    for bad in ("http://8.8.8.8/v1", "ftp://127.0.0.1", "http://169.254.169.254/v1",
                "http://u:p@127.0.0.1/v1"):
        monkeypatch.setenv("EVA_LOCAL_A_URL", bad)
        by = _by_machine(providers.eva_local_status())
        assert by["A"]["configured"] is False
        assert by["A"]["detail"] == "invalid_base_url"
        assert by["A"]["base_url"] is None              # unsafe value not echoed back
        assert bad not in str(by["A"])


def test_eva_local_status_exposes_no_secrets(monkeypatch):
    _clear_eva_env(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "gsk_SECRET")
    monkeypatch.setenv("OPENAI_API_KEY", "sk_SECRET")
    monkeypatch.setenv("EVA_LOCAL_ENABLED", "true")
    monkeypatch.setenv("EVA_LOCAL_A_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("EVA_LOCAL_A_MODEL", "m")
    blob = str(providers.eva_local_status())
    for secret in ("gsk_SECRET", "sk_SECRET", "eva-local", "Authorization", "Bearer"):
        assert secret not in blob


def test_eva_local_status_makes_no_network_call(monkeypatch):
    """It reports config only — no probe, so a broken HTTP stack cannot affect it."""
    _clear_eva_env(monkeypatch)
    monkeypatch.setenv("EVA_LOCAL_ENABLED", "true")
    monkeypatch.setenv("EVA_LOCAL_A_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("EVA_LOCAL_A_MODEL", "m")
    boom = types.ModuleType("openai")

    def _explode(*a, **k):
        raise AssertionError("eva_local_status must not open a client")

    boom.OpenAI = _explode
    monkeypatch.setitem(sys.modules, "openai", boom)
    assert providers.eva_local_status()["selected_machine"] == "A"

# ── EVA Server Local runtime health recording (Phase 2 Step 12) ──────────────
def _eva_env(monkeypatch, model="cfg-model-1"):
    _clear_eva_env(monkeypatch)
    monkeypatch.setenv("EVA_LOCAL_ENABLED", "true")
    monkeypatch.setenv("EVA_LOCAL_A_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("EVA_LOCAL_A_MODEL", model)


def _eva_health():
    return providers.eva_local_health()


def test_eva_local_success_is_recorded(monkeypatch):
    _eva_env(monkeypatch)
    captured = {}
    monkeypatch.setitem(sys.modules, "openai", _fake_openai_module(captured, "an answer"))
    assert providers.dispatch("eva_local", MSG) == "an answer"
    h = _eva_health()
    assert h["requests"] == 1 and h["failures"] == 0
    assert h["last_error_code"] is None
    assert isinstance(h["last_latency_ms"], int)
    assert h["last_success_seconds_ago"] is not None


def test_eva_local_failure_is_recorded_with_a_fixed_enum(monkeypatch):
    _eva_env(monkeypatch)
    mod = types.ModuleType("openai")

    class _Completions:
        def create(self, **k):
            raise RuntimeError("request timed out")

    class _Chat:
        def __init__(self): self.completions = _Completions()

    class _OpenAI:
        def __init__(self, api_key=None, base_url=None, **kw): self.chat = _Chat()

    mod.OpenAI = _OpenAI
    monkeypatch.setitem(sys.modules, "openai", mod)
    with pytest.raises(RuntimeError):
        providers.dispatch("eva_local", MSG)
    h = _eva_health()
    assert h["requests"] == 1 and h["failures"] == 1
    assert h["last_error_code"] == "TIMEOUT"
    assert h["last_error_code"] in providers.ERROR_CODES     # fixed enum, never free text


def test_eva_local_empty_answer_records_empty_response(monkeypatch):
    _eva_env(monkeypatch)
    captured = {}
    monkeypatch.setitem(sys.modules, "openai", _fake_openai_module(captured, "   "))
    providers.dispatch("eva_local", MSG)
    h = _eva_health()
    assert h["failures"] == 1 and h["last_error_code"] == "EMPTY_RESPONSE"


def test_eva_local_config_errors_are_not_counted_as_calls(monkeypatch):
    """A provider that was never contacted must not inflate the failure count."""
    _clear_eva_env(monkeypatch)                       # disabled + unconfigured
    with pytest.raises(RuntimeError):
        providers.dispatch("eva_local", MSG)
    assert _eva_health()["requests"] == 0


def test_eva_local_stream_records_once_on_success(monkeypatch):
    _eva_env(monkeypatch)
    captured = {}
    monkeypatch.setitem(sys.modules, "openai",
                        _fake_openai_streaming_module(captured, ["EVA ", None, "OK"]))
    assert list(providers.stream_eva_local(MSG)) == ["EVA ", "OK"]
    h = _eva_health()
    assert h["requests"] == 1 and h["failures"] == 0
    assert isinstance(h["last_latency_ms"], int)


def test_eva_local_stream_failure_is_recorded(monkeypatch):
    _eva_env(monkeypatch)
    mod = types.ModuleType("openai")

    class _BoomStream:
        def __iter__(self): return self
        def __next__(self): raise RuntimeError("Machine A down mid-stream")

    class _Completions:
        def create(self, **k): return _BoomStream()

    class _Chat:
        def __init__(self): self.completions = _Completions()

    class _OpenAI:
        def __init__(self, api_key=None, base_url=None, **kw): self.chat = _Chat()

    mod.OpenAI = _OpenAI
    monkeypatch.setitem(sys.modules, "openai", mod)
    with pytest.raises(RuntimeError):
        list(providers.stream_eva_local(MSG))
    h = _eva_health()
    assert h["requests"] == 1 and h["failures"] == 1
    assert h["last_error_code"] in providers.ERROR_CODES


def test_eva_local_health_records_no_prompt_or_secret(monkeypatch):
    _eva_env(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "gsk_SECRET")
    captured = {}
    monkeypatch.setitem(sys.modules, "openai", _fake_openai_module(captured, "the answer text"))
    providers.dispatch("eva_local", [{"role": "user", "content": "MY-SECRET-PROMPT"}])
    blob = str(providers.eva_local_status())
    # The validated base_url IS reported on purpose (Step 10); nothing else may leak.
    for leak in ("MY-SECRET-PROMPT", "the answer text", "gsk_SECRET", "eva-local"):
        assert leak not in blob


def test_eva_local_recording_notifies_the_shadow_observer(monkeypatch):
    _eva_env(monkeypatch)
    seen = []
    providers.add_record_observer(lambda pid, ok, code, ms: seen.append((pid, ok, code)))
    try:
        captured = {}
        monkeypatch.setitem(sys.modules, "openai", _fake_openai_module(captured, "ok"))
        providers.dispatch("eva_local", MSG)
    finally:
        providers._record_observers.clear()
    assert seen and seen[0][0] == "eva_local" and seen[0][1] is True


def test_eva_local_recording_does_not_join_the_cloud_order(monkeypatch):
    _eva_env(monkeypatch)
    captured = {}
    monkeypatch.setitem(sys.modules, "openai", _fake_openai_module(captured, "ok"))
    providers.dispatch("eva_local", MSG)
    # The cloud cascade itself is untouched: eva_local is not a member of it and
    # does not appear in the `live` status array, which mirrors PROVIDER_ORDER.
    assert providers.PROVIDER_ORDER == ["groq", "openai", "gemini", "local"]
    assert "eva_local" not in [p["id"] for p in providers.status()]
    # It IS first in the resolved chain now — prepended at call time because it
    # is enabled and a machine resolves. The cloud providers keep their order
    # behind it, so they remain the floor rather than being displaced.
    assert [pid for pid, _ in providers.failover_chain()] == [
        "eva_local", "groq", "openai", "gemini"]


def test_the_cloud_chain_is_unchanged_when_eva_local_is_off(monkeypatch):
    """The guarantee that matters: with the flag off the chain is byte-identical
    to what it was before local-first existed."""
    _clear_eva_env(monkeypatch)
    assert [pid for pid, _ in providers.failover_chain()] == ["groq", "openai", "gemini"]


def test_an_explicit_order_is_never_rewritten(monkeypatch):
    """A caller asking for a specific cascade gets exactly that — local is only
    prepended to the default order."""
    _eva_env(monkeypatch)
    assert [pid for pid, _ in providers.failover_chain(["gemini", "groq"])] == ["gemini", "groq"]


def test_eva_local_leads_the_chain_with_its_resolved_model(monkeypatch):
    """The label comes from the resolved config, not the import-time spec, which
    reads EVA_LOCAL_A_MODEL once and can be stale or empty."""
    _eva_env(monkeypatch, model="live-model-7b")
    chain = providers.failover_chain()
    assert chain[0] == ("eva_local", "live-model-7b")


def test_a_configured_but_unresolvable_machine_does_not_enter_the_chain(monkeypatch):
    """An SSRF-rejected or model-less machine must not be offered as a provider."""
    _clear_eva_env(monkeypatch)
    monkeypatch.setenv("EVA_LOCAL_ENABLED", "true")
    monkeypatch.setenv("EVA_LOCAL_A_URL", "http://8.8.8.8/v1")     # rejected by policy
    monkeypatch.setenv("EVA_LOCAL_A_MODEL", "m")
    assert [pid for pid, _ in providers.failover_chain()] == ["groq", "openai", "gemini"]


def test_eva_local_disabled_records_nothing(monkeypatch):
    _clear_eva_env(monkeypatch)
    monkeypatch.setenv("EVA_LOCAL_A_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("EVA_LOCAL_A_MODEL", "m")      # configured but NOT enabled
    with pytest.raises(RuntimeError):
        providers.dispatch("eva_local", MSG)
    assert _eva_health()["requests"] == 0

# ── EVA Server Local fast-fail breaker ───────────────────────────────────────
# A down machine cost a full connect timeout on every request (~7.9s measured)
# before the cloud cascade ran. These pin the skip, and that the cloud cascade
# behind it is untouched either way.
def _chain():
    return [pid for pid, _ in providers.failover_chain()]


@pytest.mark.parametrize("code", ["ERROR", "TIMEOUT", "MODEL_NOT_FOUND", "AUTH"])
def test_an_availability_failure_trips_the_breaker(monkeypatch, code):
    _eva_env(monkeypatch)
    assert _chain()[0] == "eva_local"
    _fail_machine("A", code=code)
    assert providers._eva_local_tripped("A") is True
    assert "eva_local" not in _chain()


def test_an_empty_response_does_not_trip_the_breaker(monkeypatch):
    """The machine answered, so it is up — just unhelpful. Losing local for a
    bad generation would be the wrong trade."""
    _eva_env(monkeypatch)
    _fail_machine("A", code="EMPTY_RESPONSE")
    assert providers._eva_local_tripped("A") is False
    assert _chain()[0] == "eva_local"


def test_a_tripped_breaker_leaves_the_cloud_cascade_exactly_as_it_was(monkeypatch):
    _eva_env(monkeypatch)
    _fail_machine("A", code="TIMEOUT")
    assert _chain() == ["groq", "openai", "gemini"]      # identical to flag-off


def test_a_tripped_breaker_makes_no_local_client_attempt(monkeypatch):
    """The whole point: no connection attempt, so none of the timeout is paid."""
    _eva_env(monkeypatch)
    _fail_machine("A", code="ERROR")

    exploding = types.ModuleType("openai")

    def _never(*a, **k):
        raise AssertionError("a tripped breaker must not open a local client")

    exploding.OpenAI = _never
    monkeypatch.setitem(sys.modules, "openai", exploding)
    _adapter("groq", out="CLOUD")

    r = providers.complete(MSG)
    assert (r.provider, r.text) == ("groq", "CLOUD")


def test_the_breaker_reads_state_only_and_makes_no_health_ping(monkeypatch):
    """No poller, no probe: the decision is in-memory, so a dead HTTP stack
    cannot affect it."""
    _eva_env(monkeypatch)
    _fail_machine("A", code="TIMEOUT")

    for name in ("httpx", "openai"):
        mod = types.ModuleType(name)
        mod.Client = mod.AsyncClient = mod.OpenAI = lambda *a, **k: (_ for _ in ()).throw(
            AssertionError(f"{name} must not be used by the breaker"))
        monkeypatch.setitem(sys.modules, name, mod)

    assert providers._eva_local_tripped("A") is True
    assert "eva_local" not in _chain()


def test_the_cooldown_lapsing_allows_a_half_open_trial(monkeypatch):
    _eva_env(monkeypatch)
    _fail_machine("A", code="TIMEOUT")
    assert providers._eva_local_tripped("A") is True        # OPEN, still cooling
    monkeypatch.setenv("EVA_LOCAL_HEALTH_COOLDOWN_S", "0")
    assert providers._eva_local_tripped("A") is False       # HALF-OPEN
    assert _chain()[0] == "eva_local"                    # the next request is the trial


def test_a_successful_trial_closes_the_breaker(monkeypatch):
    _eva_env(monkeypatch)
    _fail_machine("A", code="TIMEOUT")
    _heal_machine("A", latency_ms=12)    # the trial answered
    assert providers._eva_local_tripped("A") is False           # CLOSED, cooldown irrelevant
    assert _chain()[0] == "eva_local"


def test_a_failed_trial_reopens_the_breaker(monkeypatch):
    _eva_env(monkeypatch)
    monkeypatch.setenv("EVA_LOCAL_HEALTH_COOLDOWN_S", "0")
    _fail_machine("A", code="TIMEOUT")
    assert providers._eva_local_tripped("A") is False            # HALF-OPEN
    monkeypatch.setenv("EVA_LOCAL_HEALTH_COOLDOWN_S", "30")
    _fail_machine("A", code="TIMEOUT")   # trial failed
    assert providers._eva_local_tripped("A") is True             # OPEN again


def test_the_breaker_does_not_use_the_600s_dashboard_window(monkeypatch):
    """status()'s decay is tuned for a dashboard; routing on it would ignore a
    machine that came back seconds later."""
    _eva_env(monkeypatch)
    monkeypatch.delenv("EVA_LOCAL_HEALTH_COOLDOWN_S", raising=False)
    assert providers._eva_local_cooldown_s() == 30.0
    monkeypatch.setenv("EVA_LOCAL_HEALTH_COOLDOWN_S", "5")
    assert providers._eva_local_cooldown_s() == 5.0
    for bad in ("", "not-a-number"):
        monkeypatch.setenv("EVA_LOCAL_HEALTH_COOLDOWN_S", bad)
        assert providers._eva_local_cooldown_s() == 30.0


def test_the_breaker_is_inert_when_eva_local_is_disabled(monkeypatch):
    _clear_eva_env(monkeypatch)
    _fail_machine("A", code="TIMEOUT")
    assert _chain() == ["groq", "openai", "gemini"]


def test_a_tripped_breaker_never_rewrites_an_explicit_order(monkeypatch):
    _eva_env(monkeypatch)
    _fail_machine("A", code="TIMEOUT")
    assert [pid for pid, _ in providers.failover_chain(["gemini", "groq"])] == ["gemini", "groq"]


def test_the_breaker_preserves_telemetry(monkeypatch):
    """Trips are recorded like any other outcome — the counters keep counting."""
    _eva_env(monkeypatch)
    _fail_machine("A", code="TIMEOUT", latency_ms=7900)
    health = providers.eva_local_status()["health"]
    assert health["requests"] == 1 and health["failures"] == 1
    assert health["last_error_code"] == "TIMEOUT"
    assert health["last_latency_ms"] == 7900

def test_a_tripped_breaker_makes_the_provider_unavailable_everywhere(monkeypatch):
    """The chat fallback and the streaming branch ask configured(), not
    failover_chain(). Production-path verification caught them still dialling a
    known-down machine because the breaker lived only in the chain; the gate is
    in configured() so every caller gets the same answer."""
    _eva_env(monkeypatch)
    assert providers.configured("eva_local") is True
    _fail_machine("A", code="ERROR")
    assert providers.configured("eva_local") is False        # the chat guard now skips
    assert "eva_local" not in _chain()                       # and so does the chain


def test_availability_recovers_when_the_breaker_closes(monkeypatch):
    _eva_env(monkeypatch)
    _fail_machine("A", code="TIMEOUT")
    assert providers.configured("eva_local") is False
    _heal_machine("A", latency_ms=9)
    assert providers.configured("eva_local") is True


def test_status_separates_being_configured_from_being_usable(monkeypatch):
    """`available` means usable right now; the per-machine `configured` flag
    still reports that the operator set it up."""
    _eva_env(monkeypatch)
    _fail_machine("A", code="ERROR")
    st = providers.eva_local_status()
    assert st["available"] is False                          # not usable
    assert st["machines"][0]["configured"] is True           # but still configured
    assert st["enabled"] is True

# ── the local generation budget is capped (Local Production Readiness) ───────
def test_local_generation_budget_is_capped(monkeypatch):
    """A 3B model generates at ~60 tok/s, so the chat path's 1024-token ceiling
    is ~17s of pure generation. Local gets a lower one."""
    _eva_env(monkeypatch)
    captured = {}
    monkeypatch.setitem(sys.modules, "openai", _fake_openai_module(captured, "ok"))
    providers.dispatch("eva_local", MSG, max_tokens=1024)
    assert captured["max_tokens"] == 512


def test_a_smaller_caller_budget_still_wins(monkeypatch):
    """It is a cap, not a target: asking for less must still get less."""
    _eva_env(monkeypatch)
    captured = {}
    monkeypatch.setitem(sys.modules, "openai", _fake_openai_module(captured, "ok"))
    providers.dispatch("eva_local", MSG, max_tokens=64)
    assert captured["max_tokens"] == 64


def test_the_local_cap_is_configurable(monkeypatch):
    _eva_env(monkeypatch)
    monkeypatch.setenv("EVA_LOCAL_MAX_TOKENS", "200")
    assert providers._eva_local_max_tokens() == 200
    for bad in ("", "lots"):
        monkeypatch.setenv("EVA_LOCAL_MAX_TOKENS", bad)
        assert providers._eva_local_max_tokens() == 512


def test_the_cap_applies_to_streaming_too(monkeypatch):
    _eva_env(monkeypatch)
    captured = {}
    monkeypatch.setitem(sys.modules, "openai",
                        _fake_openai_streaming_module(captured, ["ok"]))
    list(providers.stream_eva_local(MSG, max_tokens=1024))
    assert captured["max_tokens"] == 512


def test_the_cap_does_not_touch_cloud_providers(monkeypatch):
    captured = {}
    _install_fake_module(monkeypatch, "groq", "Groq", _openai_style_client(captured))
    providers._call_groq(MSG, "m", 1024, None)
    assert captured["max_tokens"] == 1024

def _fail_machine(machine="A", code="ERROR", latency_ms=None):
    """Record an availability failure exactly as a real call would: against the
    machine (routing state) and against the provider (telemetry)."""
    providers._record_health(providers._eva_local_machine_key(machine),
                             ok=False, code=code, latency_ms=latency_ms)
    providers.record("eva_local", ok=False, code=code, latency_ms=latency_ms)


def _heal_machine(machine="A", latency_ms=5):
    providers._record_health(providers._eva_local_machine_key(machine),
                             ok=True, latency_ms=latency_ms)
    providers.record("eva_local", ok=True, latency_ms=latency_ms)


def _eva_env_ab(monkeypatch, a="http://127.0.0.1:11434/v1", b="http://192.168.1.20:11434/v1"):
    """Both machines configured, so A->B routing is observable."""
    _clear_eva_env(monkeypatch)
    monkeypatch.setenv("EVA_LOCAL_ENABLED", "true")
    monkeypatch.setenv("EVA_LOCAL_A_URL", a)
    monkeypatch.setenv("EVA_LOCAL_A_MODEL", "model-a")
    monkeypatch.setenv("EVA_LOCAL_B_URL", b)
    monkeypatch.setenv("EVA_LOCAL_B_MODEL", "model-b")


# ── Machine A -> B failover ──────────────────────────────────────────────────
def test_machine_a_is_preferred_while_healthy(monkeypatch):
    _eva_env_ab(monkeypatch)
    assert providers.eva_local_resolve()["machine"] == "A"


def test_machine_b_takes_over_when_a_is_down(monkeypatch):
    """The whole point of two machines: a down A must not take local with it."""
    _eva_env_ab(monkeypatch)
    _fail_machine("A")
    cfg = providers.eva_local_resolve()
    assert cfg["machine"] == "B" and cfg["model"] == "model-b"
    assert providers.configured("eva_local") is True        # local still serves
    assert [pid for pid, _ in providers.failover_chain()][0] == "eva_local"


def test_cloud_takes_over_only_when_both_machines_are_down(monkeypatch):
    _eva_env_ab(monkeypatch)
    _fail_machine("A")
    _fail_machine("B")
    assert providers.eva_local_resolve() is None
    assert providers.configured("eva_local") is False
    assert [pid for pid, _ in providers.failover_chain()] == ["groq", "openai", "gemini"]


def test_machine_a_is_preferred_again_once_it_recovers(monkeypatch):
    _eva_env_ab(monkeypatch)
    _fail_machine("A")
    assert providers.eva_local_resolve()["machine"] == "B"
    _heal_machine("A")
    assert providers.eva_local_resolve()["machine"] == "A"


def test_one_machines_failure_does_not_trip_the_other(monkeypatch):
    _eva_env_ab(monkeypatch)
    _fail_machine("A")
    assert providers._eva_local_tripped("A") is True
    assert providers._eva_local_tripped("B") is False


def test_machine_b_is_never_invented_when_only_a_is_configured(monkeypatch):
    _eva_env(monkeypatch)                                   # A only
    assert [c["machine"] for c in providers.eva_local_candidates()] == ["A"]
    _fail_machine("A")
    assert providers.eva_local_resolve() is None             # no phantom B
    assert providers.configured("eva_local") is False


def test_b_alone_is_a_valid_deployment(monkeypatch):
    _clear_eva_env(monkeypatch)
    monkeypatch.setenv("EVA_LOCAL_ENABLED", "true")
    monkeypatch.setenv("EVA_LOCAL_B_URL", "http://192.168.1.20:11434/v1")
    monkeypatch.setenv("EVA_LOCAL_B_MODEL", "model-b")
    assert providers.eva_local_resolve()["machine"] == "B"


def test_a_failing_machine_hands_the_same_request_to_the_next(monkeypatch):
    """In-request failover: A raising must not cost the user their answer when B
    is available."""
    _eva_env_ab(monkeypatch)
    seen = []

    def fake_machine(cfg, messages, max_tokens, temperature):
        seen.append(cfg["machine"])
        if cfg["machine"] == "A":
            raise RuntimeError("connection refused")
        return "ANSWER FROM B"

    monkeypatch.setattr(providers, "_call_eva_local_machine", fake_machine)
    assert providers.dispatch("eva_local", MSG) == "ANSWER FROM B"
    assert seen == ["A", "B"]                                # A tried first, then B


def test_every_machine_failing_raises_so_cloud_can_take_over(monkeypatch):
    _eva_env_ab(monkeypatch)
    monkeypatch.setattr(providers, "_call_eva_local_machine",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    with pytest.raises(RuntimeError):
        providers.dispatch("eva_local", MSG)


def test_status_reports_each_machine_separately(monkeypatch):
    """A dashboard must be able to tell "A is down, B is carrying it" from
    "both are fine"."""
    _eva_env_ab(monkeypatch)
    _fail_machine("A", code="TIMEOUT")
    by = {m["machine"]: m for m in providers.eva_local_status()["machines"]}
    assert by["A"]["skipped_now"] is True and by["A"]["health"]["last_error_code"] == "TIMEOUT"
    assert by["B"]["skipped_now"] is False and by["B"]["health"]["requests"] == 0
    assert providers.eva_local_status()["selected_machine"] == "B"


def test_per_machine_state_is_not_announced_as_a_provider(monkeypatch):
    """The shadow's provider vocabulary is a fixed enum; machine keys are routing
    state and must not reach an observer as if a new provider had appeared."""
    _eva_env_ab(monkeypatch)
    seen = []
    providers.add_record_observer(lambda pid, ok, code, ms: seen.append(pid))
    try:
        providers._record_health(providers._eva_local_machine_key("A"), ok=False, code="ERROR")
        assert seen == []                                    # nothing announced
        providers.record("eva_local", ok=False, code="ERROR")
        assert seen == ["eva_local"]                         # only the provider is
    finally:
        providers._record_observers.clear()

# ── the Gemini leg calls a model that exists ─────────────────────────────────
def test_the_gemini_default_is_not_the_retired_model():
    """gemini-3.5-flash was retired: pinning it made every Gemini call return
    MODEL_NOT_FOUND, which silently removed the last leg of the cloud cascade."""
    assert providers.PROVIDER_SPECS["gemini"]["model"] != "gemini-3.5-flash"


def test_the_gemini_model_is_operator_overridable(monkeypatch):
    """Config-driven, so the next retirement is an env change and not a deploy."""
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash")
    import importlib
    reloaded = importlib.reload(providers)
    try:
        assert reloaded.PROVIDER_SPECS["gemini"]["model"] == "gemini-3.5-flash"
    finally:
        monkeypatch.delenv("GEMINI_MODEL", raising=False)
        importlib.reload(providers)


def test_an_unset_or_blank_gemini_model_still_resolves(monkeypatch):
    """The default has to be live too: Render may set nothing at all."""
    import importlib
    for value in ("", "   "):
        monkeypatch.setenv("GEMINI_MODEL", value)
        reloaded = importlib.reload(providers)
        assert reloaded.PROVIDER_SPECS["gemini"]["model"] == "gemini-2.5-flash"
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    importlib.reload(providers)


def test_the_other_cloud_models_are_untouched():
    """The retirement fix must not drift groq/openai, which still answer."""
    assert providers.PROVIDER_SPECS["groq"]["model"] == "openai/gpt-oss-120b"
    assert providers.PROVIDER_SPECS["openai"]["model"] == "gpt-4o-mini"

# ── a down machine must be cheap to discover ─────────────────────────────────
def test_the_local_client_does_not_retry_internally():
    """A -> B -> cloud IS the retry policy. The SDK's 2 internal retries only
    multiplied the time spent inside a machine that is already down."""
    assert providers._eva_local_client("http://127.0.0.1:11499/v1").max_retries == 0


def test_connect_is_capped_but_generation_is_not():
    """Connect is the only phase that should be short: a local model can take
    minutes to generate, so clamping the whole request would abort real answers."""
    t = providers._eva_local_client("http://127.0.0.1:11499/v1").timeout
    assert t.connect == 2.0
    assert t.read >= 600.0 and t.write >= 600.0


def test_the_timeouts_are_operator_tunable(monkeypatch):
    monkeypatch.setenv("EVA_LOCAL_CONNECT_TIMEOUT_S", "0.5")
    monkeypatch.setenv("EVA_LOCAL_REQUEST_TIMEOUT_S", "120")
    t = providers._eva_local_client("http://127.0.0.1:11499/v1").timeout
    assert t.connect == 0.5 and t.read == 120.0


@pytest.mark.parametrize("bad", ["", "   ", "soon", "-1"])
def test_a_bad_timeout_falls_back_instead_of_disabling_the_cap(monkeypatch, bad):
    """A typo must not silently restore the 10s-per-dead-machine behaviour."""
    monkeypatch.setenv("EVA_LOCAL_CONNECT_TIMEOUT_S", bad)
    assert 0 < providers._eva_local_connect_timeout_s() <= 2.0


def test_both_local_paths_share_one_client_factory(monkeypatch):
    """Blocking and streaming must not drift apart on timeouts."""
    _eva_env(monkeypatch)
    seen = []
    real = providers._eva_local_client
    monkeypatch.setattr(providers, "_eva_local_client",
                        lambda url: (seen.append(url), real(url))[1])
    for call in (lambda: providers.dispatch("eva_local", MSG, max_tokens=8),
                 lambda: list(providers.stream_eva_local(MSG, max_tokens=8))):
        with providers._health_lock:
            providers._health.clear()   # else the first failure trips the machine
        try:
            call()
        except Exception:
            pass                      # nothing is listening; we want the factory call
    assert len(seen) == 2 and seen[0] == seen[1]


def test_the_cloud_clients_keep_their_own_retry_policy(monkeypatch):
    """The local cap must not leak into providers that are remote by nature."""
    captured = {}
    Client = _openai_style_client(captured)
    _install_fake_module(monkeypatch, "openai", "OpenAI", Client)
    providers._call_openai(MSG, "gpt-4o-mini", 16, None)
    assert "max_retries" not in Client.last_kwargs
    assert "timeout" not in Client.last_kwargs
