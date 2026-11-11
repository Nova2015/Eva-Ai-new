"""Build a real .xlsx from data the user supplied, and prove it opens.

Update 35a. Asked to "create an Excel sheet", EVA explained what CSV and XLSX
are; asked to create one "for all data set", it generated a PNG that looks like
a spreadsheet. The user gets a picture of a file instead of a file.

THE DATA COMES FROM THE USER, NEVER FROM A MODEL. Same rule the deterministic
chart path already follows: parse the numbers and labels the message actually
contains and put exactly those in the sheet. A spreadsheet is a document people
act on — invented rows are worse here than in prose, because a table looks
authoritative and gets forwarded.

VERIFICATION IS NOT OPTIONAL. build_workbook writes bytes; verify_workbook
opens those bytes back with a fresh reader and checks the shape and the cell
values round-tripped. "The library did not raise" is not evidence a file
opens — that is exactly the assumption that produced an image of a spreadsheet
and called it done.

Pure: no network, no filesystem, no app imports. Delivery lives in app.py.
"""

import io
import re
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "MAX_ROWS", "MAX_COLS",
    "looks_like_spreadsheet_request", "parse_table",
    "build_workbook", "verify_workbook", "safe_sheet_name",
]

# Bounded so a malformed message cannot ask for a workbook that exhausts memory
# on a free-tier container. Well above any table a person types into chat.
MAX_ROWS = 5000
MAX_COLS = 64

# An explicit ask for a file, not a question about file formats. "what is xlsx"
# and "which format should I download" must not fire: answering those with a
# generated file is as wrong as answering a file request with prose.
_REQUEST_RE = re.compile(
    # -ing forms too. The message that motivated this whole update opens with
    # "Creating image for excel sheet", and bare-verb matching missed it: the
    # image guard correctly declined to take it, the spreadsheet path did not
    # pick it up, and the user got matplotlib code instead of a file.
    r"\b(creat(?:e|ing)|mak(?:e|ing)|generat(?:e|ing)|build(?:ing)?|"
    r"export(?:ing)?|convert(?:ing)?|give\s+me|download(?:ing)?)\b[^.?!]*"
    r"\b(excel|xlsx|spreadsheet|workbook|sheet)\b",
    re.IGNORECASE,
)
_NOT_A_REQUEST_RE = re.compile(
    r"\b(what|which|why|when|explain|difference|format\s+may|meaning)\b",
    re.IGNORECASE,
)


def looks_like_spreadsheet_request(text: str) -> bool:
    """Whether the message asks for a spreadsheet FILE to be produced."""
    s = (text or "").strip()
    if not s or len(s) > 4000:
        return False
    if _NOT_A_REQUEST_RE.search(s):
        return False
    return bool(_REQUEST_RE.search(s))


def _split_row(line: str) -> List[str]:
    """Cells from one line, accepting the three shapes people actually type."""
    stripped = line.strip().strip("|").strip()
    if "|" in line:
        return [c.strip() for c in stripped.split("|")]
    if "\t" in line:
        return [c.strip() for c in line.split("\t")]
    return [c.strip() for c in stripped.split(",")]


_SEPARATOR_RE = re.compile(r"^[\s|:\-+]+$")


def _coerce(value: str) -> Any:
    """Numbers as numbers, so the sheet can be summed rather than only read."""
    v = (value or "").strip()
    if not v:
        return ""
    cleaned = v.replace(",", "") if re.fullmatch(r"-?[\d,]+(\.\d+)?", v) else v
    try:
        if re.fullmatch(r"-?\d+", cleaned):
            return int(cleaned)
        if re.fullmatch(r"-?\d*\.\d+", cleaned):
            return float(cleaned)
    except ValueError:
        pass
    return v


def parse_table(text: str) -> Optional[List[List[Any]]]:
    """Tabular data found in the message, or None.

    None means "no data here" and must stay distinguishable from an empty
    table: the caller has to be able to say "I need the data" rather than
    hand over an empty workbook.
    """
    if not text:
        return None

    rows: List[List[Any]] = []
    width = 0
    for line in text.splitlines():
        if not line.strip() or _SEPARATOR_RE.fullmatch(line.strip()):
            continue
        if not any(sep in line for sep in ("|", "\t", ",")):
            continue
        cells = [c for c in _split_row(line)]
        if len([c for c in cells if c != ""]) < 2:
            continue
        rows.append([_coerce(c) for c in cells[:MAX_COLS]])
        width = max(width, len(rows[-1]))
        if len(rows) >= MAX_ROWS:
            break

    if len(rows) < 2:          # a header alone is not a table
        return None

    for row in rows:           # ragged input becomes a rectangle
        row.extend([""] * (width - len(row)))
    return rows


_INVALID_SHEET = re.compile(r"[\[\]:*?/\\]")


def safe_sheet_name(name: str) -> str:
    """Excel rejects some characters outright and caps the name at 31 chars.
    A sheet name taken from user text would otherwise fail at write time."""
    cleaned = _INVALID_SHEET.sub(" ", (name or "").strip()) or "Sheet1"
    return cleaned[:31]


def build_workbook(rows: List[List[Any]], sheet_name: str = "Sheet1") -> bytes:
    """An .xlsx containing exactly `rows`. Raises on empty input."""
    if not rows:
        raise ValueError("refusing to build an empty workbook")

    from openpyxl import Workbook          # imported late: optional dependency
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = safe_sheet_name(sheet_name)

    for row in rows[:MAX_ROWS]:
        ws.append(list(row)[:MAX_COLS])

    for cell in ws[1]:                     # first row reads as a header
        cell.font = Font(bold=True)

    for i, _ in enumerate(rows[0][:MAX_COLS], start=1):
        longest = max(
            (len(str(r[i - 1])) for r in rows[:200] if len(r) >= i), default=8)
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = \
            min(max(longest + 2, 8), 60)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def verify_workbook(data: bytes, expected: List[List[Any]]) -> Tuple[bool, Dict[str, Any]]:
    """Open the bytes back and confirm they are the workbook we meant to make.

    Reads with a fresh loader rather than trusting the writer. A file that
    cannot be opened is the failure users would hit, and it is invisible from
    the writing side.
    """
    report: Dict[str, Any] = {"opened": False, "rows": 0, "cols": 0,
                              "matches_expected": False, "reason": ""}
    if not data:
        report["reason"] = "empty"
        return False, report

    try:
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True)
        ws = wb.active
        got = [list(r) for r in ws.iter_rows(values_only=True)]
    except Exception as exc:
        report["reason"] = f"unreadable_{type(exc).__name__}"
        return False, report

    report["opened"] = True
    report["rows"] = len(got)
    report["cols"] = max((len(r) for r in got), default=0)

    want_rows = len(expected[:MAX_ROWS])
    want_cols = max((len(r[:MAX_COLS]) for r in expected), default=0)
    if report["rows"] != want_rows or report["cols"] != want_cols:
        report["reason"] = "shape_mismatch"
        return False, report

    for r_i, want_row in enumerate(expected[:MAX_ROWS]):
        for c_i, want in enumerate(want_row[:MAX_COLS]):
            got_cell = got[r_i][c_i]
            if (got_cell if got_cell is not None else "") != want:
                report["reason"] = "cell_mismatch"
                return False, report

    report["matches_expected"] = True
    return True, report
