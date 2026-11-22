"""Offline tests for slice 20.x INVALID_INPUT validation.
Mock Piston (execute_code); no network. Run from backend/runtime_engine:
    python -m pytest test_input_validation.py -q
"""
import asyncio
import pytest

import input_validation as iv
import runtime_api
import execution_policy as ep


# ── STEP 1: appears_executable ───────────────────────────────────────────────────
def test_empty_is_not_executable():
    assert iv.appears_executable("", "python") == {"executable": False, "reason": "empty"}


def test_whitespace_only_is_empty():
    assert iv.appears_executable("   \n\t ", "python")["reason"] == "empty"


def test_pure_prose_explain_ai_not_code():
    assert iv.appears_executable("Explain AI", "python") == {"executable": False, "reason": "not_code"}


def test_pure_prose_run_test_suite_not_code():
    assert iv.appears_executable("Run Test Suite", "python") == {"executable": False, "reason": "not_code"}


def test_valid_python_executable():
    assert iv.appears_executable('print("hi")', "python")["executable"] is True


def test_bare_expression_executable():
    assert iv.appears_executable("2+2", "python")["executable"] is True


def test_assignment_executable():
    assert iv.appears_executable("x = 5", "python")["executable"] is True


def test_comprehension_executable():
    assert iv.appears_executable("[i*i for i in range(3)]", "python")["executable"] is True


def test_BROKEN_python_goes_to_piston_not_invalid():
    # ── THE CRITICAL BOUNDARY ──
    # Broken code must be EXECUTABLE so Piston returns the real SyntaxError.
    r = iv.appears_executable("def f(:", "python")
    assert r["executable"] is True and r["reason"] is None


def test_valid_js_executable():
    # Passes whether or not `node` is present (parse OR heuristic both accept real JS).
    assert iv.appears_executable('console.log("hi")', "javascript")["executable"] is True


def test_python_alias_py():
    assert iv.appears_executable("x=1", "py")["executable"] is True


# ── STEP 2: API path (handle_execute_request) ────────────────────────────────────
class _PistonSpy:
    def __init__(self):
        self.called = 0

    async def __call__(self, language, code):
        self.called += 1
        return {"status": "SUCCESS", "language": language, "stdout": "ok", "stderr": "",
                "exit_code": 0, "execution_ms": 5, "timed_out": False, "truncated": False,
                "runtime_source": "piston", "error": None}


@pytest.fixture
def piston(monkeypatch):
    spy = _PistonSpy()
    monkeypatch.setattr(runtime_api, "execute_code", spy)
    return spy


def _run(coro):
    return asyncio.run(coro)


def test_invalid_input_returns_200_and_never_calls_piston(piston):
    status, payload = _run(runtime_api.handle_execute_request("python", "Explain AI", enabled=True))
    assert status == 200
    assert payload["status"] == "INVALID_INPUT"
    assert payload["runtime_source"] == "validator"
    assert payload["reason"] == "not_code"
    assert payload["exit_code"] is None and payload["execution_ms"] == 0
    assert payload["timed_out"] is False and payload["truncated"] is False
    assert piston.called == 0  # Piston NEVER contacted


def test_valid_code_reaches_piston(piston):
    status, payload = _run(runtime_api.handle_execute_request("python", 'print("hi")', enabled=True))
    assert status == 200 and payload["status"] == "SUCCESS"
    assert piston.called == 1


def test_broken_code_reaches_piston_not_invalid_at_api(piston):
    status, payload = _run(runtime_api.handle_execute_request("python", "def f(:", enabled=True))
    assert payload["status"] != "INVALID_INPUT"
    assert piston.called == 1


def test_disabled_returns_403_and_no_validation_or_piston(piston):
    status, payload = _run(runtime_api.handle_execute_request("python", "Explain AI", enabled=False))
    assert status == 403
    assert piston.called == 0


# ── consistency with slice-6 mark_runnable ──────────────────────────────────────
def test_consistency_markrunnable_accept_implies_executable():
    text = '```python\nprint("hi")\n```'
    m = ep.mark_runnable(text)
    assert m["eligible"] is True
    v = iv.appears_executable(m["code"], m["language"])
    assert v["executable"] is True  # never INVALID_INPUT'd for a contradictory reason
