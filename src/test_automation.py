"""Tests for the Update 38 automation lifecycle.

The properties that matter for a foundation that will later carry more:

  * it runs the whole lifecycle and delivers a verified file (happy path);
  * a real workbook it builds actually round-trips (not a fake in a fake);
  * verification failure is caught, corrected within a strict bound, and — if
    it persists — stops honestly instead of shipping a broken file;
  * the retry budget cannot be exceeded;
  * a tool failure and an upload failure are each recorded, never hidden;
  * NO failure is ever reported as success, and no artifact is invented;
  * provenance (a digest) is recorded;
  * the executor can reach exactly one tool and refuses any other;
  * a request that is not a spreadsheet request never enters the path.
"""

import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import automation as A
from automation import (
    DeliveredCheck, Deps, Outcome, ToolId, ToolUnavailable, UnapprovedTool,
    run_excel_task, run_tool,
)


ROWS = [["name", "qty", "price"], ["widget", 10, 2.5], ["bolt", 4, 0.75]]
XLSX = b"PK\x03\x04 fake-but-non-empty workbook bytes"


def _run(coro):
    return asyncio.run(coro)


def make_deps(**over):
    """Working fakes by default; override one at a time to inject a fault.

    `tools_seen` records every tool id the orchestrator asked to run, so a test
    can prove nothing but the Excel tool was ever reached.
    """
    tools_seen = []

    def parse(_q):
        return [list(r) for r in ROWS]

    def run_tool_fake(tool_id, rows, sheet):
        tools_seen.append(tool_id)
        return XLSX

    def verify(_data, _expected):
        return True, {"opened": True}

    async def upload(_data, _name):
        return "https://cdn.example/eva-data.xlsx", "ok"

    def digest(data):
        import hashlib
        return hashlib.sha256(data).hexdigest()[:16]

    def strategy(_q):
        return "DIRECT"

    deps = Deps(
        parse=over.pop("parse", parse),
        run_tool=over.pop("run_tool", run_tool_fake),
        verify=over.pop("verify", verify),
        upload=over.pop("upload", upload),
        digest=over.pop("digest", digest),
        strategy=over.pop("strategy", strategy),
        download=over.pop("download", None),
    )
    assert not over, f"unknown deps override: {list(over)}"
    return deps, tools_seen


def counter(fail_times, then=(True, {})):
    """A verify/upload fake that fails a fixed number of times, then succeeds.
    Returns (fn, calls) where calls[0] is the call count."""
    calls = [0]

    def fn(*_a, **_k):
        calls[0] += 1
        if calls[0] <= fail_times:
            return (False, {"reason": "shape_mismatch"})
        return then
    return fn, calls


# ── 1: happy path ────────────────────────────────────────────────────────────
def test_plan_act_verify_deliver_happy_path():
    deps, tools = make_deps()
    res = _run(run_excel_task("make an excel sheet", deps))
    assert res.outcome is Outcome.DELIVERED
    assert res.ok is True
    assert res.url == "https://cdn.example/eva-data.xlsx"
    assert res.record.verified is True
    assert res.record.retries == 0
    assert res.record.correction_attempted is False
    assert res.rows == 2 and res.columns == 3      # body rows, columns
    assert tools == [ToolId.BUILD_EXCEL]


# ── 2: a real workbook round-trips (real build + real verify) ────────────────
def test_a_real_workbook_is_built_and_round_trips():
    from spreadsheet import build_workbook, verify_workbook, parse_table

    async def upload(_data, _name):
        return "https://cdn.example/real.xlsx", "ok"

    deps = Deps(
        parse=parse_table,
        run_tool=run_tool,                 # the real gated registry
        verify=verify_workbook,            # the real 35b verifier
        upload=upload,
        digest=A._digest_bytes,
        strategy=lambda _q: "DIRECT",
        download=None,
    )
    q = "create an excel sheet\nname, qty, price\nwidget, 10, 2.5\nbolt, 4, 0.75"
    res = _run(run_excel_task(q, deps))
    assert res.outcome is Outcome.DELIVERED
    assert res.record.verified is True
    assert res.record.digest and len(res.record.digest) == 16
    assert res.rows == 2 and res.columns == 3


# ── 3: verification failure, no retries left ─────────────────────────────────
def test_persistent_verification_failure_stops_and_does_not_deliver():
    always_fail, _ = counter(fail_times=99)
    deps, _ = make_deps(verify=always_fail)
    res = _run(run_excel_task("sheet", deps, max_retries=2))
    assert res.outcome is Outcome.VERIFY_FAILED
    assert res.ok is False
    assert res.url is None
    assert res.record.verified is False
    assert res.record.correction_attempted is True


# ── 4: correction + successful retry ─────────────────────────────────────────
def test_verification_fails_once_then_a_retry_succeeds():
    verify, calls = counter(fail_times=1)
    deps, _ = make_deps(verify=verify)
    res = _run(run_excel_task("sheet", deps, max_retries=2))
    assert res.outcome is Outcome.DELIVERED
    assert res.record.verified is True
    assert res.record.correction_attempted is True
    assert res.record.retries == 1
    assert calls[0] == 2                            # failed once, then verified


# ── 5: the retry limit is strict ─────────────────────────────────────────────
def test_the_retry_budget_is_bounded():
    verify, calls = counter(fail_times=99)
    deps, _ = make_deps(verify=verify)
    res = _run(run_excel_task("sheet", deps, max_retries=2))
    assert res.record.retries == 2                  # exactly the budget, no more
    assert calls[0] == 3                             # initial + 2 retries, then stop


def test_the_budget_cannot_be_raised_above_the_ceiling():
    verify, calls = counter(fail_times=99)
    deps, _ = make_deps(verify=verify)
    _run(run_excel_task("sheet", deps, max_retries=9999))
    assert calls[0] == A.MAX_RETRIES_CAP + 1        # clamped to the hard cap


# ── 6: tool failure ──────────────────────────────────────────────────────────
def test_a_tool_failure_is_recorded_not_hidden():
    def boom(_t, _r, _s):
        raise RuntimeError("openpyxl exploded")
    deps, _ = make_deps(run_tool=boom)
    res = _run(run_excel_task("sheet", deps, max_retries=1))
    assert res.outcome is Outcome.BUILD_FAILED
    assert res.ok is False
    assert res.url is None


def test_a_missing_dependency_is_distinct_from_a_build_failure():
    def unavailable(_t, _r, _s):
        raise ToolUnavailable("openpyxl")
    deps, _ = make_deps(run_tool=unavailable)
    res = _run(run_excel_task("sheet", deps))
    assert res.outcome is Outcome.TOOL_UNAVAILABLE


# ── 7: artifact upload failure ───────────────────────────────────────────────
def test_upload_failure_after_retries_is_delivery_failed():
    async def upload(_d, _n):
        return None, "http_500"
    deps, _ = make_deps(upload=upload)
    res = _run(run_excel_task("sheet", deps, max_retries=2))
    assert res.outcome is Outcome.DELIVERY_FAILED
    assert res.url is None
    assert res.record.verified is True              # it built and verified first
    assert res.record.retries == 2


def test_upload_fails_once_then_succeeds():
    state = {"n": 0}

    async def upload(_d, _n):
        state["n"] += 1
        return (None, "http_500") if state["n"] == 1 else ("https://cdn/x.xlsx", "ok")
    deps, _ = make_deps(upload=upload)
    res = _run(run_excel_task("sheet", deps, max_retries=2))
    assert res.outcome is Outcome.DELIVERED
    assert res.record.retries == 1


# ── 8: no fabricated success on failure ──────────────────────────────────────
@pytest.mark.parametrize("fault,expected", [
    ("verify", Outcome.VERIFY_FAILED),
    ("upload", Outcome.DELIVERY_FAILED),
])
def test_no_failure_is_ever_reported_as_success(fault, expected):
    over = {}
    if fault == "verify":
        over["verify"], _ = counter(fail_times=99)
    else:
        async def upload(_d, _n):
            return None, "http_500"
        over["upload"] = upload
    deps, _ = make_deps(**over)
    res = _run(run_excel_task("sheet", deps, max_retries=1))
    assert res.outcome is expected
    assert res.ok is False
    assert res.url is None
    assert res.message                              # a truthful message, not a file
    assert "http" not in res.message.lower() or "://" not in res.message  # no url leaked


def test_no_data_never_invents_an_artifact():
    deps, tools = make_deps(parse=lambda _q: None)
    res = _run(run_excel_task("what is xlsx", deps))
    assert res.outcome is Outcome.NO_DATA
    assert res.url is None
    assert tools == []                              # the tool was never run
    assert res.record.rows == 0 and res.record.columns == 0


# ── 9: provenance recorded ───────────────────────────────────────────────────
def test_a_digest_is_recorded_on_delivery():
    deps, _ = make_deps()
    res = _run(run_excel_task("sheet", deps))
    assert res.record.digest
    assert len(res.record.digest) == A.DIGEST_CHARS
    # It is a hash of the bytes, not the bytes.
    assert res.record.digest == __import__("hashlib").sha256(XLSX).hexdigest()[:A.DIGEST_CHARS]


def test_every_outcome_writes_exactly_one_record():
    before = len(A.recent_records(limit=200))
    deps, _ = make_deps()
    _run(run_excel_task("sheet", deps))
    after = A.recent_records(limit=200)
    assert len(after) == before + 1
    assert after[-1]["outcome"] == Outcome.DELIVERED.value
    # enum/count only — never content or identity
    assert set(after[-1]) == {
        "task_type", "strategy", "tool", "verified", "delivered_check",
        "correction_attempted", "retries", "outcome", "digest", "rows", "columns"}


# ── 10 & 12: exactly one tool, everything else refused ───────────────────────
@pytest.mark.parametrize("bad", [
    "web_search", "rag_query", "read_url", "think", "shell", "code", "",
    None, 0, "build_excel",   # wrong case is a different string, so refused
])
def test_the_executor_refuses_every_tool_but_the_excel_one(bad):
    with pytest.raises(UnapprovedTool):
        run_tool(bad, ROWS)


def test_the_approved_tool_id_and_its_string_value_both_run():
    # ToolId is a str-Enum, so the exact value "BUILD_EXCEL" resolves to the
    # same single approved tool — not a bypass, the same one tool.
    assert run_tool(ToolId.BUILD_EXCEL, ROWS)
    assert run_tool("BUILD_EXCEL", ROWS)


def test_the_only_approved_tool_runs():
    data = run_tool(ToolId.BUILD_EXCEL, ROWS)
    assert isinstance(data, (bytes, bytearray)) and len(data) > 0


def test_the_registry_holds_exactly_one_tool():
    assert list(A._TOOL_REGISTRY) == [ToolId.BUILD_EXCEL]


def test_a_gated_tool_bound_to_a_builder_is_just_as_strict():
    # The app injects its own builder through this; injecting a builder must not
    # widen what the executor may run.
    calls = []
    gate = A.gated_excel_tool(lambda rows, sheet: (calls.append(sheet) or b"PKxx"))
    assert gate(ToolId.BUILD_EXCEL, ROWS) == b"PKxx"
    assert calls == ["Data"]
    for bad in ("web_search", "rag_query", "shell", "", None):
        with pytest.raises(UnapprovedTool):
            gate(bad, ROWS)


def test_the_orchestrator_only_ever_asks_for_the_excel_tool():
    # Force several retries so the loop runs many times; every request must
    # still be for the one approved tool.
    verify, _ = counter(fail_times=2)
    deps, tools = make_deps(verify=verify)
    _run(run_excel_task("sheet", deps, max_retries=3))
    assert tools and set(tools) == {ToolId.BUILD_EXCEL}


# ── delivered-verify semantics ───────────────────────────────────────────────
def test_delivered_verify_confirms_a_matching_download():
    async def download(_url):
        return XLSX
    deps, _ = make_deps(download=download)
    res = _run(run_excel_task("sheet", deps))
    assert res.outcome is Outcome.DELIVERED
    assert res.record.delivered_check is DeliveredCheck.VERIFIED


def test_a_download_mismatch_refuses_to_claim_success():
    verify_calls = [0]

    def verify(_data, _expected):
        # local build verifies; the re-downloaded copy does not
        verify_calls[0] += 1
        return (verify_calls[0] == 1, {})
    async def download(_url):
        return b"corrupt"
    deps, _ = make_deps(verify=verify, download=download)
    res = _run(run_excel_task("sheet", deps, max_retries=1))
    assert res.outcome is Outcome.DELIVERED_VERIFY_FAILED
    assert res.record.delivered_check is DeliveredCheck.MISMATCH
    assert res.url is None


def test_a_download_that_cannot_run_is_inconclusive_not_a_failure():
    async def download(_url):
        raise ConnectionError("cdn not ready")
    deps, _ = make_deps(download=download)
    res = _run(run_excel_task("sheet", deps))
    assert res.outcome is Outcome.DELIVERED          # upload succeeded; verify inconclusive
    assert res.record.delivered_check is DeliveredCheck.INCONCLUSIVE


# ── the real downloader's host guard (boundary #12) ──────────────────────────
@pytest.mark.parametrize("url", [
    "https://res.cloudinary.com/demo/raw/upload/eva/x.xlsx",
    "https://cloudinary.com/x",
    "https://sub.res.cloudinary.com/x.xlsx",
])
def test_the_downloader_allows_the_delivery_host(url):
    assert A._is_fetchable(url) is True


@pytest.mark.parametrize("url", [
    "http://res.cloudinary.com/x.xlsx",        # not https
    "https://evilcloudinary.com/x",            # no dot boundary — not a subdomain
    "https://cloudinary.com.evil.com/x",       # suffix trick
    "https://example.com/x.xlsx",              # unrelated host
    "https://169.254.169.254/latest/meta-data",  # metadata endpoint
    "file:///etc/passwd",
    "ftp://res.cloudinary.com/x",
    "not a url", "", None, 123,
])
def test_the_downloader_refuses_anything_but_the_delivery_host(url):
    assert A._is_fetchable(url) is False


def test_the_downloader_refuses_a_bad_host_without_touching_the_network():
    # A refused URL returns None (INCONCLUSIVE upstream) and never opens a
    # client — nothing to mock, because nothing is fetched.
    assert _run(A.default_download("https://example.com/x")) is None
    assert _run(A.default_download("http://res.cloudinary.com/x")) is None


def test_delivered_verify_is_on_in_the_app_wiring(app_module):
    # The production path wires the real downloader, so delivered-verify is not
    # silently disabled by a stray download=None.
    import inspect
    src = inspect.getsource(app_module._spreadsheet_response)
    assert "download=_automation.default_download" in src


# ── 11: normal chat, and anything that is not a spreadsheet request, is
#        untouched and never even enters the automation path ──────────────────
@pytest.fixture(scope="module")
def app_module():
    try:
        import app
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"app.py not importable here: {type(exc).__name__}: {exc}")
    return app


@pytest.mark.parametrize("text", [
    "what is the capital of France",
    "explain the difference between csv and excel",
    "why is my spreadsheet slow",
    "hello",
])
def test_a_non_spreadsheet_request_never_enters_automation(app_module, text):
    """The gate is the same one that was there before. A normal question falls
    through to the ordinary answer and leaves no automation record — the path is
    entered only by an actual spreadsheet request."""
    before = len(app_module._automation.recent_records(limit=200))
    out = asyncio.run(app_module._spreadsheet_response(text))
    after = len(app_module._automation.recent_records(limit=200))
    assert out is None                     # unchanged: falls through to normal chat
    assert after == before                 # nothing was recorded


def _stub_delivery(app_module, monkeypatch):
    """Stub upload + delivered-verify so app-level tests never touch the network
    (delivered-verify now fetches the delivered URL for real)."""
    async def fake_upload(data, filename, **kw):
        return "https://res.cloudinary.com/demo/raw/upload/eva/x.xlsx", "ok"
    async def fake_download(_url, **kw):
        return None                        # INCONCLUSIVE, fast, no network
    monkeypatch.setattr(app_module, "_upload_raw", fake_upload)
    monkeypatch.setattr(app_module._automation, "default_download", fake_download)


def test_the_gate_still_recognises_a_real_request(app_module, monkeypatch):
    """The counterpart: a genuine request DOES enter the path and record one
    run. Delivery is stubbed so this does not depend on Cloudinary."""
    _stub_delivery(app_module, monkeypatch)
    before = len(app_module._automation.recent_records(limit=200))
    out = asyncio.run(app_module._spreadsheet_response(
        "create an excel sheet\nname, qty\nwidget, 10\nbolt, 4"))
    after = app_module._automation.recent_records(limit=200)
    assert out is not None and out["provider"] == "spreadsheet"
    assert out["file"]["url"].endswith(".xlsx")
    assert len(after) == before + 1
    assert after[-1]["outcome"] == Outcome.DELIVERED.value
    assert after[-1]["tool"] == ToolId.BUILD_EXCEL.value


# ── persistence to Supabase ──────────────────────────────────────────────────
def _make_record(app_module):
    A = app_module._automation
    return A.AutomationRecord(
        task_type=A.TaskType.EXCEL_FROM_TABLE, strategy="DIRECT",
        tool=A.ToolId.BUILD_EXCEL, verified=True,
        delivered_check=A.DeliveredCheck.VERIFIED, correction_attempted=False,
        retries=0, outcome=A.Outcome.DELIVERED, digest="abc0000000000000",
        rows=3, columns=2)


def test_a_persisted_row_is_enums_counts_and_a_digest_only(app_module):
    row = app_module._automation_row(_make_record(app_module))
    assert set(row) == {
        "created_at", "task_type", "strategy", "tool", "verified",
        "delivered_check", "correction_attempted", "retries", "outcome",
        "digest", "row_count", "col_count",
        # presentation columns; null for an Excel record
        "structural_check", "visual_check", "slide_count"}
    assert row["row_count"] == 3 and row["col_count"] == 2
    assert row["slide_count"] is None and row["structural_check"] is None
    blob = json.dumps(row).lower()
    for forbidden in ("prompt", "answer", "question", "user", "\"ip\"",
                      "password", "email"):
        assert forbidden not in blob


def test_persist_then_flush_posts_to_the_table_and_clears(app_module, monkeypatch):
    posted = {}
    async def fake_post(table, rows):
        posted["table"] = table
        posted["rows"] = rows
        return "ok"
    monkeypatch.setattr(app_module, "_shadow_post", fake_post)
    with app_module._automation_lock:
        app_module._automation_buffer.clear()
    app_module._automation_persist(_make_record(app_module))
    assert len(app_module._automation_buffer) == 1
    asyncio.run(app_module._automation_flush())
    assert posted["table"] == "automation_runs"
    assert len(posted["rows"]) == 1 and posted["rows"][0]["outcome"] == "DELIVERED"
    assert len(app_module._automation_buffer) == 0          # cleared on ok
    assert app_module._automation_last["code"] == "ok"


def test_a_failed_flush_rebuffers_rather_than_losing_the_run(app_module, monkeypatch):
    async def fail_post(_table, _rows):
        return "http_500"
    monkeypatch.setattr(app_module, "_shadow_post", fail_post)
    with app_module._automation_lock:
        app_module._automation_buffer.clear()
    app_module._automation_persist(_make_record(app_module))
    asyncio.run(app_module._automation_flush())
    assert len(app_module._automation_buffer) == 1          # put back, not lost
    assert app_module._automation_last["code"] == "http_500"
    with app_module._automation_lock:
        app_module._automation_buffer.clear()


def test_the_persist_buffer_is_bounded(app_module):
    with app_module._automation_lock:
        app_module._automation_buffer.clear()
    for _ in range(app_module.AUTOMATION_BUFFER_CAP + 40):
        app_module._automation_persist(_make_record(app_module))
    assert len(app_module._automation_buffer) <= app_module.AUTOMATION_BUFFER_CAP
    with app_module._automation_lock:
        app_module._automation_buffer.clear()


def test_a_real_request_enqueues_a_run_for_persistence(app_module, monkeypatch):
    _stub_delivery(app_module, monkeypatch)
    monkeypatch.setattr(app_module, "_automation_flush_due", lambda: False)  # observe the buffer
    with app_module._automation_lock:
        app_module._automation_buffer.clear()
    out = asyncio.run(app_module._spreadsheet_response(
        "create an excel sheet\nname, qty\nwidget, 10\nbolt, 4"))
    assert out is not None
    assert len(app_module._automation_buffer) == 1
    assert app_module._automation_buffer[0]["outcome"] == "DELIVERED"
    with app_module._automation_lock:
        app_module._automation_buffer.clear()


# ═══════════════════════════════════════════════════════════════════════════
# Update 39A — presentation orchestrator
# ═══════════════════════════════════════════════════════════════════════════
PPTX = b"PK\x03\x04 fake-but-non-empty pptx bytes"


class _Plan:
    """A stand-in plan; the orchestrator treats plans as opaque."""
    def __init__(self, slide_count=5):
        self.slide_count = slide_count


def make_pres_deps(**over):
    tools_seen = []

    def parse(_q):
        return over.pop("plan", _Plan(5))

    def run_tool_fake(tool_id, plan):
        tools_seen.append(tool_id)
        return PPTX

    def verify_structure(_data, _plan):
        return True, {"reason": "ok"}

    def verify_layout(_data):
        return True, {"render_clipping": "UNAVAILABLE"}

    async def upload(_data, _name):
        return "https://res.cloudinary.com/demo/raw/upload/eva/x.pptx", "ok"

    def digest(data):
        import hashlib
        return hashlib.sha256(data).hexdigest()[:16]

    deps = A.PresentationDeps(
        parse=over.pop("parse", parse),
        run_tool=over.pop("run_tool", run_tool_fake),
        verify_structure=over.pop("verify_structure", verify_structure),
        verify_layout=over.pop("verify_layout", verify_layout),
        upload=over.pop("upload", upload),
        digest=over.pop("digest", digest),
        strategy=over.pop("strategy", lambda _q: "DIRECT"),
        slide_count_of=over.pop("slide_count_of", lambda p: p.slide_count),
        download=over.pop("download", None),
    )
    assert not over, f"unknown deps override: {list(over)}"
    return deps, tools_seen


def pres_counter(fail_times, then=(True, {"reason": "ok"})):
    calls = [0]

    def fn(*_a, **_k):
        calls[0] += 1
        return (False, {"reason": "bad"}) if calls[0] <= fail_times else then
    return fn, calls


def test_presentation_happy_path():
    deps, tools = make_pres_deps()
    res = _run(A.run_presentation_task("make a deck", deps))
    assert res.outcome is Outcome.DELIVERED and res.ok
    assert res.url.endswith(".pptx")
    assert res.record.structural_check is A.CheckResult.PASS
    assert res.record.visual_check is A.CheckResult.PASS
    assert res.record.verified is True
    assert res.record.slide_count == 5
    assert tools == [ToolId.BUILD_POWERPOINT]


def test_a_real_deck_is_built_and_structurally_verified():
    import presentation as P

    async def upload(_d, _n):
        return "https://res.cloudinary.com/demo/raw/upload/eva/real.pptx", "ok"
    deps = A.PresentationDeps(
        parse=P.parse_presentation_spec, run_tool=A.run_pptx_tool,
        verify_structure=P.verify_pptx_structure, verify_layout=P.verify_pptx_layout,
        upload=upload, digest=A._digest_bytes, strategy=lambda _q: "DIRECT",
        slide_count_of=lambda p: p.slide_count, download=None)
    q = "create a presentation about the Bridge Study\n## Findings\n- Peak stress 180 MPa\n## Next\n- Approve"
    res = _run(A.run_presentation_task(q, deps))
    assert res.outcome is Outcome.DELIVERED
    assert res.record.structural_check is A.CheckResult.PASS
    assert res.record.visual_check is A.CheckResult.PASS
    assert res.record.digest and res.record.slide_count >= 3


def test_no_content_asks_and_never_runs_the_tool():
    deps, tools = make_pres_deps(parse=lambda _q: None)
    res = _run(A.run_presentation_task("make me a powerpoint", deps))
    assert res.outcome is Outcome.NO_CONTENT
    assert res.url is None and res.message and tools == []


def test_persistent_structural_failure_stops_honestly():
    always, _ = pres_counter(99)
    deps, _ = make_pres_deps(verify_structure=always)
    res = _run(A.run_presentation_task("deck", deps, max_retries=2))
    assert res.outcome is Outcome.STRUCTURAL_FAILED
    assert res.url is None and res.record.verified is False
    assert res.record.correction_attempted is True


def test_structural_fails_once_then_a_retry_succeeds():
    verify, calls = pres_counter(1)
    deps, _ = make_pres_deps(verify_structure=verify)
    res = _run(A.run_presentation_task("deck", deps, max_retries=2))
    assert res.outcome is Outcome.DELIVERED
    assert res.record.retries == 1 and calls[0] == 2


def test_persistent_visual_failure_stops_honestly():
    always, _ = pres_counter(99)
    deps, _ = make_pres_deps(verify_layout=always)
    res = _run(A.run_presentation_task("deck", deps, max_retries=2))
    assert res.outcome is Outcome.VISUAL_FAILED
    assert res.record.visual_check is A.CheckResult.FAIL
    assert res.url is None


def test_visual_check_unavailable_does_not_fail_the_task():
    def raises(_data):
        raise RuntimeError("layout inspector exploded")
    deps, _ = make_pres_deps(verify_layout=raises)
    res = _run(A.run_presentation_task("deck", deps))
    assert res.outcome is Outcome.DELIVERED
    assert res.record.visual_check is A.CheckResult.UNAVAILABLE


def test_presentation_retry_budget_is_bounded():
    always, calls = pres_counter(99)
    deps, _ = make_pres_deps(verify_structure=always)
    res = _run(A.run_presentation_task("deck", deps, max_retries=2))
    assert res.record.retries == 2 and calls[0] == 3


def test_presentation_tool_failure_is_recorded():
    def boom(_t, _p):
        raise RuntimeError("pptx exploded")
    deps, _ = make_pres_deps(run_tool=boom)
    res = _run(A.run_presentation_task("deck", deps, max_retries=1))
    assert res.outcome is Outcome.BUILD_FAILED and res.url is None


def test_presentation_missing_library_is_tool_unavailable():
    def unavail(_t, _p):
        raise A.ToolUnavailable("pptx")
    deps, _ = make_pres_deps(run_tool=unavail)
    res = _run(A.run_presentation_task("deck", deps))
    assert res.outcome is Outcome.TOOL_UNAVAILABLE


def test_presentation_upload_failure_is_delivery_failed():
    async def upload(_d, _n):
        return None, "http_500"
    deps, _ = make_pres_deps(upload=upload)
    res = _run(A.run_presentation_task("deck", deps, max_retries=2))
    assert res.outcome is Outcome.DELIVERY_FAILED and res.url is None
    assert res.record.verified is True


def test_a_delivered_deck_that_does_not_reopen_is_not_claimed_delivered():
    struct_calls = [0]

    def verify_structure(_data, _plan):
        struct_calls[0] += 1
        return (struct_calls[0] == 1, {})       # local ok; delivered copy fails
    async def download(_url):
        return b"corrupt"
    deps, _ = make_pres_deps(verify_structure=verify_structure, download=download)
    res = _run(A.run_presentation_task("deck", deps, max_retries=1))
    assert res.outcome is Outcome.DELIVERED_VERIFY_FAILED
    assert res.record.delivered_check is DeliveredCheck.MISMATCH
    assert res.url is None


def test_delivered_verify_confirms_a_matching_pptx():
    async def download(_url):
        return PPTX
    deps, _ = make_pres_deps(download=download)
    res = _run(A.run_presentation_task("deck", deps))
    assert res.outcome is Outcome.DELIVERED
    assert res.record.delivered_check is DeliveredCheck.VERIFIED


@pytest.mark.parametrize("bad", ["web_search", "BUILD_EXCEL", "shell", "", None])
def test_the_pptx_gate_refuses_every_tool_but_powerpoint(bad):
    with pytest.raises(UnapprovedTool):
        A.run_pptx_tool(bad, _Plan())


def test_a_gated_pptx_tool_bound_to_a_builder_is_just_as_strict():
    calls = []
    gate = A.gated_powerpoint_tool(lambda plan: (calls.append(1) or PPTX))
    assert gate(ToolId.BUILD_POWERPOINT, _Plan()) == PPTX
    for bad in ("web_search", ToolId.BUILD_EXCEL, None):
        with pytest.raises(UnapprovedTool):
            gate(bad, _Plan())


def test_the_presentation_orchestrator_only_asks_for_powerpoint():
    verify, _ = pres_counter(2)
    deps, tools = make_pres_deps(verify_structure=verify)
    _run(A.run_presentation_task("deck", deps, max_retries=3))
    assert tools and set(tools) == {ToolId.BUILD_POWERPOINT}


def test_presentation_record_is_privacy_safe():
    deps, _ = make_pres_deps()
    res = _run(A.run_presentation_task("deck", deps))
    row = res.record.model_dump()
    assert set(row) == {
        "task_type", "strategy", "tool", "verified", "structural_check",
        "visual_check", "delivered_check", "correction_attempted", "retries",
        "outcome", "digest", "slide_count"}
    blob = json.dumps(row, default=str).lower()
    for forbidden in ("prompt", "answer", "question", "\"user\"", "\"ip\"",
                      "password", "email"):
        assert forbidden not in blob


@pytest.mark.parametrize("fault,expected", [
    ("structural", Outcome.STRUCTURAL_FAILED),
    ("visual", Outcome.VISUAL_FAILED),
    ("upload", Outcome.DELIVERY_FAILED),
])
def test_no_presentation_failure_is_reported_as_success(fault, expected):
    over = {}
    if fault == "structural":
        over["verify_structure"], _ = pres_counter(99)
    elif fault == "visual":
        over["verify_layout"], _ = pres_counter(99)
    else:
        async def upload(_d, _n):
            return None, "http_500"
        over["upload"] = upload
    deps, _ = make_pres_deps(**over)
    res = _run(A.run_presentation_task("deck", deps, max_retries=1))
    assert res.outcome is expected and not res.ok and res.url is None
    assert res.message


# ── app-level: the presentation gate and telemetry ──────────────────────────
def _stub_pptx_delivery(app_module, monkeypatch):
    async def fake_upload(data, filename, **kw):
        return "https://res.cloudinary.com/demo/raw/upload/eva/deck.pptx", "ok"
    async def fake_download(_url, **kw):
        return None
    monkeypatch.setattr(app_module, "_upload_raw", fake_upload)
    monkeypatch.setattr(app_module._automation, "default_download", fake_download)


@pytest.mark.parametrize("text", [
    "what is the capital of France",
    "create an excel sheet from this data",
    "how do i open a pptx",
])
def test_a_non_presentation_request_never_enters_the_deck_path(app_module, text):
    before = len(app_module._automation.recent_records(limit=200))
    out = asyncio.run(app_module._presentation_response(text))
    after = len(app_module._automation.recent_records(limit=200))
    assert out is None and after == before


def test_a_real_presentation_request_delivers_and_records(app_module, monkeypatch):
    _stub_pptx_delivery(app_module, monkeypatch)
    before = len(app_module._automation.recent_records(limit=200))
    out = asyncio.run(app_module._presentation_response(
        "create a presentation about the Q3 Review\n## Sales\n- Up 8 percent\n## Risk\n- Churn 2 percent"))
    after = app_module._automation.recent_records(limit=200)
    assert out is not None and out["provider"] == "presentation"
    assert out["file"]["url"].endswith(".pptx") and out["file"]["kind"] == "pptx"
    assert len(after) == before + 1
    assert after[-1]["outcome"] == Outcome.DELIVERED.value
    assert after[-1]["tool"] == ToolId.BUILD_POWERPOINT.value


def test_a_contentless_deck_request_asks_and_records_no_content(app_module):
    out = asyncio.run(app_module._presentation_response("make me a powerpoint"))
    assert out is not None and out["provider"] == "presentation"
    assert "file" not in out
    assert app_module._automation.recent_records(limit=1)[-1]["outcome"] == "NO_CONTENT"


def test_the_endpoint_reports_persistence_status(app_module, monkeypatch):
    # No creds → no network, deterministic; the endpoint still answers with a
    # clear persistence block.
    monkeypatch.setattr(app_module, "_shadow_supabase", lambda: None)
    out = asyncio.run(app_module.api_health_automation(limit=5))
    assert out["available"] is True
    assert out["approved_tools"] == ["BUILD_EXCEL", "BUILD_POWERPOINT"]
    assert out["persistence"]["configured"] is False
    assert out["persistence"]["read"] == "not_configured"
    assert "pending_unflushed" in out["persistence"]
    assert out["persisted"] == []           # nothing durable read without creds
    assert "in_memory_recent" in out
