"""Tests for /api/health/firewall and the durable shadow buffer.

This endpoint exists to answer one question with evidence: is it safe to set
ENFORCE_FIREWALL to True. So the properties that matter are that it never
overstates what is known, and that it never leaks what it is counting.
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
    return asyncio.run(app_module.api_health_firewall(**kw))


# ── A: it must not arm anything ──────────────────────────────────────────────
def test_reading_the_endpoint_does_not_change_enforcement(app_module):
    before = app_module.SECURITY_CONFIG.get("ENFORCE_FIREWALL", False)
    _call(app_module)
    assert app_module.SECURITY_CONFIG.get("ENFORCE_FIREWALL", False) is before


def test_enforcement_is_reported_not_assumed(app_module):
    out = _call(app_module)
    assert out["enforcing"] == bool(
        app_module.SECURITY_CONFIG.get("ENFORCE_FIREWALL", False))


# ── B: it must not leak what it counts ───────────────────────────────────────
def test_the_payload_carries_no_free_text_from_a_verdict(app_module):
    """Unauthenticated endpoint. Every string in it should be a reason code, a
    fixed status word, or a date."""
    blob = repr(_call(app_module))
    for forbidden in ("prompt", "answer", "message", "detail", "@", "http://",
                      "supabase.co"):
        assert forbidden not in blob.lower(), f"leaked {forbidden!r}"


def test_a_supabase_error_is_reported_as_a_code_not_a_message(app_module, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project-ref.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "service-role-key-not-real")
    out = _call(app_module)
    read = out["persistence"]["read"]
    assert " " not in read, f"read status looks like prose: {read!r}"
    assert "supabase" not in read.lower()


def test_the_key_never_appears_in_the_payload(app_module, monkeypatch):
    secret = "sb-secret-DO-NOT-LEAK-0987654321"
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", secret)
    blob = repr(_call(app_module))
    assert secret not in blob
    assert secret[:10] not in blob


# ── C: absence of data must not read as a safe result ────────────────────────
def test_no_data_gives_a_null_block_rate_not_zero(app_module, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    out = _call(app_module)
    assert out["persisted"]["block_rate"] is None
    assert out["persisted"]["inspected"] == 0


def test_unconfigured_storage_is_visible(app_module, monkeypatch):
    """"Nothing was blocked" and "nothing was ever written" must be
    distinguishable, or the firewall gets armed on the strength of no data."""
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    out = _call(app_module)
    assert out["persistence"]["configured"] is False
    assert out["persistence"]["read"] == "not_configured"


def test_days_observed_is_reported(app_module):
    assert "days_observed" in _call(app_module)["persisted"]


# ── D: the window ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("asked,expected", [(1, 1), (30, 30), (0, 1),
                                            (-5, 1), (9999, 365)])
def test_the_window_is_clamped(app_module, asked, expected):
    assert _call(app_module, days=asked)["window_days"] == expected


# ── E: buffering ─────────────────────────────────────────────────────────────
def test_recording_buffers_without_network(app_module):
    app_module._shadow_buffer.clear()
    app_module._shadow_record("APPROVED", False)
    app_module._shadow_record("HALLUCINATION", True)
    assert len(app_module._shadow_buffer) == 2
    app_module._shadow_buffer.clear()


def test_an_unknown_reason_code_never_enters_the_buffer(app_module):
    app_module._shadow_buffer.clear()
    app_module._shadow_record("something the model said", True)
    assert app_module._shadow_buffer == {}


def test_draining_empties_the_buffer_exactly_once(app_module):
    """Counts must not be sent twice; a doubled count would understate the
    block rate as much as a lost one overstates it."""
    app_module._shadow_buffer.clear()
    app_module._shadow_record("APPROVED", False)
    first = app_module._shadow_take()
    second = app_module._shadow_take()
    assert len(first) == 1
    assert second == []


def test_the_flush_timer_does_not_fire_twice_in_a_row(app_module):
    app_module._shadow_last_flush[0] = 0.0
    assert app_module._shadow_flush_due() is True
    assert app_module._shadow_flush_due() is False


def test_pending_counts_are_visible_before_they_are_written(app_module):
    app_module._shadow_buffer.clear()
    app_module._shadow_record("APPROVED", False)
    assert _call(app_module)["persistence"]["pending_unflushed"] >= 1
    app_module._shadow_buffer.clear()
