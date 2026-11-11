"""Tests for durable outbound-firewall shadow statistics.

The load-bearing properties are about what must NEVER be stored. This data
exists to justify arming a security filter, and it is written to a hosted
database — a counter that quietly grows a prompt column would be a worse
outcome than never having built it.

  1. Only a fixed enum of reason codes reaches storage.
  2. Rows carry counts and a day. Nothing else, ever.
  3. "No data" and "nothing would be blocked" never look the same.
"""

from datetime import datetime, timedelta, timezone

import pytest

try:
    from outbound_shadow import (
        VALID_REASON_CODES, today_key, merge_event, rows_for_upsert, summarize,
    )
except ImportError:  # running from the repo root
    from src.outbound_shadow import (  # type: ignore
        VALID_REASON_CODES, today_key, merge_event, rows_for_upsert, summarize,
    )


# ── A: nothing but counts and a day is ever stored ───────────────────────────
def test_a_row_has_exactly_four_fields():
    buckets = {}
    merge_event(buckets, "APPROVED", False)
    row = rows_for_upsert(buckets)[0]
    assert set(row) == {"day", "reason_code", "inspected", "would_block"}


def test_no_row_field_can_hold_free_text_from_a_verdict():
    """Only reason_code is a string, and it is enum-checked before it lands."""
    buckets = {}
    merge_event(buckets, "HALLUCINATION", True)
    row = rows_for_upsert(buckets)[0]
    assert row["reason_code"] in VALID_REASON_CODES
    assert isinstance(row["inspected"], int)
    assert isinstance(row["would_block"], int)


@pytest.mark.parametrize("bad", [
    "the answer mentioned a patient name",
    "user@example.com",
    "BLOCKED: 192.168.1.1",
    "approved",          # case matters; the enum is upper
    "",
    "DROP TABLE outbound_shadow_daily",
])
def test_an_unknown_reason_code_is_dropped_not_stored(bad):
    buckets = {}
    assert merge_event(buckets, bad, True) is False
    assert buckets == {}
    assert rows_for_upsert(buckets) == []


def test_the_enum_matches_the_one_the_gate_actually_uses(app_reason_codes):
    """The copy in outbound_shadow.py must not drift from app.py. If it does,
    real reason codes start being silently dropped."""
    assert VALID_REASON_CODES == app_reason_codes


@pytest.fixture(scope="module")
def app_reason_codes():
    import os
    import sys
    for rel in ("", "runtime_engine", "review_engine"):
        p = os.path.abspath(os.path.join(os.path.dirname(__file__), rel))
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
    try:
        import app
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"app.py not importable here: {type(exc).__name__}: {exc}")
    return frozenset({
        v for k, v in vars(app).items()
        if k.startswith("OUTBOUND_REASON_") and isinstance(v, str)
    })


# ── B: counting ──────────────────────────────────────────────────────────────
def test_counts_accumulate_per_reason():
    b = {}
    for _ in range(3):
        merge_event(b, "APPROVED", False)
    merge_event(b, "HALLUCINATION", True)
    rows = {r["reason_code"]: r for r in rows_for_upsert(b)}
    assert rows["APPROVED"]["inspected"] == 3
    assert rows["APPROVED"]["would_block"] == 0
    assert rows["HALLUCINATION"]["would_block"] == 1


def test_would_block_only_counts_when_it_would_block():
    b = {}
    merge_event(b, "BLOCKED_OTHER", False)
    row = rows_for_upsert(b)[0]
    assert row["inspected"] == 1 and row["would_block"] == 0


def test_days_are_separate_buckets():
    b = {}
    merge_event(b, "APPROVED", False, now=datetime(2026, 8, 7, tzinfo=timezone.utc))
    merge_event(b, "APPROVED", False, now=datetime(2026, 8, 8, tzinfo=timezone.utc))
    assert len(rows_for_upsert(b)) == 2


def test_the_bucket_is_utc_not_local():
    """Two hosts in different timezones must agree which day a count belongs
    to, or the same day appears twice and rates are computed on half the data.

    The offset case is the one that matters, and an earlier version of this
    test did not have it: both inputs were already UTC, so deleting the
    conversion changed nothing and the test passed over the bug it named.
    """
    late = datetime(2026, 8, 7, 23, 30, tzinfo=timezone.utc)
    assert today_key(late) == "2026-08-07"

    naive = datetime(2026, 8, 7, 23, 30)
    assert today_key(naive) == "2026-08-07"

    # 04:00 on the 8th in Kolkata is 22:30 on the 7th in UTC. Reading the local
    # date here would file the count under the wrong day — and this is the
    # timezone the project is actually developed in.
    ist = timezone(timedelta(hours=5, minutes=30))
    assert today_key(datetime(2026, 8, 8, 4, 0, tzinfo=ist)) == "2026-08-07"

    # And the mirror case the other way.
    utc_minus_8 = timezone(timedelta(hours=-8))
    assert today_key(datetime(2026, 8, 7, 20, 0, tzinfo=utc_minus_8)) == "2026-08-08"


def test_nothing_pending_produces_no_rows():
    # A flush with an empty buffer must send no request at all.
    assert rows_for_upsert({}) == []


# ── C: the number the decision rests on ──────────────────────────────────────
def test_block_rate_is_the_share_that_would_have_been_refused():
    rows = [
        {"day": "2026-08-07", "reason_code": "APPROVED", "inspected": 90, "would_block": 0},
        {"day": "2026-08-07", "reason_code": "HALLUCINATION", "inspected": 10, "would_block": 10},
    ]
    out = summarize(rows)
    assert out["inspected"] == 100
    assert out["would_block"] == 10
    assert out["block_rate"] == pytest.approx(0.10)


def test_no_data_is_not_reported_as_a_zero_block_rate():
    """"Nothing inspected" and "nothing would be blocked" are opposite
    conclusions. Reporting both as 0.0 would invite arming the firewall on the
    strength of no evidence at all."""
    assert summarize([])["block_rate"] is None
    assert summarize([])["inspected"] == 0


def test_a_genuine_zero_block_rate_is_reported_as_zero():
    rows = [{"day": "d", "reason_code": "APPROVED", "inspected": 50, "would_block": 0}]
    assert summarize(rows)["block_rate"] == 0.0


def test_summarize_counts_distinct_days():
    rows = [
        {"day": "2026-08-06", "reason_code": "APPROVED", "inspected": 1, "would_block": 0},
        {"day": "2026-08-07", "reason_code": "APPROVED", "inspected": 1, "would_block": 0},
        {"day": "2026-08-07", "reason_code": "GATE_ERROR", "inspected": 1, "would_block": 0},
    ]
    assert summarize(rows)["days_observed"] == 2


def test_summarize_ignores_rows_with_an_unknown_code():
    rows = [
        {"day": "d", "reason_code": "APPROVED", "inspected": 10, "would_block": 0},
        {"day": "d", "reason_code": "SOMETHING_ELSE", "inspected": 999, "would_block": 999},
    ]
    out = summarize(rows)
    assert out["inspected"] == 10
    assert "SOMETHING_ELSE" not in out["by_reason_code"]


@pytest.mark.parametrize("junk", [None, [], [{}], [{"inspected": "x"}],
                                  [{"reason_code": "APPROVED", "inspected": None}]])
def test_summarize_survives_junk(junk):
    out = summarize(junk)
    assert isinstance(out["inspected"], int)
