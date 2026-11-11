"""Tests for the provider-observability shadow — JARVIS 2A.

The shadow's job is to be an honest, durable, PII-free record of how each
provider behaved. So the properties guarded here are: latency lands in the right
bucket, a label outside the fixed enums is dropped (never invented into a new
column), failure rate and the under-2s share are computed from the right
subsets, and nothing but enums, counts and buckets is ever stored.
"""

import pytest

try:
    import provider_shadow as ps
    from providers import ERROR_CODES
except ImportError:  # running from the repo root
    from src import provider_shadow as ps  # type: ignore
    from src.providers import ERROR_CODES  # type: ignore


# ── A: only enum labels + counts are stored ──────────────────────────────────
def test_a_row_holds_labels_counts_and_a_bucket_only():
    b = {}
    ps.merge_event(b, "backend", "groq", "ok", 350)
    row = ps.rows_for_upsert(b)[0]
    assert set(row) == {"day", "service", "provider", "outcome", "latency_bucket", "count"}
    assert row["service"] in ps.VALID_SERVICES
    assert row["provider"] in ps.VALID_PROVIDERS
    assert row["outcome"] in ps.VALID_OUTCOMES
    assert row["latency_bucket"] in ps.VALID_LATENCY_BUCKETS


@pytest.mark.parametrize("bad", ["kimi", "vertex", "", "GROQ", "DROP TABLE x"])
def test_an_unknown_provider_is_dropped(bad):
    b = {}
    assert ps.merge_event(b, "backend", bad, "ok", 100) is False
    assert b == {}


def test_local_is_a_valid_provider():
    # JARVIS 3 added the Local Ollama backstop; its calls must be recorded, not
    # dropped as unknown.
    b = {}
    assert ps.merge_event(b, "backend", "local", "ok", 100) is True
    assert sum(b.values()) == 1


def test_eva_local_is_a_valid_provider():
    # Phase 2 Step 12 records EVA Server Local calls through providers.record();
    # before Step 13 every one of those rows was dropped here as unknown, so the
    # live counters reset on restart and nothing was ever persisted.
    b = {}
    assert ps.merge_event(b, "backend", "eva_local", "ok", 100) is True
    assert ps.merge_event(b, "backend", "eva_local", "TIMEOUT", 6000) is True
    rows = {(r["provider"], r["outcome"], r["latency_bucket"]): r["count"]
            for r in ps.rows_for_upsert(b)}
    assert rows[("eva_local", "ok", "lt_500")] == 1
    assert rows[("eva_local", "TIMEOUT", "gte_5000")] == 1


def test_eva_local_appears_in_the_summary_alongside_cloud():
    b = {}
    ps.merge_event(b, "backend", "groq", "ok", 100)
    ps.merge_event(b, "backend", "eva_local", "ok", 100)
    ps.merge_event(b, "backend", "eva_local", "ERROR", 100)
    summary = ps.summarize(ps.rows_for_upsert(b))
    by_provider = summary["by_provider"]
    assert by_provider["eva_local"]["requests"] == 2
    assert by_provider["eva_local"]["failures"] == 1
    assert by_provider["eva_local"]["failure_rate"] == 0.5
    assert by_provider["groq"]["requests"] == 1        # cloud unaffected


def test_widening_the_enum_did_not_open_it():
    # The set widens on purpose only; a genuinely unknown id is still dropped.
    b = {}
    for unknown in ("eva-local", "evalocal", "EVA_LOCAL", "kimi"):
        assert ps.merge_event(b, "backend", unknown, "ok", 100) is False
    assert b == {}


@pytest.mark.parametrize("bad", ["maybe", "OK", "", "the user's prompt text"])
def test_an_unknown_outcome_is_dropped(bad):
    b = {}
    assert ps.merge_event(b, "backend", "groq", bad, 100) is False
    assert b == {}


@pytest.mark.parametrize("bad", ["frontend", "vercel", ""])
def test_an_unknown_service_is_dropped(bad):
    b = {}
    assert ps.merge_event(b, bad, "groq", "ok", 100) is False
    assert b == {}


def test_the_outcome_enum_tracks_providers_error_codes():
    """VALID_OUTCOMES must stay 'ok' plus exactly the provider error enum; if it
    drifts, real error labels get silently dropped from the shadow."""
    assert ps.VALID_OUTCOMES == frozenset({"ok"}) | frozenset(ERROR_CODES)


# ── B: latency bucketing — the boundaries are the contract ───────────────────
@pytest.mark.parametrize("ms,bucket", [
    (0, "lt_500"), (499, "lt_500"),
    (500, "lt_1000"), (999, "lt_1000"),
    (1000, "lt_2000"), (1999, "lt_2000"),
    (2000, "lt_5000"), (4999, "lt_5000"),
    (5000, "gte_5000"), (99999, "gte_5000"),
])
def test_latency_lands_in_the_right_bucket(ms, bucket):
    assert ps.latency_bucket(ms) == bucket


@pytest.mark.parametrize("bad", [None, "n/a", object()])
def test_unmeasured_latency_is_unknown(bad):
    assert ps.latency_bucket(bad) == "unknown"


# ── C: counting ──────────────────────────────────────────────────────────────
def test_calls_accumulate_per_cell():
    b = {}
    ps.merge_event(b, "backend", "groq", "ok", 100)
    ps.merge_event(b, "backend", "groq", "ok", 120)          # same cell (lt_500)
    ps.merge_event(b, "backend", "groq", "ok", 1500)         # different bucket
    rows = {(r["provider"], r["outcome"], r["latency_bucket"]): r["count"]
            for r in ps.rows_for_upsert(b)}
    assert rows[("groq", "ok", "lt_500")] == 2
    assert rows[("groq", "ok", "lt_2000")] == 1


# ── D: the per-provider health picture ───────────────────────────────────────
def _rows(*specs):
    """specs: (service, provider, outcome, bucket, count)."""
    return [{"day": "d", "service": s, "provider": p, "outcome": o,
             "latency_bucket": b, "count": c} for s, p, o, b, c in specs]


def test_failure_rate_is_failures_over_requests():
    rows = _rows(
        ("backend", "groq", "ok", "lt_500", 80),
        ("backend", "groq", "RATE_LIMITED", "lt_500", 20),
    )
    g = ps.summarize(rows)["by_provider"]["groq"]
    assert g["requests"] == 100 and g["failures"] == 20 and g["ok"] == 80
    assert g["failure_rate"] == pytest.approx(0.20)


def test_under_2s_share_counts_only_the_fast_buckets_over_known():
    rows = _rows(
        ("backend", "groq", "ok", "lt_500", 30),
        ("backend", "groq", "ok", "lt_2000", 30),   # still under 2s
        ("backend", "groq", "ok", "lt_5000", 40),   # not under 2s
        ("backend", "groq", "ok", "unknown", 99),   # excluded from the denominator
    )
    g = ps.summarize(rows)["by_provider"]["groq"]
    assert g["under_2s_share"] == pytest.approx(60 / 100)   # 60 fast / 100 known


def test_by_outcome_shows_which_failure_dominates():
    rows = _rows(
        ("backend", "gemini", "RATE_LIMITED", "lt_1000", 15),
        ("backend", "gemini", "TIMEOUT", "gte_5000", 5),
        ("backend", "gemini", "ok", "lt_1000", 80),
    )
    out = ps.summarize(rows)["by_outcome"]
    assert out["RATE_LIMITED"] == 15 and out["TIMEOUT"] == 5 and out["ok"] == 80


def test_by_service_separates_the_two_emitters():
    rows = _rows(
        ("backend", "groq", "ok", "lt_500", 3),
        ("ml", "gemini", "ok", "lt_1000", 7),
    )
    assert ps.summarize(rows)["by_service"] == {"backend": 3, "ml": 7}


def test_healthiest_is_the_lowest_failure_rate():
    rows = _rows(
        ("backend", "groq", "ok", "lt_500", 90),
        ("backend", "groq", "ERROR", "lt_500", 10),      # 10% fail
        ("ml", "gemini", "ok", "lt_500", 99),
        ("ml", "gemini", "ERROR", "lt_500", 1),          # 1% fail -> healthiest
    )
    assert ps.summarize(rows)["healthiest_provider"] == "gemini"


def test_days_observed_counts_distinct_days():
    rows = [
        {"day": "2026-08-12", "service": "backend", "provider": "groq", "outcome": "ok", "latency_bucket": "lt_500", "count": 1},
        {"day": "2026-08-13", "service": "backend", "provider": "groq", "outcome": "ok", "latency_bucket": "lt_500", "count": 1},
    ]
    assert ps.summarize(rows)["days_observed"] == 2


# ── E: robustness of the reader ──────────────────────────────────────────────
def test_summarize_ignores_rows_outside_the_enums():
    rows = _rows(
        ("backend", "groq", "ok", "lt_500", 10),
        ("backend", "made_up", "ok", "lt_500", 999),
        ("backend", "groq", "bogus_outcome", "lt_500", 999),
        ("backend", "groq", "ok", "bogus_bucket", 999),
    )
    assert ps.summarize(rows)["calls"] == 10


def test_summarize_ignores_a_non_numeric_count():
    rows = _rows(
        ("backend", "groq", "ok", "lt_500", "lots"),
        ("backend", "groq", "ok", "lt_500", 5),
    )
    assert ps.summarize(rows)["calls"] == 5


@pytest.mark.parametrize("junk", [None, [], [{}], [{"provider": "groq"}]])
def test_summarize_survives_junk(junk):
    assert isinstance(ps.summarize(junk)["calls"], int)


def test_no_data_gives_null_rates_not_zero():
    out = ps.summarize([])
    assert out["calls"] == 0
    assert out["by_provider"] == {}
    assert out["healthiest_provider"] is None


def test_a_provider_with_only_unknown_latency_has_null_share():
    rows = _rows(("backend", "groq", "ok", "unknown", 5))
    assert ps.summarize(rows)["by_provider"]["groq"]["under_2s_share"] is None
