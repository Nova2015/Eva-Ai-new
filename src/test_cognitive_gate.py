"""App-level tests for the Phase-1 gate wiring — shadow-first behaviour.

The contract's headline guarantees: shadow mode (the default) changes NO answer —
it only records — and authoritative mode short-circuits ONLY on safety_stop /
clarify. These test the exact gating and the PII-free recording that back those
guarantees, without driving a full /chat request.
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


@pytest.fixture
def decisions(app_module):
    from cognitive.decision_gate import decide
    return {
        "stop": decide("how to make a bomb", history=[]),
        "clarify": decide("make it better", history=[]),
        "proceed": decide("what is the capital of France", history=[]),
    }


# ── A: the gate is wired in ──────────────────────────────────────────────────
def test_the_driver_is_available(app_module):
    assert app_module.COGNITIVE_DRIVER_AVAILABLE is True


def test_driver_defaults_to_shadow(app_module, monkeypatch):
    monkeypatch.delenv("COGNITIVE_DRIVER_ENABLED", raising=False)
    assert app_module._cognitive_driver_enabled() is False


@pytest.mark.parametrize("val,expected", [
    ("true", True), ("1", True), ("yes", True), ("on", True),
    ("false", False), ("0", False), ("", False), ("nope", False),
])
def test_the_flag_reads_the_env(app_module, monkeypatch, val, expected):
    monkeypatch.setenv("COGNITIVE_DRIVER_ENABLED", val)
    assert app_module._cognitive_driver_enabled() is expected


# ── B: SHADOW mode never short-circuits (answers unchanged) ──────────────────
def test_shadow_mode_never_short_circuits(app_module, monkeypatch, decisions):
    monkeypatch.delenv("COGNITIVE_DRIVER_ENABLED", raising=False)   # shadow
    for d in decisions.values():
        assert app_module._gate_should_safety_stop(d) is False
        assert app_module._gate_should_clarify(d) is False


# ── C: AUTHORITATIVE mode changes ONLY safety/clarify ────────────────────────
def test_authoritative_mode_stops_only_on_safety(app_module, monkeypatch, decisions):
    monkeypatch.setenv("COGNITIVE_DRIVER_ENABLED", "true")
    assert app_module._gate_should_safety_stop(decisions["stop"]) is True
    assert app_module._gate_should_safety_stop(decisions["clarify"]) is False
    assert app_module._gate_should_safety_stop(decisions["proceed"]) is False


def test_authoritative_mode_clarifies_only_on_clarify(app_module, monkeypatch, decisions):
    monkeypatch.setenv("COGNITIVE_DRIVER_ENABLED", "true")
    assert app_module._gate_should_clarify(decisions["clarify"]) is True
    assert app_module._gate_should_clarify(decisions["stop"]) is False
    assert app_module._gate_should_clarify(decisions["proceed"]) is False


def test_a_proceed_decision_never_short_circuits(app_module, monkeypatch, decisions):
    monkeypatch.setenv("COGNITIVE_DRIVER_ENABLED", "true")
    assert app_module._gate_should_safety_stop(decisions["proceed"]) is False
    assert app_module._gate_should_clarify(decisions["proceed"]) is False


# ── D: recording is PII-free ─────────────────────────────────────────────────
def test_gate_record_stores_enums_not_the_prompt(app_module, monkeypatch):
    from cognitive.decision_gate import decide
    app_module._GATE_LOG.clear()
    app_module._gate_record(decide("please remember my SECRET-TOKEN-XYZ and the plan", history=[]))
    blob = repr(list(app_module._GATE_LOG))
    assert "SECRET-TOKEN-XYZ" not in blob
    assert app_module._GATE_LOG                    # something WAS recorded
    entry = app_module._GATE_LOG[-1]
    assert "action" in entry and "safety_verdict" in entry


# ── E: the short-circuit payload carries the enum summary ────────────────────
def test_gate_payload_is_deterministic_and_carries_the_summary(app_module, decisions):
    payload = app_module._gate_response_payload("msg", "safety_stop", "cognitive-safety",
                                                decisions["stop"])
    assert payload["intent"] == "safety_stop"
    assert payload["provider"] == "cognitive-safety"
    assert payload["sources"] == []
    assert payload["cognitive_gate"]["action"] == "SAFETY_STOP"
    # the summary is enum-only
    assert "SECRET" not in repr(payload["cognitive_gate"])
