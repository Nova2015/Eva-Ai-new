"""Tests for /api/health/vision and its reason codes (Update 30).

The endpoint exists because a vision failure is indistinguishable from outside:
every cause returns the same VISION_UNAVAILABLE_RESPONSE. Diagnosing production
meant reading container logs, and it took two rounds of inference to establish
that gemini-3.5-flash had been retired and then that its replacement had no
quota.

It is unauthenticated on purpose, so the load-bearing tests here are the ones
about what it must NOT say. A diagnostic endpoint that leaks a key is worse
than no diagnostic endpoint.
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


# ── A: classification comes from a fixed enum, never provider text ───────────
@pytest.mark.parametrize("message,expected", [
    ("404 models/gemini-3.5-flash is not found for API version v1beta",
     "model_not_found"),
    ("429 You exceeded your current quota, please check your plan and billing",
     "quota_exhausted"),
    ("Error code: 429 - insufficient_quota: You have no credits remaining",
     "quota_exhausted"),
    ("401 Unauthorized: invalid api key", "auth_failed"),
    ("Connection reset by peer", "provider_error"),
])
def test_reason_codes(app_module, message, expected):
    assert app_module._vision_reason_code(Exception(message)) == expected


def test_a_missing_library_is_its_own_code(app_module):
    assert app_module._vision_reason_code(ImportError("No module named 'PIL'")) \
        == "library_missing"


def test_an_unrecognised_error_still_returns_an_enum_value(app_module):
    """The FALLBACK is the branch that matters.

    A message we already classify is safe by construction. The danger is the
    one we do not recognise: if the default returned the provider's text, an
    unauthenticated caller would receive whatever it happened to contain. The
    earlier version of this file only tested classified messages, so a mutation
    replacing the fallback with str(exc) survived.
    """
    raw = ("Unexpected failure contacting https://internal.example/acct/12345 "
           "for operator@example.com")
    code = app_module._vision_reason_code(Exception(raw))
    assert code == app_module.VISION_REASON_UNKNOWN
    assert "http" not in code
    assert "@" not in code
    assert "12345" not in code


def test_the_provider_message_never_becomes_the_reason_code(app_module):
    """The whole point of the enum. An OpenAI quota error carries a billing URL
    and an organization path; none of it may reach an unauthenticated response."""
    raw = ("Error code: 429 - {'error': {'message': 'You have no credits "
           "remaining. Add credits at https://platform.openai.com/settings/"
           "organization/billing/', 'code': 'credit_balance_exhausted'}}")
    code = app_module._vision_reason_code(Exception(raw))
    assert code == "quota_exhausted"
    assert "http" not in code
    assert "organization" not in code
    assert code in {
        app_module.VISION_REASON_OK, app_module.VISION_REASON_NO_KEY,
        app_module.VISION_REASON_MODEL_NOT_FOUND, app_module.VISION_REASON_QUOTA,
        app_module.VISION_REASON_AUTH, app_module.VISION_REASON_LIBRARY_MISSING,
        app_module.VISION_REASON_UNKNOWN,
    }


# ── B: the payload, and what it must never contain ───────────────────────────
def _payload(app_module):
    import asyncio
    return asyncio.run(app_module.api_health_vision())


def test_reports_key_presence_as_a_boolean(app_module, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "sk-not-a-real-key-1234567890")
    out = _payload(app_module)
    assert out["gemini"]["key_set"] is True


def test_never_returns_the_key_or_any_part_of_it(app_module, monkeypatch):
    """A diagnostic endpoint that leaks a credential is worse than none."""
    secret = "sk-live-SUPERSECRETVALUE-0987654321"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    blob = repr(_payload(app_module))
    assert secret not in blob
    for n in (8, 12, 16):
        assert secret[:n] not in blob, f"leaked a {n}-char prefix of the key"


def test_an_empty_key_reads_as_absent(app_module, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "   ")
    assert _payload(app_module)["gemini"]["key_set"] is False


def test_reports_the_configured_model(app_module, monkeypatch):
    """The question that took two rounds to answer: which model is live?"""
    monkeypatch.setenv("GEMINI_VISION_MODEL", "gemini-flash-latest")
    assert _payload(app_module)["gemini"]["model"] == "gemini-flash-latest"


def test_falls_back_to_the_shipped_default(app_module, monkeypatch):
    monkeypatch.delenv("GEMINI_VISION_MODEL", raising=False)
    assert _payload(app_module)["gemini"]["model"] == "gemini-3.5-flash"


def test_configured_is_false_when_no_provider_can_run(app_module, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    assert _payload(app_module)["configured"] is False


def test_configured_is_true_when_one_provider_can_run(app_module, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "a-key")
    out = _payload(app_module)
    # Gemini also needs its libraries; the fixture environment has them.
    assert out["configured"] is out["gemini"]["library"]


def test_it_does_not_call_a_provider(app_module, monkeypatch):
    """Probing on every health check would spend the quota this endpoint
    exists to report on."""
    import importlib
    called = []
    real = importlib.import_module("importlib.util").find_spec
    monkeypatch.setattr("importlib.util.find_spec", lambda n: called.append(n) or real(n))
    _payload(app_module)
    assert all("openai" in c or "google" in c or "PIL" in c for c in called)


# ── C: outcomes are recorded, bounded, and carry no content ──────────────────
def test_recording_stores_only_a_code_and_a_time(app_module):
    app_module._record_vision("gemini", app_module.VISION_REASON_QUOTA)
    entry = app_module._VISION_LAST["gemini"]
    assert set(entry) == {"reason_code", "at"}
    assert entry["reason_code"] == "quota_exhausted"


def test_the_record_is_bounded_to_the_two_providers(app_module):
    assert set(app_module._VISION_LAST) == {"openai", "gemini"}


def test_the_endpoint_surfaces_the_last_outcome(app_module):
    app_module._record_vision("openai", app_module.VISION_REASON_AUTH)
    assert _payload(app_module)["openai"]["last"]["reason_code"] == "auth_failed"
