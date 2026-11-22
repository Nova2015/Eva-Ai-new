"""Tests for the /chat table-to-chart path.

Additive by design: the inline "A=40, B=30" path is live and tested, so this
runs only when that one finds nothing. The tests therefore care as much about
what still works as about what is new.
"""

import json
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


TABLE_REQUEST = "make a chart from this data\nregion, sales\nNorth, 40\nSouth, 30"


def _spec(block):
    assert block and block.startswith("```chart")
    return json.loads(block.split("\n", 1)[1].rsplit("```", 1)[0])


# ── A: the new path ──────────────────────────────────────────────────────────
def test_a_pasted_table_becomes_a_chart(app_module):
    spec = _spec(app_module._chart_from_table(TABLE_REQUEST))
    assert spec["data"] == [{"label": "North", "value": 40},
                            {"label": "South", "value": 30}]


def test_an_explicit_type_is_honoured(app_module):
    block = app_module._chart_from_table(
        "make a pie chart from this\nregion, sales\nNorth, 40\nSouth, 30")
    assert _spec(block)["type"] == "pie"


def test_a_time_column_becomes_a_line(app_module):
    block = app_module._chart_from_table(
        "chart of revenue by year\nyear, revenue\n2021, 10\n2022, 14")
    assert _spec(block)["type"] == "line"


# ── B: it must refuse rather than guess ──────────────────────────────────────
@pytest.mark.parametrize("text", [
    "what is a bar chart",                 # a question about charts
    "make a chart of everything",          # asked, but sent no data
    "hello",
    "region, sales\nNorth, 40",            # data, but no chart was requested
])
def test_it_falls_through_when_it_should(app_module, text):
    assert app_module._chart_from_table(text) is None


def test_a_table_with_no_numbers_falls_through(app_module):
    assert app_module._chart_from_table(
        "chart this\nname, city\nAnil, Pune\nBela, Delhi") is None


def test_a_chart_failing_verification_is_never_emitted(app_module, monkeypatch):
    """Verification is the guard against restating the user's numbers back to
    them incorrectly. If it fails, nothing may be returned."""
    monkeypatch.setattr(app_module, "_verify_chart",
                        lambda spec, rows: (False, {"reason": "value_not_in_source"}))
    assert app_module._chart_from_table(TABLE_REQUEST) is None


def test_a_build_error_falls_through(app_module, monkeypatch):
    def boom(rows, requested_type=None, title=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(app_module, "_chart_spec_from_table", boom)
    assert app_module._chart_from_table(TABLE_REQUEST) is None


# ── C: the existing inline path is untouched ─────────────────────────────────
def test_inline_pairs_still_work(app_module):
    """This path is live and was verified on production. The new one runs only
    when it finds nothing, so it must not shadow it."""
    block = app_module.deterministic_chart_response(
        "make a pie chart of sales: A=40, B=30, C=30")
    spec = _spec(block)
    assert spec["type"] == "pie"
    assert {"label": "A", "value": 40} in spec["data"]


def test_the_inline_path_wins_when_both_could_match(app_module):
    """Asserted against chat()'s own source, not by re-running the precedence
    here. An earlier version of this test wrote `A or B` itself, so it proved
    that `or` works — swapping the real order in app.py left it passing."""
    import inspect
    src = inspect.getsource(app_module.chat)
    # A window rather than a regex: the expression spans two lines and any
    # pattern that tries to match balanced parentheses stops at the first ")",
    # which is inside the first call.
    start = src.index("chart_response = (")
    window = src[start:start + 400]
    first = window.index("deterministic_chart_response")
    second = window.index("_chart_from_table")
    assert first < second, (
        "the table path must run only when the inline path finds nothing; "
        f"got: {' '.join(window[:160].split())}")


def test_both_chart_paths_are_reachable_from_chat(app_module):
    import inspect
    src = inspect.getsource(app_module.chat)
    assert "deterministic_chart_response(" in src
    assert "_chart_from_table(" in src
