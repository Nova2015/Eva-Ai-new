"""Offline mocked tests for the slice-4 runtime engine. NO network.

Run:  pytest backend/runtime_engine -v

httpx is monkeypatched inside piston_adapter; the one real-network test is
@pytest.mark.integration and skipped unless RUN_INTEGRATION=1. Async driven
with asyncio.run() -- no pytest-asyncio dependency.
"""

import asyncio
import os

import httpx
import pytest

try:
    from backend.runtime_engine import piston_adapter
    from backend.runtime_engine.execution_service import execute_code, extract_first_runnable_block
except ImportError:
    import piston_adapter
    from execution_service import execute_code, extract_first_runnable_block


class FakeResponse:
    def __init__(self, status_code=200, payload=None, bad_json=False):
        self.status_code = status_code
        self._payload = payload or {}
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


class FakeClient:
    calls = []

    def __init__(self, response=None, raise_exc=None):
        self._response = response
        self._raise = raise_exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None):
        FakeClient.calls.append({"url": url, "json": json})
        if self._raise:
            raise self._raise
        return self._response


def _patch(monkeypatch, response=None, raise_exc=None):
    FakeClient.calls = []
    monkeypatch.setattr(
        piston_adapter.httpx, "AsyncClient",
        lambda **kw: FakeClient(response=response, raise_exc=raise_exc),
    )


def _forbid_http(monkeypatch):
    def explode(**kw):
        raise AssertionError("HTTP client must not be constructed for this case")
    monkeypatch.setattr(piston_adapter.httpx, "AsyncClient", explode)


def _run(coro):
    return asyncio.run(coro)


def _piston(run=None, compile_=None):
    d = {"run": run or {}}
    if compile_ is not None:
        d["compile"] = compile_
    return d


def _assert_types(r):
    assert isinstance(r["status"], str)
    assert isinstance(r["language"], str)
    assert isinstance(r["stdout"], str)
    assert isinstance(r["stderr"], str)
    assert r["exit_code"] is None or isinstance(r["exit_code"], int)
    assert r["execution_ms"] is None or isinstance(r["execution_ms"], int)
    assert isinstance(r["timed_out"], bool)
    assert isinstance(r["truncated"], bool)
    assert r["runtime_source"] == "piston"
    assert r["error"] is None or isinstance(r["error"], str)


def test_python_hello_world_success(monkeypatch):
    _patch(monkeypatch, FakeResponse(200, _piston(
        run={"stdout": "hello world\n", "stderr": "", "code": 0, "signal": None},
    )))
    r = _run(execute_code("python", 'print("hello world")'))
    _assert_types(r)
    assert r["status"] == "SUCCESS"
    assert r["stdout"] == "hello world\n"
    assert r["exit_code"] == 0
    assert isinstance(r["execution_ms"], int)
    assert r["error"] is None
    assert FakeClient.calls[0]["url"].endswith("/execute")
    assert FakeClient.calls[0]["json"]["version"] == "3.10.0"


def test_python_syntax_error_is_runtime_error_not_unknown(monkeypatch):
    _patch(monkeypatch, FakeResponse(200, _piston(
        run={"stdout": "", "stderr": 'SyntaxError: invalid syntax\n', "code": 1, "signal": None},
    )))
    r = _run(execute_code("python", "def f( :"))
    _assert_types(r)
    assert r["status"] == "RUNTIME_ERROR"
    assert r["status"] != "UNKNOWN"
    assert r["exit_code"] == 1
    assert "SyntaxError" in r["stderr"]
    assert r["error"] is None


def test_piston_503_is_unknown(monkeypatch):
    _patch(monkeypatch, FakeResponse(503, {}))
    r = _run(execute_code("python", "print(1)"))
    _assert_types(r)
    assert r["status"] == "UNKNOWN"
    assert r["exit_code"] is None
    assert "503" in r["error"]


def test_piston_unreachable_is_unknown_no_raise(monkeypatch):
    _patch(monkeypatch, raise_exc=httpx.ConnectError("boom"))
    r = _run(execute_code("python", "print(1)"))
    assert r["status"] == "UNKNOWN"
    assert r["exit_code"] is None
    assert "unreachable" in r["error"]


def test_piston_signal_is_timeout(monkeypatch):
    _patch(monkeypatch, FakeResponse(200, _piston(
        run={"stdout": "", "stderr": "", "code": None, "signal": "SIGKILL"},
    )))
    r = _run(execute_code("python", "while True: pass"))
    _assert_types(r)
    assert r["status"] == "TIMEOUT"
    assert r["timed_out"] is True


def test_malformed_body_is_unknown_no_crash(monkeypatch):
    _patch(monkeypatch, FakeResponse(200, bad_json=True))
    r = _run(execute_code("python", "print(1)"))
    assert r["status"] == "UNKNOWN"
    assert "bad json" in r["error"]


def test_unsupported_language_is_unknown_clean(monkeypatch):
    _forbid_http(monkeypatch)
    r = _run(execute_code("ruby", "puts 1"))
    _assert_types(r)
    assert r["status"] == "UNKNOWN"
    assert "unsupported language" in r["error"]


def test_oversized_stdout_truncated(monkeypatch):
    _patch(monkeypatch, FakeResponse(200, _piston(
        run={"stdout": "x" * 50_000, "stderr": "", "code": 0, "signal": None},
    )))
    r = _run(execute_code("python", "print('x' * 50000)"))
    assert r["status"] == "SUCCESS"
    assert r["truncated"] is True
    assert len(r["stdout"]) < 50_000


def test_oversized_code_rejected_before_http(monkeypatch):
    _forbid_http(monkeypatch)
    big_code = "x = 1\n" * 5_000
    r = _run(execute_code("python", big_code))
    _assert_types(r)
    assert r["status"] == "UNKNOWN"
    assert "code exceeds max size" in r["error"]
    assert r["execution_ms"] is None


def test_javascript_hello_world_success(monkeypatch):
    _patch(monkeypatch, FakeResponse(200, _piston(
        run={"stdout": "hi\n", "stderr": "", "code": 0, "signal": None},
    )))
    r = _run(execute_code("javascript", "console.log('hi')"))
    _assert_types(r)
    assert r["status"] == "SUCCESS"
    assert r["stdout"] == "hi\n"
    assert FakeClient.calls[0]["json"]["version"] == "18.15.0"


def test_client_timeout_is_unknown(monkeypatch):
    _patch(monkeypatch, raise_exc=httpx.ReadTimeout("too slow"))
    r = _run(execute_code("javascript", "console.log(1)"))
    assert r["status"] == "UNKNOWN"
    assert r["error"] is not None


def test_compile_stage_error_path_handled(monkeypatch):
    _patch(monkeypatch, FakeResponse(200, _piston(
        run={},
        compile_={"stdout": "", "stderr": "error: expected ';'", "code": 1},
    )))
    r = _run(execute_code("python", "..."))
    assert r["status"] == "RUNTIME_ERROR"
    assert "expected ';'" in r["stderr"]


def test_language_aliases_normalized(monkeypatch):
    _patch(monkeypatch, FakeResponse(200, _piston(
        run={"stdout": "1\n", "stderr": "", "code": 0, "signal": None},
    )))
    r = _run(execute_code("js", "console.log(1)"))
    assert r["status"] == "SUCCESS"
    assert r["language"] == "javascript"


# -- Slice 4.5: extraction for chat wiring ------------------------------------

def test_extract_first_python_block():
    text = "Here:\n```python\nprint(1)\n```\nand\n```js\nconsole.log(2)\n```"
    assert extract_first_runnable_block(text) == ("python", "print(1)")


def test_extract_ignores_chart_mermaid_json_untagged():
    text = (
        '```chart\n{"type":"pie","data":[]}\n```\n'
        "```mermaid\nflowchart TD\n A-->B\n```\n"
        '```json\n{"a":1}\n```\n'
        "```\nplain\n```\n"
        "```js\nconsole.log(1)\n```"
    )
    assert extract_first_runnable_block(text) == ("javascript", "console.log(1)")


def test_extract_none_when_no_runnable_block():
    assert extract_first_runnable_block("plain prose, no code") is None
    assert extract_first_runnable_block("") is None
    assert extract_first_runnable_block(None) is None


@pytest.mark.integration
@pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="network-gated; set RUN_INTEGRATION=1")
def test_real_piston_python_hello():
    r = _run(execute_code("python", 'print("live")'))
    assert r["status"] == "SUCCESS"
    assert "live" in r["stdout"]
