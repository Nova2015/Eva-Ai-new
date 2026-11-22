"""Phase 2 Step 14 — the backend's read-only eva_local registry reader.

No network: httpx is faked in-process. The properties that matter are that a
registry value WINS over env, that every failure path degrades to {} (and so to
the env bootstrap), that the cache holds for its TTL, and that a row in the
database can never bypass the SSRF policy.
"""

import sys
import types

import pytest

try:
    import eva_local_registry as reg
    import providers
except ImportError:  # running from the repo root
    from src import eva_local_registry as reg  # type: ignore
    from src import providers  # type: ignore


class _Resp:
    def __init__(self, status_code=200, payload=None, raise_json=False):
        self.status_code = status_code
        self._payload = payload
        self._raise = raise_json

    def json(self):
        if self._raise:
            raise ValueError("malformed")
        return self._payload


def _fake_httpx(monkeypatch, resp, captured=None):
    mod = types.ModuleType("httpx")

    class _Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False

        def get(self, url, headers=None, params=None):
            if captured is not None:
                captured.update({"url": url, "headers": headers or {}, "params": params or {}})
            if isinstance(resp, Exception):
                raise resp
            return resp

    mod.Client = _Client
    monkeypatch.setitem(sys.modules, "httpx", mod)


BLOCK = {"runtime": "ollama",
         "machines": {"A": {"base_url": "http://192.168.1.9:8000/v1", "model": "registry-model"}}}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "SUPER-SECRET-KEY")
    reg.invalidate()
    yield
    reg.invalidate()
    providers.set_eva_local_registry_reader(None)


# ── reading the active version ───────────────────────────────────────────────
def test_reads_the_active_versions_eva_local_block(monkeypatch):
    captured = {}
    _fake_httpx(monkeypatch, _Resp(200, [{"version": 7, "config": {"eva_local": BLOCK}}]), captured)
    assert reg.fetch_active_eva_local() == BLOCK
    # asks for exactly the ACTIVE row, newest first, one row
    assert captured["url"].endswith("/rest/v1/model_config_versions")
    assert captured["params"]["status"] == "eq.ACTIVE"
    assert captured["params"]["order"] == "version.desc"
    assert captured["params"]["limit"] == "1"


@pytest.mark.parametrize("payload", [
    [],                                             # no active version
    [{"version": 7, "config": {}}],                 # active version without the block
    [{"version": 7, "config": {"eva_local": None}}],
    [{"version": 7, "config": {"eva_local": "nope"}}],
    [{"version": 7, "config": "not-a-dict"}],
    {"unexpected": "shape"},
])
def test_every_missing_or_odd_shape_degrades_to_empty(monkeypatch, payload):
    _fake_httpx(monkeypatch, _Resp(200, payload))
    assert reg.fetch_active_eva_local() == {}


def test_http_error_and_transport_error_degrade_to_empty(monkeypatch):
    _fake_httpx(monkeypatch, _Resp(500, None))
    assert reg.fetch_active_eva_local() == {}
    _fake_httpx(monkeypatch, _Resp(200, None, raise_json=True))
    assert reg.fetch_active_eva_local() == {}
    _fake_httpx(monkeypatch, RuntimeError("connection refused"))
    assert reg.fetch_active_eva_local() == {}


def test_without_credentials_nothing_is_fetched(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    _fake_httpx(monkeypatch, RuntimeError("must not be called"))
    assert reg.fetch_active_eva_local() == {}       # no creds -> no request at all


# ── caching ──────────────────────────────────────────────────────────────────
def test_the_read_is_cached_for_its_ttl(monkeypatch):
    calls = []

    def counting():
        calls.append(1)
        return BLOCK

    monkeypatch.setattr(reg, "fetch_active_eva_local", counting)
    assert reg.read() == BLOCK
    assert reg.read() == BLOCK
    assert len(calls) == 1                          # second read served from cache
    reg.invalidate()
    assert reg.read() == BLOCK
    assert len(calls) == 2


def test_a_zero_ttl_disables_the_cache(monkeypatch):
    calls = []
    monkeypatch.setenv("EVA_LOCAL_REGISTRY_TTL_S", "0")
    monkeypatch.setattr(reg, "fetch_active_eva_local", lambda: calls.append(1) or BLOCK)
    reg.read(); reg.read()
    assert len(calls) == 2


# ── the reader never leaks the Supabase key ──────────────────────────────────
def test_the_supabase_key_is_never_in_the_result(monkeypatch):
    _fake_httpx(monkeypatch, _Resp(200, [{"version": 7, "config": {"eva_local": BLOCK}}]))
    assert "SUPER-SECRET-KEY" not in str(reg.read())


# ── integration with providers.eva_local_resolve ─────────────────────────────
def _env_a(monkeypatch):
    for k in ("EVA_LOCAL_A_URL", "EVA_LOCAL_A_MODEL", "EVA_LOCAL_B_URL", "EVA_LOCAL_B_MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("EVA_LOCAL_ENABLED", "true")
    monkeypatch.setenv("EVA_LOCAL_A_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("EVA_LOCAL_A_MODEL", "env-model")


def test_registry_wins_over_env(monkeypatch):
    _env_a(monkeypatch)
    providers.set_eva_local_registry_reader(lambda: BLOCK)
    cfg = providers.eva_local_resolve()
    assert cfg["base_url"] == "http://192.168.1.9:8000/v1"
    assert cfg["model"] == "registry-model"


def test_env_is_used_when_the_registry_is_empty_or_broken(monkeypatch):
    _env_a(monkeypatch)
    for reader in (lambda: {}, lambda: None, lambda: "junk",
                   lambda: (_ for _ in ()).throw(RuntimeError("registry down"))):
        providers.set_eva_local_registry_reader(reader)
        cfg = providers.eva_local_resolve()
        assert cfg["base_url"] == "http://127.0.0.1:11434/v1"
        assert cfg["model"] == "env-model"


def test_no_reader_injected_is_todays_behaviour(monkeypatch):
    _env_a(monkeypatch)
    providers.set_eva_local_registry_reader(None)
    assert providers.eva_local_resolve()["model"] == "env-model"


def test_a_registry_row_cannot_bypass_the_ssrf_policy(monkeypatch):
    _env_a(monkeypatch)
    for bad in ("http://8.8.8.8/v1", "http://169.254.169.254/v1",
                "ftp://192.168.1.9", "http://u:p@192.168.1.9/v1"):
        providers.set_eva_local_registry_reader(
            lambda bad=bad: {"machines": {"A": {"base_url": bad, "model": "m"}}})
        # A registry-supplied machine that fails validation is skipped, never used.
        cfg = providers.eva_local_resolve()
        assert cfg is None or cfg["base_url"] != bad


def test_registry_machine_b_is_recognised_and_absent_b_is_not_invented(monkeypatch):
    _env_a(monkeypatch)
    # A + B in the registry: A is still preferred.
    providers.set_eva_local_registry_reader(lambda: {"machines": {
        "A": {"base_url": "http://192.168.1.9:8000/v1", "model": "ma"},
        "B": {"base_url": "http://192.168.1.20:8000/v1", "model": "mb"}}})
    assert providers.eva_local_resolve()["machine"] == "A"

    # B only in the registry, and no env for either: B is used, not invented away.
    monkeypatch.delenv("EVA_LOCAL_A_URL", raising=False)
    monkeypatch.delenv("EVA_LOCAL_A_MODEL", raising=False)
    providers.set_eva_local_registry_reader(lambda: {"machines": {
        "B": {"base_url": "http://192.168.1.20:8000/v1", "model": "mb"}}})
    cfg = providers.eva_local_resolve()
    assert cfg["machine"] == "B" and cfg["model"] == "mb"

    # Registry names no machine at all and there is no env: nothing is invented.
    providers.set_eva_local_registry_reader(lambda: {"machines": {}})
    assert providers.eva_local_resolve() is None


def test_providers_still_has_no_storage_import():
    """providers.py documents that it carries no storage dependency; Step 14
    keeps it that way by injecting the reader instead of importing it."""
    import inspect
    src = inspect.getsource(providers)
    assert "import eva_local_registry" not in src      # injected, never imported
    assert "SUPABASE_URL" not in src                    # no credentials read here
    assert "rest/v1" not in src                         # and no storage calls
