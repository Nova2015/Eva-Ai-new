"""Pytest suite for the slice 2 integration adapter.

Run:  pytest backend/review_engine -v

The debug-gating tests exercise attach_review_if_enabled() — the exact
function app.py's chat() calls — rather than importing the 8,400-line app.py
with its heavy dependency graph.
"""

try:
    from backend.review_engine import integration_adapter
    from backend.review_engine.integration_adapter import (
        run_review_pipeline,
        attach_review_if_enabled,
        format_review_log,
    )
except ImportError:
    import integration_adapter
    from integration_adapter import (
        run_review_pipeline,
        attach_review_if_enabled,
        format_review_log,
    )


# ── Payload shape ─────────────────────────────────────────────────────────────

def test_payload_has_all_required_fields():
    r = run_review_pipeline("Just some plain prose.")
    assert isinstance(r["valid"], bool)
    assert r["score"] is None or isinstance(r["score"], float)
    assert isinstance(r["issues"], list)
    assert isinstance(r["checks"], dict)
    meta = r["review_meta"]
    assert meta["mode"] == "standard"
    assert meta["validator_version"] == "v1"
    assert isinstance(meta["execution_ms"], int)
    assert meta["error"] is None


def test_valid_response_passes():
    text = 'Here you go:\n\n```json\n{"a": 1}\n```\n'
    r = run_review_pipeline(text)
    assert r["valid"] is True
    assert r["issues"] == []
    assert r["score"] == 1.0


def test_known_bad_response_broken_mermaid():
    text = "```mermaid\ngraph TD\n  A[Start --> B(End)\n```"
    r = run_review_pipeline(text)
    assert r["valid"] is False
    assert "unbalanced_brackets" in [i["code"] for i in r["issues"]]
    assert isinstance(r["score"], float) and r["score"] < 1.0


# ── Crash path ────────────────────────────────────────────────────────────────

def test_validator_crash_returns_safe_payload(monkeypatch):
    def boom(text, mode):
        raise RuntimeError("validator exploded")

    monkeypatch.setattr(integration_adapter, "review_response", boom)
    r = run_review_pipeline("anything")
    assert r["valid"] is True           # fail-open
    assert r["score"] is None
    assert r["issues"] == []
    assert r["checks"] == {}
    assert "RuntimeError" in r["review_meta"]["error"]
    assert "validator exploded" in r["review_meta"]["error"]
    assert isinstance(r["review_meta"]["execution_ms"], int)


# ── Debug gating (the exact function chat() uses) ─────────────────────────────

def _fresh_body():
    return {"success": True, "answer": "hello"}


def test_review_attached_when_env_debug_on(monkeypatch):
    monkeypatch.setenv("DEBUG_REVIEW", "true")
    review = run_review_pipeline("hello")
    body = attach_review_if_enabled(_fresh_body(), review, request_debug=False)
    assert "review" in body
    assert body["review"] is review
    assert body["answer"] == "hello"    # response content untouched


def test_review_attached_when_request_flag_on(monkeypatch):
    monkeypatch.delenv("DEBUG_REVIEW", raising=False)
    review = run_review_pipeline("hello")
    body = attach_review_if_enabled(_fresh_body(), review, request_debug=True)
    assert "review" in body


def test_review_absent_when_debug_off(monkeypatch):
    monkeypatch.delenv("DEBUG_REVIEW", raising=False)
    review = run_review_pipeline("hello")
    body = attach_review_if_enabled(_fresh_body(), review, request_debug=False)
    assert "review" not in body
    assert body == {"success": True, "answer": "hello"}  # nothing else altered


def test_env_value_must_be_exactly_true(monkeypatch):
    monkeypatch.setenv("DEBUG_REVIEW", "1")  # not "true" -> off
    review = run_review_pipeline("hello")
    body = attach_review_if_enabled(_fresh_body(), review, request_debug=False)
    assert "review" not in body


# ── Log line ──────────────────────────────────────────────────────────────────

def test_format_review_log_shape():
    review = run_review_pipeline("```mermaid\ngraph TD\n  A[x --> B\n```")
    line = format_review_log(review)
    assert line.startswith("[REVIEW] ")
    assert "score=" in line
    assert "valid=False" in line
    assert "issues=1" in line
    assert "execution_ms=" in line
    assert "mode=standard" in line
