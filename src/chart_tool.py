"""Turn a table the user pasted into a chart whose every value is theirs.

Update 35a. The deterministic chart path already refuses to invent data, but it
can only read inline pairs like "A=40, B=30". Given an actual table — the way
people paste data — it extracts nothing, falls through to the model, and from
there to whatever interceptor grabs the message first. That is how "make a
chart of this data" ended up at an image generator and produced a picture.

Three things this adds, and the middle one is the point:

  TABLES AS INPUT. The same parse_table used to build spreadsheets, so a CSV
  or markdown table becomes a chart with exact values.

  VERIFICATION. Every label and value in the emitted spec must be traceable to
  a row of the source. Charts have been held to a lower standard than files:
  the workbook path re-opens the bytes and compares every cell, while the chart
  path emitted a spec and trusted the parser. A chart with one wrong bar is as
  wrong as a spreadsheet with one wrong cell, and harder to notice.

  TYPE INFERENCE. Only when the user did not say. An explicit "pie chart"
  always wins; guessing over a stated preference would be a worse failure than
  guessing over silence.

Pure module: no I/O, no app imports.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "ALLOWED_TYPES", "MAX_POINTS",
    "infer_chart_type", "spec_from_table", "verify_chart",
]

# What the frontend renderer can actually draw. Emitting anything else produces
# a fenced block that silently fails to render.
ALLOWED_TYPES = ("pie", "bar", "line", "scatter")

# A chart with more points than this is unreadable, and truncating silently
# would misrepresent the data — the caller is told to refuse instead.
MAX_POINTS = 60

_TIME_HEADER_RE = re.compile(
    r"\b(year|month|date|day|week|quarter|time|period)\b", re.IGNORECASE)
_TIME_VALUE_RE = re.compile(
    r"^(19|20)\d{2}$|^(q[1-4])$|"
    r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", re.IGNORECASE)
_SHARE_HEADER_RE = re.compile(
    r"\b(share|percent|percentage|proportion|split|distribution|%)\b",
    re.IGNORECASE)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _columns(rows: List[List[Any]]) -> Tuple[List[str], List[List[Any]]]:
    header = [str(c) for c in rows[0]]
    return header, rows[1:]


def _pick_columns(rows: List[List[Any]]) -> Optional[Tuple[int, int]]:
    """(label column, value column), or None if there is no numeric column.

    The value column must be numeric in the DATA rows, not the header — a
    header is text by definition, and reading it as a value is how a chart
    gains a bar labelled "qty".
    """
    _, body = _columns(rows)
    if not body:
        return None
    width = max(len(r) for r in body)

    numeric = [c for c in range(width)
               if body and all(_is_number(r[c]) for r in body if len(r) > c)]
    if not numeric:
        return None

    label_candidates = [c for c in range(width) if c not in numeric]
    if label_candidates:
        return label_candidates[0], numeric[0]

    # Every column is numeric — a year axis, or two measurements. The FIRST
    # column is the independent one by convention, so it labels and the next
    # numeric column supplies the values. Reading them the other way round
    # plotted revenue along the bottom and years up the side.
    if len(numeric) < 2:
        return None
    return numeric[0], numeric[1]


def infer_chart_type(rows: List[List[Any]], requested: Optional[str] = None) -> str:
    """The chart type to draw. An explicit request always wins."""
    if requested and requested.lower() in ALLOWED_TYPES:
        return requested.lower()

    picked = _pick_columns(rows)
    if not picked:
        return "bar"
    label_col, value_col = picked
    header, body = _columns(rows)
    label_header = header[label_col] if label_col < len(header) else ""
    labels = [r[label_col] for r in body if len(r) > label_col]

    # A time axis reads as a progression, so connect the points. Checked BEFORE
    # the numeric test: years parse as integers, so "2021, 2022, 2023" looks
    # exactly like a second measurement and was being drawn as a scatter.
    if _TIME_HEADER_RE.search(label_header) or (
            labels and all(_TIME_VALUE_RE.match(str(v).strip()) for v in labels)):
        return "line"

    # Both axes numeric and neither is time: the relationship is the point.
    if _is_number(labels[0] if labels else None):
        return "scatter"

    # Parts of a whole, and few enough that slices stay legible.
    value_header = header[value_col] if value_col < len(header) else ""
    if _SHARE_HEADER_RE.search(value_header) and len(labels) <= 8:
        return "pie"

    return "bar"


def spec_from_table(rows: List[List[Any]], requested_type: Optional[str] = None,
                    title: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """A chart spec built only from `rows`, or None if no chart is possible.

    None rather than a best effort: a chart drawn from data that could not be
    read is a confident picture of nothing.
    """
    if not rows or len(rows) < 2:
        return None
    picked = _pick_columns(rows)
    if not picked:
        return None
    label_col, value_col = picked

    header, body = _columns(rows)
    if len(body) > MAX_POINTS:
        return None

    data = []
    for row in body:
        if len(row) <= max(label_col, value_col):
            continue
        label = str(row[label_col]).strip()
        value = row[value_col]
        if not label or not _is_number(value):
            continue
        data.append({"label": label, "value": value})

    if not data:
        return None

    chart_title = (title or (header[value_col] if value_col < len(header) else "")
                   or "Chart").strip()
    return {
        "type": infer_chart_type(rows, requested_type),
        "title": chart_title,
        "data": data,
    }


def verify_chart(spec: Optional[Dict[str, Any]],
                 rows: List[List[Any]]) -> Tuple[bool, Dict[str, Any]]:
    """Confirm every point in `spec` came from `rows`.

    Held to the same standard as the workbook round-trip: it is not enough that
    a spec was produced, every label and value has to be traceable to a source
    row. A chart is read as fact and forwarded; one wrong bar is a wrong claim.
    """
    report: Dict[str, Any] = {"points": 0, "reason": ""}
    if not isinstance(spec, dict):
        report["reason"] = "no_spec"
        return False, report

    if spec.get("type") not in ALLOWED_TYPES:
        report["reason"] = "unrenderable_type"
        return False, report

    data = spec.get("data")
    if not isinstance(data, list) or not data:
        report["reason"] = "no_data"
        return False, report
    report["points"] = len(data)

    # Every (label, value) the source could legitimately produce.
    allowed = set()
    for row in rows[1:]:
        for label_i, label in enumerate(row):
            for value_i, value in enumerate(row):
                if label_i != value_i and _is_number(value):
                    allowed.add((str(label).strip(), float(value)))

    for point in data:
        if not isinstance(point, dict):
            report["reason"] = "malformed_point"
            return False, report
        label = str(point.get("label", "")).strip()
        value = point.get("value")
        if not label or not _is_number(value):
            report["reason"] = "malformed_point"
            return False, report
        if (label, float(value)) not in allowed:
            report["reason"] = "value_not_in_source"
            return False, report

    return True, report
