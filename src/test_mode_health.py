"""Tests for /api/health/mode_shadow and the _mode_record hook — Update 37.

The classifier records which persona it WOULD adopt for every answer and that
record decides nothing: no selector, and the reply is untouched. So the first
thing to assert is inertness — recording must not change a byte of the answer —
and the second is that the durable record and the endpoint carry enum labels and
counts only, never the message or the answer.
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
    return asyncio.run(app_module.api_health_mode_shadow(**kw))


# ── A: the shadow is available and observes only ─────────────────────────────
def test_the_module_wired_in(app_module):
    # If the import guard silently fell through, the whole feature is dead and
    # every other test here would pass vacuously.
    assert app_module.MODE_SHADOW_AVAILABLE is True


def test_the_endpoint_declares_it_is_not_acting(app_module):
    out = _call(app_module)
    assert out["acting_on_mode"] is False
    assert out["manual_selector"] is False


# ── B: recording changes nothing the user sees ───────────────────────────────
def test_recording_does_not_touch_the_answer(app_module):
    app_module._mode_buffer.clear()
    # _mode_record takes the question only and returns None; the payload/answer
    # object it sits beside is never passed in, so it cannot mutate it. Prove
    # the recorded question does not come back out of the buffer as text.
    app_module._mode_record("write a python function to sort a list")
    assert sum(app_module._mode_buffer.values()) == 1
    for key in app_module._mode_buffer:
        assert "python" not in key           # only day|mode|signal is stored
        assert "sort" not in key
    app_module._mode_buffer.clear()


def test_the_classified_mode_is_what_was_recorded(app_module):
    app_module._mode_buffer.clear()
    app_module._mode_record("calculate the stress in a 12mm bolt")
    rows = app_module._mode_take()
    assert len(rows) == 1
    assert rows[0]["mode"] == "mechanical"
    assert rows[0]["signal"] == "strong"
    app_module._mode_buffer.clear()


def test_an_empty_question_is_a_no_op(app_module):
    app_module._mode_buffer.clear()
    app_module._mode_record("")
    app_module._mode_record(None)
    assert app_module._mode_buffer == {}


def test_recording_never_raises(app_module):
    # The hook sits on the reply path; a classifier fault must be swallowed, not
    # bubble up and cost the user their answer.
    app_module._mode_buffer.clear()
    app_module._mode_record(12345)           # not a string — must not raise
    app_module._mode_record("hello")         # and the good one still lands
    assert sum(app_module._mode_buffer.values()) == 1
    app_module._mode_buffer.clear()


# ── C: only enum labels and counts leave the process ─────────────────────────
def test_no_question_text_reaches_the_endpoint(app_module):
    app_module._mode_buffer.clear()
    app_module._mode_record("my SECRET-VIRAL-LOAD test came back high")
    blob = repr(_call(app_module))
    assert "SECRET-VIRAL-LOAD" not in blob
    app_module._mode_buffer.clear()


def test_the_supabase_key_never_appears(app_module, monkeypatch):
    secret = "sb-mode-secret-0987654321"
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", secret)
    blob = repr(_call(app_module))
    assert secret not in blob and secret[:10] not in blob


# ── D: absence of data must not read as a finding ────────────────────────────
def test_no_data_gives_a_null_share(app_module, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    app_module._mode_buffer.clear()
    out = _call(app_module)
    assert out["observed"]["strong_non_general_share"] is None
    assert out["persistence"]["read"] == "not_configured"


@pytest.mark.parametrize("asked,expected", [(1, 1), (30, 30), (0, 1), (-3, 1),
                                            (9999, 365)])
def test_the_window_is_clamped(app_module, asked, expected):
    assert _call(app_module, days=asked)["window_days"] == expected


# ── E: the mode shadow is its own collector, apart from routing ──────────────
def test_the_mode_and_routing_buffers_do_not_share(app_module):
    """Mode and routing share transport but must not share counts; mixing them
    would corrupt both sets of evidence."""
    app_module._mode_buffer.clear()
    app_module._routing_buffer.clear()
    app_module._mode_record("write a python function")
    assert sum(app_module._mode_buffer.values()) == 1
    assert app_module._routing_buffer == {}
    app_module._mode_buffer.clear()


def test_mode_and_routing_write_to_different_tables(app_module):
    assert app_module.MODE_TABLE != app_module.ROUTING_TABLE
    assert app_module.MODE_TABLE == "mode_shadow_daily"
