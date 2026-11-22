"""Tests for /api/health/providers and the record->shadow observer — JARVIS 2A.

The shadow persists per-provider health without changing any answer, so the
first thing to assert is that the observer is actually wired to providers.record
and that recording only ever puts enums, counts and latency buckets into the
buffer — never a prompt or a key. The endpoint then exposes the live in-memory
status alongside the durable summary.
"""

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


def _call(app_module, **kw):
    import asyncio
    return asyncio.run(app_module.api_health_providers(**kw))


# ── A: available and observe-only ────────────────────────────────────────────
def test_the_module_is_wired_in(app_module):
    assert app_module.PROVIDER_SHADOW_AVAILABLE is True


def test_the_endpoint_declares_it_is_not_acting(app_module):
    assert _call(app_module)["acting_on_provider_health"] is False


# ── B: the observer turns a recorded call into a shadow bucket ───────────────
def test_recording_a_provider_call_feeds_the_shadow(app_module):
    app_module._provider_buffer.clear()
    app_module.providers.record("groq", ok=True, latency_ms=350)
    rows = app_module._provider_take()
    assert len(rows) == 1
    r = rows[0]
    assert (r["service"], r["provider"], r["outcome"], r["latency_bucket"]) == (
        "backend", "groq", "ok", "lt_500")
    app_module._provider_buffer.clear()


def test_a_failure_records_its_error_code_as_the_outcome(app_module):
    app_module._provider_buffer.clear()
    app_module.providers.record("gemini", ok=False, code="RATE_LIMITED", latency_ms=1200)
    rows = app_module._provider_take()
    assert rows[0]["outcome"] == "RATE_LIMITED"
    assert rows[0]["latency_bucket"] == "lt_2000"
    app_module._provider_buffer.clear()


def test_a_failure_with_no_code_falls_back_to_error(app_module):
    app_module._provider_buffer.clear()
    app_module.providers.record("openai", ok=False, code=None, latency_ms=None)
    rows = app_module._provider_take()
    assert rows[0]["outcome"] == "ERROR"
    assert rows[0]["latency_bucket"] == "unknown"
    app_module._provider_buffer.clear()


def test_only_labels_reach_the_buffer_never_a_prompt(app_module):
    app_module._provider_buffer.clear()
    # record() takes no text at all, but prove the stored keys are pure enums.
    app_module.providers.record("groq", ok=True, latency_ms=100)
    for key in app_module._provider_buffer:
        parts = key.split("|")
        assert parts[1] == "backend" and parts[2] == "groq" and parts[3] == "ok"
    app_module._provider_buffer.clear()


# ── C: the endpoint exposes live + durable, and leaks nothing ────────────────
def test_the_endpoint_returns_live_and_observed(app_module):
    out = _call(app_module)
    assert "live" in out and isinstance(out["live"], list)
    assert "observed" in out
    assert "persistence" in out


def test_the_supabase_key_never_appears(app_module, monkeypatch):
    secret = "sb-provider-secret-1234567890"
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", secret)
    blob = repr(_call(app_module))
    assert secret not in blob and secret[:10] not in blob


def test_no_data_reads_as_not_configured_not_a_finding(app_module, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    out = _call(app_module)
    assert out["persistence"]["read"] == "not_configured"
    assert out["observed"].get("healthiest_provider") is None


@pytest.mark.parametrize("asked,expected", [(1, 1), (30, 30), (0, 1), (-3, 1), (9999, 365)])
def test_the_window_is_clamped(app_module, asked, expected):
    assert _call(app_module, days=asked)["window_days"] == expected


# ── D: the three shadows stay separate ───────────────────────────────────────
def test_provider_shadow_writes_its_own_table(app_module):
    assert app_module.PROVIDER_TABLE == "provider_shadow_daily"
    assert app_module.PROVIDER_TABLE != app_module.MODE_TABLE
    assert app_module.PROVIDER_TABLE != app_module.ROUTING_TABLE
