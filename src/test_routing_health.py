"""Tests for /api/health/routing — Stage 1 of adaptive routing.

Stage 1's entire value is that it changes nothing while it watches. So the
first thing to assert is inertness: recording a comparison must not alter the
reply, the route, or what the engine does.
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
    return asyncio.run(app_module.api_health_routing(**kw))


# ── A: Stage 1 observes and nothing else ─────────────────────────────────────
def test_the_endpoint_declares_that_it_is_not_acting(app_module):
    assert _call(app_module)["acting_on_strategy"] is False


def test_recording_does_not_mutate_the_payload(app_module):
    """The payload is the reply about to be returned. Reading it to record a
    comparison must not change a byte of it."""
    app_module._routing_buffer.clear()
    payload = {"provider": "groq", "mode_used": "hybrid",
               "sources": ["a.pdf"], "answer": "hello"}
    before = dict(payload)
    app_module._routing_record(payload, "DIRECT")
    assert payload == before
    app_module._routing_buffer.clear()


def test_recording_without_a_strategy_is_a_no_op(app_module):
    """When the engine did not run — timeout, disabled, import failure — there
    is nothing to compare, and inventing a label would pollute the matrix."""
    app_module._routing_buffer.clear()
    app_module._routing_record({"provider": "groq"}, None)
    app_module._routing_record({"provider": "groq"}, "")
    assert app_module._routing_buffer == {}


def test_a_strategy_outside_the_enum_never_enters_the_buffer(app_module):
    app_module._routing_buffer.clear()
    app_module._routing_record({"provider": "groq"}, "whatever the user typed")
    assert app_module._routing_buffer == {}


# ── B: what the payload may contain ──────────────────────────────────────────
def test_no_question_or_answer_reaches_the_endpoint(app_module):
    app_module._routing_buffer.clear()
    app_module._routing_record(
        {"provider": "groq", "answer": "SECRET-ANSWER-TEXT",
         "question": "SECRET-QUESTION-TEXT", "mode_used": "hybrid"},
        "DIRECT")
    blob = repr(_call(app_module))
    assert "SECRET-ANSWER-TEXT" not in blob
    assert "SECRET-QUESTION-TEXT" not in blob
    app_module._routing_buffer.clear()


def test_the_supabase_key_never_appears(app_module, monkeypatch):
    secret = "sb-routing-secret-1234567890"
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", secret)
    blob = repr(_call(app_module))
    assert secret not in blob and secret[:10] not in blob


# ── C: absence of data must not read as a finding ────────────────────────────
def test_no_data_gives_a_null_share(app_module, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    out = _call(app_module)
    assert out["observed"]["retrieved_without_need"]["share"] is None
    assert out["persistence"]["read"] == "not_configured"


@pytest.mark.parametrize("asked,expected", [(1, 1), (7, 7), (0, 1), (-3, 1),
                                            (9999, 365)])
def test_the_window_is_clamped(app_module, asked, expected):
    assert _call(app_module, days=asked)["window_days"] == expected


# ── D: buffering ─────────────────────────────────────────────────────────────
def test_pairs_buffer_and_drain_once(app_module):
    app_module._routing_buffer.clear()
    app_module._routing_record({"provider": "groq", "mode_used": "hybrid"}, "DIRECT")
    first = app_module._routing_take()
    assert len(first) == 1 and first[0]["route"] == "RAG_SERVICE"
    assert app_module._routing_take() == []


def test_the_two_collectors_keep_separate_buffers(app_module):
    """The firewall and routing collectors share transport but must not share
    counts; mixing them would corrupt both sets of evidence."""
    app_module._routing_buffer.clear()
    app_module._shadow_buffer.clear()
    app_module._routing_record({"provider": "groq", "mode_used": "hybrid"}, "DIRECT")
    assert len(app_module._routing_buffer) == 1
    assert app_module._shadow_buffer == {}
    app_module._routing_buffer.clear()


def test_the_two_collectors_write_to_different_tables(app_module):
    assert app_module.ROUTING_TABLE != app_module.SHADOW_TABLE
