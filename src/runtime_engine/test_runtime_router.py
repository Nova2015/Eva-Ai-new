"""STEP 5 tests for the runtime router mount + consolidated execute + health.

Piston is always mocked here — no network, fully offline. These tests target
the SRC copy of runtime_engine (the one src.app imports), so we prepend src/ to
sys.path before importing (the repo conftest only wires backend/runtime_engine).
"""

import os
import sys

_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../src
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)  # ensure `import runtime_engine` / `import app` = src copies

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import runtime_engine
from runtime_engine.runtime_models import (
    make_result, STATUS_SUCCESS, STATUS_UNKNOWN,
)


def _bare_client():
    """A minimal app with ONLY the runtime router mounted (dep-light)."""
    app = FastAPI()
    try:  # mirror app.py: register the shared limiter, but disable it offline
        from rate_limit import limiter
        limiter.enabled = False
        app.state.limiter = limiter
    except Exception:
        pass
    app.include_router(runtime_engine.router)
    return TestClient(app)


# ── router exports & mounts ───────────────────────────────────────────────────
def test_runtime_engine_exports_router():
    # The exact bug that started this: `runtime_engine.router` must exist.
    assert hasattr(runtime_engine, "router"), "runtime_engine must export `router`"


def test_router_registers_runtime_routes():
    app = FastAPI()
    app.include_router(runtime_engine.router)
    paths = {r.path for r in app.routes}
    assert "/runtime/execute" in paths
    assert "/runtime/health" in paths


# ── /runtime/execute reaches Piston (mocked) → SUCCESS ────────────────────────
def test_execute_success(monkeypatch):
    monkeypatch.setenv("EVA_ENABLE_RUNTIME_EXECUTION", "true")

    async def fake_run_on_piston(lang, code, stdin=""):
        return make_result(STATUS_SUCCESS, lang, stdout="hi\n", exit_code=0, execution_ms=12)

    monkeypatch.setattr("runtime_engine.execution_service.run_on_piston", fake_run_on_piston)

    r = _bare_client().post("/runtime/execute", json={"language": "python", "code": "print('hi')"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == STATUS_SUCCESS
    assert body["runtime_source"] == "piston"
    assert body["stdout"] == "hi\n"


# ── Piston 503 → UNKNOWN, HTTP 200, no raise ──────────────────────────────────
def test_execute_piston_503_maps_to_unknown_200(monkeypatch):
    monkeypatch.setenv("EVA_ENABLE_RUNTIME_EXECUTION", "true")

    async def fake_503(lang, code, stdin=""):
        # The adapter is no-raise: a 503 comes back as an UNKNOWN result.
        return make_result(STATUS_UNKNOWN, lang, error="piston returned HTTP 503")

    monkeypatch.setattr("runtime_engine.execution_service.run_on_piston", fake_503)

    r = _bare_client().post("/runtime/execute", json={"language": "python", "code": "print('hi')"})
    assert r.status_code == 200          # never raises to the client
    body = r.json()
    assert body["status"] == STATUS_UNKNOWN
    assert body["error"]                 # UNKNOWN carries the provider reason


def test_execute_adapter_exception_still_unknown_200(monkeypatch):
    monkeypatch.setenv("EVA_ENABLE_RUNTIME_EXECUTION", "true")

    async def boom(lang, code, stdin=""):
        raise ConnectionError("piston unreachable")

    monkeypatch.setattr("runtime_engine.execution_service.run_on_piston", boom)

    r = _bare_client().post("/runtime/execute", json={"language": "python", "code": "print('hi')"})
    assert r.status_code == 200
    assert r.json()["status"] == STATUS_UNKNOWN


# ── gating: disabled → 403, Piston never contacted ────────────────────────────
def test_execute_disabled_returns_403(monkeypatch):
    monkeypatch.setenv("EVA_ENABLE_RUNTIME_EXECUTION", "false")

    async def must_not_call(lang, code, stdin=""):  # pragma: no cover
        raise AssertionError("Piston must not be contacted when disabled")

    monkeypatch.setattr("runtime_engine.execution_service.run_on_piston", must_not_call)

    r = _bare_client().post("/runtime/execute", json={"language": "python", "code": "print('hi')"})
    assert r.status_code == 403


# ── /runtime/health reflects the env flag, no fabricated metrics ──────────────
def test_health_enabled(monkeypatch):
    monkeypatch.setenv("EVA_ENABLE_RUNTIME_EXECUTION", "true")
    body = _bare_client().get("/runtime/health").json()
    assert body == {"status": "ok", "runtime_enabled": True, "provider": "piston"}


def test_health_disabled(monkeypatch):
    monkeypatch.setenv("EVA_ENABLE_RUNTIME_EXECUTION", "false")
    body = _bare_client().get("/runtime/health").json()
    assert body["runtime_enabled"] is False
    assert body["provider"] == "piston"
    # honest health: no persistence-backed metrics
    for k in ("avg_runtime_ms", "success_rate", "timeout_count"):
        assert k not in body


# ── the real app mounts /runtime and has NO legacy /execute ───────────────────
# This is the assertion for the bug that started this. Requires app.py's deps;
# skips (loudly) only if the environment can't import the 8k-line app at all.
def test_real_app_mounts_runtime_and_has_no_legacy_execute():
    try:
        import app as eva_app
    except Exception as e:  # pragma: no cover - environment missing app deps
        pytest.skip(f"src.app import unavailable in this env: {type(e).__name__}: {e}")
    paths = {getattr(r, "path", None) for r in eva_app.app.routes}
    assert "/runtime/execute" in paths, "runtime router did not mount on the real app"
    assert "/runtime/health" in paths
    assert "/execute" not in paths, "legacy /execute route must not exist"
