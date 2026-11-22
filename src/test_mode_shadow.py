"""Tests for the mode-shadow aggregation — Update 37.

The shadow's only job is to be honest about what the classifier would choose,
durably and without ever storing text. So the properties guarded here are:

  1. Only enum labels and counts are ever stored — never a message or answer.
  2. A label outside the classifier's enums is dropped, not invented into a new
     column, so the matrix cannot drift as the classifier changes shape.
  3. strong_non_general — the number Update 37 would actually route on — is
     computed from STRONG, non-general rows only, and is a null share (not zero)
     when nothing has been observed.
"""

from datetime import datetime, timedelta, timezone

import pytest

try:
    from mode_shadow import (
        TABLE, VALID_MODES, VALID_SIGNALS,
        merge_event, rows_for_upsert, summarize, today_key,
    )
except ImportError:  # running from the repo root
    from src.mode_shadow import (  # type: ignore
        TABLE, VALID_MODES, VALID_SIGNALS,
        merge_event, rows_for_upsert, summarize, today_key,
    )


# ── A: only enum labels and counts are ever stored ───────────────────────────
def test_a_row_holds_labels_and_counts_only():
    b = {}
    merge_event(b, "coding", "strong")
    row = rows_for_upsert(b)[0]
    assert set(row) == {"day", "mode", "signal", "count"}
    assert row["mode"] in VALID_MODES
    assert row["signal"] in VALID_SIGNALS


@pytest.mark.parametrize("bad_mode", [
    "legal", "the user asked about their divorce", "", "GENERAL",
    "DROP TABLE mode_shadow_daily",
])
def test_an_unknown_mode_is_dropped(bad_mode):
    b = {}
    assert merge_event(b, bad_mode, "strong") is False
    assert b == {}


@pytest.mark.parametrize("bad_signal", ["maybe", "STRONG", "", "high"])
def test_an_unknown_signal_is_dropped(bad_signal):
    b = {}
    assert merge_event(b, "coding", bad_signal) is False
    assert b == {}


def test_the_enums_match_the_classifier():
    """If the shadow's copy of the valid labels drifts from the classifier's,
    real classifications start being silently dropped. They are imported from
    the classifier for exactly this reason — this pins that they still are."""
    try:
        from mode_classifier import VALID_MODES as CM, VALID_SIGNALS as CS
    except ImportError:  # pragma: no cover
        from src.mode_classifier import VALID_MODES as CM, VALID_SIGNALS as CS  # type: ignore
    assert VALID_MODES == CM
    assert VALID_SIGNALS == CS


# ── B: counting ──────────────────────────────────────────────────────────────
def test_a_true_return_means_it_was_recorded():
    b = {}
    assert merge_event(b, "medical", "weak") is True
    assert sum(b.values()) == 1


def test_pairs_accumulate_separately():
    b = {}
    merge_event(b, "coding", "strong")
    merge_event(b, "coding", "strong")
    merge_event(b, "coding", "weak")
    merge_event(b, "medical", "strong")
    rows = {(r["mode"], r["signal"]): r["count"] for r in rows_for_upsert(b)}
    assert rows[("coding", "strong")] == 2
    assert rows[("coding", "weak")] == 1
    assert rows[("medical", "strong")] == 1


def test_days_are_separate_and_utc():
    b = {}
    ist = timezone(timedelta(hours=5, minutes=30))
    # 04:00 on the 8th in Kolkata is still the 7th in UTC.
    merge_event(b, "coding", "strong",
                now=datetime(2026, 8, 8, 4, 0, tzinfo=ist))
    assert rows_for_upsert(b)[0]["day"] == "2026-08-07"
    assert today_key(datetime(2026, 8, 7, 23, 30, tzinfo=timezone.utc)) == "2026-08-07"


# ── C: the distribution ──────────────────────────────────────────────────────
def test_by_mode_and_by_signal_sum_the_rows():
    rows = [
        {"day": "d", "mode": "coding", "signal": "strong", "count": 40},
        {"day": "d", "mode": "coding", "signal": "weak", "count": 10},
        {"day": "d", "mode": "general", "signal": "default", "count": 50},
    ]
    out = summarize(rows)
    assert out["classified"] == 100
    assert out["by_mode"]["coding"] == 50
    assert out["by_mode"]["general"] == 50
    assert out["by_signal"]["strong"] == 40
    assert out["by_signal"]["default"] == 50


def test_the_matrix_keeps_every_pair():
    rows = [
        {"day": "d", "mode": "mechanical", "signal": "strong", "count": 7},
        {"day": "d", "mode": "design", "signal": "weak", "count": 3},
    ]
    m = summarize(rows)["matrix"]
    assert m["mechanical"]["strong"] == 7
    assert m["design"]["weak"] == 3


def test_days_observed_counts_distinct_days():
    rows = [
        {"day": "2026-08-12", "mode": "coding", "signal": "strong", "count": 1},
        {"day": "2026-08-13", "mode": "coding", "signal": "strong", "count": 1},
        {"day": "2026-08-13", "mode": "medical", "signal": "weak", "count": 1},
    ]
    assert summarize(rows)["days_observed"] == 2


# ── D: the number Update 37 would route on ───────────────────────────────────
def test_strong_non_general_counts_only_strong_non_general():
    rows = [
        {"day": "d", "mode": "coding", "signal": "strong", "count": 20},
        {"day": "d", "mode": "medical", "signal": "strong", "count": 10},
        {"day": "d", "mode": "coding", "signal": "weak", "count": 15},   # weak → out
        {"day": "d", "mode": "general", "signal": "default", "count": 55},
    ]
    out = summarize(rows)
    assert out["classified"] == 100
    assert out["strong_non_general"] == 30            # 20 + 10, not the weak 15
    assert out["strong_non_general_share"] == pytest.approx(0.30)


def test_a_strong_general_would_never_count_even_if_it_appeared():
    # general only ever pairs with default (the classifier guarantees it), but
    # the aggregation must not depend on that: a hypothetical strong-general row
    # is still excluded because it is general.
    rows = [
        {"day": "d", "mode": "general", "signal": "strong", "count": 99},
        {"day": "d", "mode": "coding", "signal": "strong", "count": 1},
    ]
    assert summarize(rows)["strong_non_general"] == 1


def test_no_data_gives_a_null_share_not_zero():
    """"Nothing observed" and "nothing ever fired a strong mode" are opposite
    findings and must not look identical."""
    out = summarize([])
    assert out["classified"] == 0
    assert out["strong_non_general_share"] is None


# ── E: robustness of the reader ──────────────────────────────────────────────
def test_summarize_ignores_rows_outside_the_enums():
    rows = [
        {"day": "d", "mode": "coding", "signal": "strong", "count": 10},
        {"day": "d", "mode": "made_up", "signal": "strong", "count": 999},
        {"day": "d", "mode": "coding", "signal": "loud", "count": 999},
    ]
    assert summarize(rows)["classified"] == 10


def test_summarize_ignores_a_non_numeric_count():
    rows = [
        {"day": "d", "mode": "coding", "signal": "strong", "count": "lots"},
        {"day": "d", "mode": "coding", "signal": "strong", "count": 5},
    ]
    assert summarize(rows)["classified"] == 5


@pytest.mark.parametrize("junk", [None, [], [{}], [{"mode": "coding"}]])
def test_summarize_survives_junk(junk):
    assert isinstance(summarize(junk)["classified"], int)


# ── F: no verdict is baked into the collector ────────────────────────────────
def test_no_verdict_about_the_right_mode_is_encoded():
    """Stage 1 collects evidence; whether a persona fires too often is what the
    evidence decides. A key like "correct" or "should_route" would bake in the
    conclusion the shadow exists to establish."""
    out = summarize([{"day": "d", "mode": "mechanical", "signal": "strong",
                      "count": 5}])
    flat = repr(out).lower()
    for verdict_word in ("correct", "wrong", "agree", "mismatch", "should"):
        assert verdict_word not in flat


def test_the_table_name_is_the_append_delta_table():
    # Not a unique-constrained upsert table: summed on read, like routing.
    assert TABLE == "mode_shadow_daily"
