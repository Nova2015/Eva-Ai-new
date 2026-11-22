"""Tests for the /chat spreadsheet path.

The behaviour being replaced, from real screenshots:

    "Excel sheet downloaded format"          -> a paragraph about CSV and XML
    "Creating image for excel sheet ..."     -> a PNG that looks like a sheet

So the properties are: an explicit request with data produces a real file, a
question about spreadsheets does not, and anything uncertain falls through to
the normal answer rather than returning a broken download.
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


def _run(coro):
    import asyncio
    return asyncio.run(coro)


def _ask(app_module, text):
    return _run(app_module._spreadsheet_response(text))


CSV_REQUEST = ("create an excel sheet from this data\n"
               "name, qty, price\nwidget, 10, 2.5\nbolt, 4, 0.75")


# ── A: it must not hijack questions ──────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "Excel sheet downloaded format",       # the screenshot, verbatim
    "what is the difference between csv and xlsx",
    "which download format should I use",
    "explain spreadsheets",
    "hello",
])
def test_a_question_falls_through_to_the_normal_answer(app_module, text):
    assert _ask(app_module, text) is None


# ── B: asked for a file with no data ─────────────────────────────────────────
def test_a_request_without_data_asks_for_it(app_module):
    """It must not invent rows. A spreadsheet of made-up numbers looks
    authoritative and gets forwarded to other people."""
    out = _ask(app_module, "create an excel sheet for me")
    assert out is not None
    assert out["provider"] == "spreadsheet"
    assert "file" not in out
    assert "paste the data" in out["answer"].lower()


# ── C: the whole path, with delivery stubbed ─────────────────────────────────
def test_a_real_file_is_produced_and_linked(app_module, monkeypatch):
    seen = {}

    async def fake_upload(data, filename, **kw):
        seen["bytes"] = data
        seen["filename"] = filename
        return "https://res.cloudinary.com/demo/raw/upload/eva/x.xlsx", "ok"

    monkeypatch.setattr(app_module, "_upload_raw", fake_upload)
    out = _ask(app_module, CSV_REQUEST)

    assert out is not None and out["provider"] == "spreadsheet"
    assert out["file"]["url"].endswith(".xlsx")
    assert out["file"]["rows"] == 2 and out["file"]["columns"] == 3
    assert out["file"]["url"] in out["answer"]
    # What was uploaded is a genuine workbook, not a description of one.
    assert seen["bytes"][:2] == b"PK"
    assert seen["filename"].endswith(".xlsx")


def test_the_uploaded_bytes_open_and_contain_the_user_values(app_module, monkeypatch):
    """The file the user downloads is the file we verified, so this reads back
    the exact bytes that were sent to delivery."""
    captured = {}

    async def fake_upload(data, filename, **kw):
        captured["data"] = data
        return "https://example.invalid/x.xlsx", "ok"

    monkeypatch.setattr(app_module, "_upload_raw", fake_upload)
    _ask(app_module, CSV_REQUEST)

    import io
    from openpyxl import load_workbook
    ws = load_workbook(io.BytesIO(captured["data"]), read_only=True).active
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    assert rows[0] == ["name", "qty", "price"]
    assert rows[1] == ["widget", 10, 2.5]


# ── D: every failure falls through rather than shipping a bad download ───────
def test_a_failed_upload_falls_through(app_module, monkeypatch):
    async def failing(data, filename, **kw):
        return None, "http_401"

    monkeypatch.setattr(app_module, "_upload_raw", failing)
    assert _ask(app_module, CSV_REQUEST) is None


def test_unconfigured_delivery_falls_through(app_module, monkeypatch):
    monkeypatch.delenv("CLOUDINARY_URL", raising=False)
    assert _ask(app_module, CSV_REQUEST) is None


def test_a_workbook_that_fails_verification_is_never_shipped(app_module, monkeypatch):
    """Verification is the guard against handing over a file that will not
    open. If it fails, no link may be returned."""
    monkeypatch.setattr(app_module, "_verify_workbook",
                        lambda data, rows: (False, {"reason": "shape_mismatch"}))

    async def fake_upload(data, filename, **kw):  # pragma: no cover
        raise AssertionError("upload attempted after failed verification")

    monkeypatch.setattr(app_module, "_upload_raw", fake_upload)
    assert _ask(app_module, CSV_REQUEST) is None


def test_a_build_error_falls_through(app_module, monkeypatch):
    def boom(rows, sheet_name="Data"):
        raise RuntimeError("openpyxl exploded")

    monkeypatch.setattr(app_module, "_build_workbook", boom)
    assert _ask(app_module, CSV_REQUEST) is None


# ── E: no credential ever reaches the reply ──────────────────────────────────
def test_the_answer_carries_no_credential(app_module, monkeypatch):
    monkeypatch.setenv("CLOUDINARY_URL",
                       "cloudinary://KEYLEAK:SECRETLEAK@democloud")

    async def fake_upload(data, filename, **kw):
        return "https://res.cloudinary.com/democloud/raw/upload/eva/x.xlsx", "ok"

    monkeypatch.setattr(app_module, "_upload_raw", fake_upload)
    blob = repr(_ask(app_module, CSV_REQUEST))
    assert "KEYLEAK" not in blob and "SECRETLEAK" not in blob
