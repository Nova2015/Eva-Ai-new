"""Slice 6 tests: eligibility classification + execute-endpoint handler.

Offline: Piston HTTP is mocked; the flag-off test PROVES no HTTP client is
even constructed. Run:  pytest backend/runtime_engine -v
"""

import asyncio

import httpx
import pytest

try:
    from backend.runtime_engine import execution_policy, piston_adapter
    from backend.runtime_engine.execution_policy import mark_runnable, runnable_payload
    from backend.runtime_engine.runtime_api import handle_execute_request
except ImportError:
    import execution_policy
    import piston_adapter
    from execution_policy import mark_runnable, runnable_payload
    from runtime_api import handle_execute_request


def _run(coro):
    return asyncio.run(coro)


# ── mark_runnable ─────────────────────────────────────────────────────────────

def test_prose_only_not_eligible():
    m = mark_runnable("Paris is the capital of France.")
    assert m["eligible"] is False
    assert m["reason"] == "no_code_block"
    assert m["language"] is None and m["code"] is None


def test_single_python_block_eligible():
    m = mark_runnable("Here you go:\n```python\nprint(1)\n```\nEnjoy!")
    assert m["eligible"] is True
    assert m["reason"] == "eligible"
    assert m["language"] == "python"
    assert m["code"] == "print(1)"


def test_two_blocks_not_eligible():
    m = mark_runnable("```python\nprint(1)\n```\n\n```js\nconsole.log(2)\n```")
    assert m["eligible"] is False
    assert m["reason"] == "multiple_code_blocks"


def test_unsupported_language_not_eligible():
    for fence in ("```bash\nls\n```", "```sql\nSELECT 1;\n```", "```html\n<b>x</b>\n```"):
        m = mark_runnable(fence)
        assert m["eligible"] is False
        assert m["reason"] == "unsupported_language"


def test_oversized_code_not_eligible():
    big = "x = 1\n" * 5_000  # 30k chars > 10k cap
    m = mark_runnable(f"```python\n{big}\n```")
    assert m["eligible"] is False
    assert m["reason"] == "too_large"
    assert m["language"] == "python"


def test_chart_and_mermaid_fences_do_not_count_as_code():
    text = (
        '```chart\n{"type":"pie","data":[]}\n```\n'
        "```mermaid\nflowchart TD\n A-->B\n```\n"
        "```js\nconsole.log(1)\n```"
    )
    m = mark_runnable(text)
    assert m["eligible"] is True
    assert m["language"] == "javascript"


def test_js_alias_normalized():
    m = mark_runnable("```node\nconsole.log(1)\n```")
    assert m["eligible"] is True
    assert m["language"] == "javascript"


# ── runnable_payload (chat attach point) ──────────────────────────────────────

def test_runnable_payload_omits_code():
    p = runnable_payload("```python\nprint(1)\n```")
    assert p == {"eligible": True, "language": "python"}
    assert "code" not in p


def test_runnable_payload_never_raises(monkeypatch):
    def boom(text):
        raise RuntimeError("classifier exploded")
    monkeypatch.setattr(execution_policy, "mark_runnable", boom)
    p = execution_policy.runnable_payload("anything")
    assert p == {"eligible": False, "language": None}


# ── handle_execute_request (endpoint handler) ────────────────────────────────

class FakeResponse:
    status_code = 200
    def __init__(self, payload):
        self._payload = payload
    def json(self):
        return self._payload


class Fake503:
    status_code = 503
    def json(self):
        return {}


class FakeClient:
    def __init__(self, response):
        self._response = response
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        return False
    async def post(self, url, json=None):
        return self._response


def _forbid_http(monkeypatch):
    def explode(**kw):
        raise AssertionError("Piston must not be contacted")
    monkeypatch.setattr(piston_adapter.httpx, "AsyncClient", explode)


def test_flag_off_blocks_and_never_calls_piston(monkeypatch):
    monkeypatch.delenv("EVA_ENABLE_RUNTIME_EXECUTION", raising=False)
    _forbid_http(monkeypatch)
    status, payload = _run(handle_execute_request("python", "print(1)"))
    assert status == 403
    assert "disabled" in payload["detail"].lower()

    monkeypatch.setenv("EVA_ENABLE_RUNTIME_EXECUTION", "1")  # not "true" -> still off
    status, _ = _run(handle_execute_request("python", "print(1)"))
    assert status == 403


def test_flag_on_success_payload(monkeypatch):
    monkeypatch.setenv("EVA_ENABLE_RUNTIME_EXECUTION", "true")
    monkeypatch.setattr(
        piston_adapter.httpx, "AsyncClient",
        lambda **kw: FakeClient(FakeResponse(
            {"run": {"stdout": "hi\n", "stderr": "", "code": 0, "signal": None}}
        )),
    )
    status, payload = _run(handle_execute_request("python", "print('hi')"))
    assert status == 200
    assert payload["status"] == "SUCCESS"
    assert payload["stdout"] == "hi\n"
    assert payload["runtime_source"] == "piston"


def test_flag_on_piston_503_is_unknown_200(monkeypatch):
    monkeypatch.setenv("EVA_ENABLE_RUNTIME_EXECUTION", "true")
    monkeypatch.setattr(piston_adapter.httpx, "AsyncClient", lambda **kw: FakeClient(Fake503()))
    status, payload = _run(handle_execute_request("python", "print(1)"))
    assert status == 200          # endpoint still returns 200
    assert payload["status"] == "UNKNOWN"
    assert "503" in payload["error"]


def test_handler_hides_internal_errors(monkeypatch):
    monkeypatch.setenv("EVA_ENABLE_RUNTIME_EXECUTION", "true")

    async def boom(language, code, **kw):
        raise RuntimeError("secret /etc/passwd traceback")

    try:
        import backend.runtime_engine.runtime_api as runtime_api
    except ImportError:
        import runtime_api
    monkeypatch.setattr(runtime_api, "execute_code", boom)
    status, payload = _run(handle_execute_request("python", "print(1)"))
    assert status == 200
    assert payload["status"] == "UNKNOWN"
    assert "RuntimeError" in payload["error"]
    assert "secret" not in payload["error"]  # message/traceback never leaked
