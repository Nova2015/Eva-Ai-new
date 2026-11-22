"""Tests for real .xlsx generation.

The failure this replaces: asked to create an Excel sheet, EVA explained what
CSV and XLSX are; asked again, it generated a PNG that looks like a
spreadsheet. So the properties that matter are

  1. The file actually opens, checked by reading it back — not by trusting
     that the writer did not raise.
  2. Every value in it came from the user. A spreadsheet with invented rows is
     worse than invented prose: it looks authoritative and gets forwarded.
  3. A question ABOUT spreadsheets is not a request FOR one.
"""

import pytest

try:
    from spreadsheet import (
        MAX_COLS, looks_like_spreadsheet_request, parse_table,
        build_workbook, verify_workbook, safe_sheet_name,
    )
except ImportError:  # running from the repo root
    from src.spreadsheet import (  # type: ignore
        MAX_COLS, looks_like_spreadsheet_request, parse_table,
        build_workbook, verify_workbook, safe_sheet_name,
    )


CSV = "name, qty, price\nwidget, 10, 2.5\nbolt, 4, 0.75"
PIPE = "| name | qty |\n| --- | --- |\n| widget | 10 |\n| bolt | 4 |"


# ── A: asking for a file vs asking about files ───────────────────────────────
@pytest.mark.parametrize("text", [
    "create an excel sheet from this data",
    "make me a spreadsheet",
    "generate an xlsx of the results",
    "export this to excel",
    "convert this data to a spreadsheet",
    "build a workbook from these rows",
    "give me an excel file",
])
def test_a_request_for_a_file_is_recognised(text):
    assert looks_like_spreadsheet_request(text) is True


@pytest.mark.parametrize("text", [
    # The message from the screenshot that started Update 35. Verified on the
    # live page: the image guard declined it, but bare-verb matching meant the
    # spreadsheet path did not pick it up either, so the user got matplotlib
    # code. Both halves have to recognise it, not just one.
    "Creating image for excel sheet for all data set",
    "creating an excel sheet",
    "making a spreadsheet from this",
    "generating an xlsx report",
    "exporting these rows to excel",
    "building a workbook",
    "downloading this as a spreadsheet",
])
def test_the_ing_form_is_a_request_too(text):
    assert looks_like_spreadsheet_request(text) is True


@pytest.mark.parametrize("text", [
    "Excel sheet downloaded format",          # the actual screenshot
    "what is xlsx",
    "which format should I use for download",
    "explain the difference between csv and excel",
    "why is my spreadsheet slow",
    "when was excel released",
    "",
])
def test_a_question_about_spreadsheets_is_not_a_request(text):
    """Answering "what is xlsx" with a generated file is as wrong as answering
    "make me a sheet" with a paragraph about file formats."""
    assert looks_like_spreadsheet_request(text) is False


@pytest.mark.parametrize("text", [
    "what format should I use to create an excel sheet",
    "which tool can generate a spreadsheet",
    "why would I export this to excel",
    "explain how to build a workbook",
])
def test_a_question_that_also_mentions_creating_is_still_a_question(text):
    """These match the request pattern AND the question pattern, so only the
    question guard can separate them. The earlier cases did not reach it: they
    failed the positive pattern too, so deleting the guard changed nothing and
    a mutation removing it survived."""
    assert looks_like_spreadsheet_request(text) is False


def test_a_very_long_message_is_not_treated_as_a_file_request():
    assert looks_like_spreadsheet_request("create an excel sheet " + "x" * 4000) is False


# ── B: the data comes from the user ──────────────────────────────────────────
def test_csv_rows_are_parsed():
    assert parse_table(CSV) == [["name", "qty", "price"],
                                ["widget", 10, 2.5],
                                ["bolt", 4, 0.75]]


def test_a_markdown_table_is_parsed_and_its_rule_row_dropped():
    assert parse_table(PIPE) == [["name", "qty"], ["widget", 10], ["bolt", 4]]


def test_numbers_become_numbers_so_the_sheet_can_be_summed():
    rows = parse_table(CSV)
    assert isinstance(rows[1][1], int)
    assert isinstance(rows[1][2], float)


def test_thousands_separators_are_understood_where_they_are_unambiguous():
    """Only in pipe and tab tables. In comma-delimited text "1,234" is two
    fields by definition, and guessing otherwise would silently merge real
    columns — the comma cannot be both a delimiter and a grouping mark."""
    assert parse_table("| a | b |\n| x | 1,234 |")[1][1] == 1234
    assert parse_table("a\tb\nx\t1,234")[1][1] == 1234


def test_a_comma_inside_csv_is_a_delimiter_not_a_grouping_mark():
    rows = parse_table("a, b, c\nx, 1,234")
    assert rows[1] == ["x", 1, 234]


def test_prose_with_no_table_yields_nothing():
    """None, not an empty table: the caller must be able to ask for the data
    rather than hand back an empty workbook."""
    assert parse_table("please make me an excel sheet of everything") is None
    assert parse_table("") is None
    assert parse_table(None) is None


def test_a_header_alone_is_not_a_table():
    assert parse_table("name, qty") is None


def test_ragged_rows_become_a_rectangle():
    rows = parse_table("a, b, c\n1, 2\n3, 4, 5")
    assert all(len(r) == 3 for r in rows)


def test_column_count_is_capped():
    wide = ",".join(str(i) for i in range(200))
    rows = parse_table(f"{wide}\n{wide}")
    assert len(rows[0]) <= MAX_COLS


# ── C: the file opens, and says what we put in it ────────────────────────────
def test_the_workbook_opens_and_round_trips():
    rows = parse_table(CSV)
    ok, report = verify_workbook(build_workbook(rows), rows)
    assert ok is True
    assert report["opened"] is True
    assert report["rows"] == 3 and report["cols"] == 3
    assert report["matches_expected"] is True


def test_verification_rejects_bytes_that_are_not_a_workbook():
    """The check must be "it opens", not "we produced something"."""
    ok, report = verify_workbook(b"this is not an xlsx", [["a", "b"]])
    assert ok is False
    assert report["opened"] is False
    assert report["reason"].startswith("unreadable")


def test_verification_rejects_an_empty_payload():
    ok, report = verify_workbook(b"", [["a", "b"]])
    assert ok is False and report["reason"] == "empty"


def test_verification_notices_a_missing_row():
    rows = parse_table(CSV)
    data = build_workbook(rows[:2])
    ok, report = verify_workbook(data, rows)
    assert ok is False and report["reason"] == "shape_mismatch"


def test_verification_notices_a_changed_value():
    rows = parse_table(CSV)
    data = build_workbook(rows)
    tampered = [list(r) for r in rows]
    tampered[1][1] = 999
    ok, report = verify_workbook(data, tampered)
    assert ok is False and report["reason"] == "cell_mismatch"


def test_building_nothing_is_refused():
    with pytest.raises(ValueError):
        build_workbook([])


# ── D: sheet names Excel will accept ─────────────────────────────────────────
@pytest.mark.parametrize("raw,expected_ok", [
    ("Sales 2026", True), ("a/b:c*d?e[f]g", True), ("", True), ("x" * 80, True),
])
def test_sheet_names_are_made_legal(raw, expected_ok):
    name = safe_sheet_name(raw)
    assert 0 < len(name) <= 31
    assert not set(name) & set("[]:*?/\\")


def test_a_workbook_with_an_awkward_title_still_opens():
    rows = parse_table(CSV)
    data = build_workbook(rows, sheet_name="Q1/Q2 [draft]: results?")
    ok, _ = verify_workbook(data, rows)
    assert ok is True
