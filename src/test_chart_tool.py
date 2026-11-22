"""Tests for building a chart from a pasted table.

A chart is read as fact and forwarded. One wrong bar is a wrong claim, and
harder to notice than a wrong cell in a spreadsheet — so the load-bearing tests
here are the ones that try to get an invented value into a chart.
"""

import pytest

try:
    from chart_tool import (
        ALLOWED_TYPES, MAX_POINTS, infer_chart_type, spec_from_table, verify_chart)
    from spreadsheet import parse_table
except ImportError:  # running from the repo root
    from src.chart_tool import (  # type: ignore
        ALLOWED_TYPES, MAX_POINTS, infer_chart_type, spec_from_table, verify_chart)
    from src.spreadsheet import parse_table  # type: ignore


SALES = parse_table("region, sales\nNorth, 40\nSouth, 30\nEast, 30")
YEARS = parse_table("year, revenue\n2021, 10\n2022, 14\n2023, 19")
SHARE = parse_table("segment, share\nA, 55\nB, 45")
POINTS = parse_table("height, weight\n1.6, 55\n1.8, 78")


# ── A: values come from the table, never from anywhere else ──────────────────
def test_every_point_is_a_row_of_the_source():
    spec = spec_from_table(SALES)
    assert spec["data"] == [{"label": "North", "value": 40},
                            {"label": "South", "value": 30},
                            {"label": "East", "value": 30}]


def test_a_spec_built_from_the_table_verifies():
    spec = spec_from_table(SALES)
    ok, report = verify_chart(spec, SALES)
    assert ok is True and report["points"] == 3


def test_an_invented_value_is_caught():
    """The failure this exists for: a plausible number that is not in the data."""
    spec = spec_from_table(SALES)
    spec["data"][0]["value"] = 41
    ok, report = verify_chart(spec, SALES)
    assert ok is False and report["reason"] == "value_not_in_source"


def test_an_invented_label_is_caught():
    spec = spec_from_table(SALES)
    spec["data"].append({"label": "West", "value": 40})
    ok, report = verify_chart(spec, SALES)
    assert ok is False and report["reason"] == "value_not_in_source"


def test_a_value_swapped_between_labels_is_caught():
    """North=30 exists in the table, but not for North. A pairing check that
    only looked for "is this number present" would pass this."""
    spec = spec_from_table(SALES)
    spec["data"] = [{"label": "North", "value": 30},
                    {"label": "South", "value": 40}]
    ok, report = verify_chart(spec, SALES)
    assert ok is False


def test_a_type_the_renderer_cannot_draw_is_rejected():
    spec = spec_from_table(SALES)
    spec["type"] = "donut3d"
    ok, report = verify_chart(spec, SALES)
    assert ok is False and report["reason"] == "unrenderable_type"


@pytest.mark.parametrize("spec", [None, {}, {"type": "bar"},
                                  {"type": "bar", "data": []},
                                  {"type": "bar", "data": [{"label": "x"}]},
                                  {"type": "bar", "data": ["nope"]}])
def test_a_malformed_spec_never_verifies(spec):
    ok, _ = verify_chart(spec, SALES)
    assert ok is False


# ── B: type inference, and never over a stated preference ────────────────────
def test_an_explicit_type_always_wins():
    """Guessing over a stated preference is a worse failure than guessing over
    silence: the user said what they wanted."""
    assert spec_from_table(YEARS, requested_type="pie")["type"] == "pie"
    assert spec_from_table(SALES, requested_type="line")["type"] == "line"


def test_a_time_axis_becomes_a_line():
    assert infer_chart_type(YEARS) == "line"


def test_categories_become_bars():
    assert infer_chart_type(SALES) == "bar"


def test_a_share_column_becomes_a_pie():
    assert infer_chart_type(SHARE) == "pie"


def test_two_numeric_columns_become_a_scatter():
    assert infer_chart_type(POINTS) == "scatter"


def test_an_unknown_requested_type_falls_back_to_inference():
    assert infer_chart_type(SALES, requested="donut") == "bar"


def test_every_inferred_type_is_renderable():
    for rows in (SALES, YEARS, SHARE, POINTS):
        assert infer_chart_type(rows) in ALLOWED_TYPES


# ── C: refusing rather than guessing ─────────────────────────────────────────
def test_a_table_with_no_numbers_produces_nothing():
    rows = parse_table("name, city\nAnil, Pune\nBela, Delhi")
    assert spec_from_table(rows) is None


def test_a_header_only_table_produces_nothing():
    assert spec_from_table([["a", "b"]]) is None
    assert spec_from_table([]) is None
    assert spec_from_table(None) is None


def test_too_many_points_is_refused_not_truncated():
    """Silently dropping rows would misrepresent the data — the chart would
    look complete and be wrong."""
    rows = [["label", "value"]] + [[f"r{i}", i] for i in range(MAX_POINTS + 5)]
    assert spec_from_table(rows) is None


def test_the_header_is_never_read_as_a_data_point():
    """A header is text by definition; reading it as a value is how a chart
    gains a bar labelled "sales"."""
    spec = spec_from_table(SALES)
    assert all(p["label"] != "region" for p in spec["data"])
    assert all(p["value"] != "sales" for p in spec["data"])


def test_a_numeric_header_is_still_not_a_data_point():
    """Year headers are ordinary. "2020, 2021" parses as numbers, so the
    numeric filter that normally rejects a header row does not fire — only the
    row slice keeps it out. Without a case like this, the slice could be
    removed and every test still passed."""
    rows = parse_table("2020, 2021\nNorth, 40\nSouth, 30")
    spec = spec_from_table(rows)
    assert [p["label"] for p in spec["data"]] == ["North", "South"]
    assert all(str(p["label"]) not in ("2020", "2021") for p in spec["data"])


def test_the_title_defaults_to_the_measured_column():
    assert spec_from_table(SALES)["title"] == "sales"
    assert spec_from_table(SALES, title="Q1 results")["title"] == "Q1 results"


def test_rows_shorter_than_the_columns_are_skipped_not_guessed():
    rows = [["region", "sales"], ["North", 40], ["South"]]
    spec = spec_from_table(rows)
    assert [p["label"] for p in spec["data"]] == ["North"]
