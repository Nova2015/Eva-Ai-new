"""Tests for the routing shadow comparison.

Stage 1 changes no behaviour, so the properties worth guarding are about
honesty of the evidence rather than correctness of a decision:

  1. Only enum labels are stored — never a question, an answer or a provider
     message.
  2. route_of reads what actually answered, including the cases that hide
     behind each other (a fallback still carries the failed retrieval's
     metadata).
  3. No judgement about which routing is "right" is baked in. That is what the
     data is for.
"""

from datetime import datetime, timedelta, timezone

import pytest

try:
    from routing_shadow import (
        VALID_STRATEGIES, VALID_ROUTES, route_of, grounded_of, merge_event,
        rows_for_upsert, summarize, today_key,
        ROUTE_CHART, ROUTE_SPREADSHEET, ROUTE_VISION, ROUTE_RAG_SERVICE,
        ROUTE_FALLBACK, ROUTE_GENERAL_LLM, ROUTE_UNKNOWN,
    )
except ImportError:  # running from the repo root
    from src.routing_shadow import (  # type: ignore
        VALID_STRATEGIES, VALID_ROUTES, route_of, grounded_of, merge_event,
        rows_for_upsert, summarize, today_key,
        ROUTE_CHART, ROUTE_SPREADSHEET, ROUTE_VISION, ROUTE_RAG_SERVICE,
        ROUTE_FALLBACK, ROUTE_GENERAL_LLM, ROUTE_UNKNOWN,
    )


# ── A: reading which route answered ──────────────────────────────────────────
def test_the_chart_shortcut_is_recognised():
    assert route_of({"provider": "chart", "model": "deterministic-chart"}) == ROUTE_CHART


def test_a_generated_spreadsheet_is_its_own_route():
    """Before this existed, an .xlsx answer fell through to GENERAL_LLM and
    every artifact quietly polluted the text bucket — visible in the first
    real reading of the matrix, where a spreadsheet reply was counted as a
    plain model answer."""
    assert route_of({"provider": "spreadsheet",
                     "model": "deterministic-spreadsheet"}) == ROUTE_SPREADSHEET


def test_an_artifact_route_is_not_counted_as_a_text_answer():
    for provider in ("chart", "spreadsheet"):
        assert route_of({"provider": provider}) not in (
            ROUTE_GENERAL_LLM, ROUTE_RAG_SERVICE, ROUTE_FALLBACK)


@pytest.mark.parametrize("provider", ["vision-gemini", "vision-openai",
                                      "vision-unavailable"])
def test_every_vision_outcome_is_one_route(provider):
    assert route_of({"provider": provider}) == ROUTE_VISION


def test_the_rag_service_is_recognised_by_its_retrieval_metadata():
    # Observed live: a general-knowledge question came back with these fields,
    # because the RAG call is unconditional.
    assert route_of({"provider": "groq", "mode_used": "hybrid",
                     "retrievers_used": ["bm25", "vector"]}) == ROUTE_RAG_SERVICE


def test_the_backend_fallback_has_no_retrieval_metadata():
    """The backend's low-confidence _llm_fallback answers from the general
    model without retrieving, so its payload carries fallback_mode and NO
    mode_used/retrievers_used. That is the only thing FALLBACK means."""
    payload = {"provider": "groq", "sources": [], "fallback_mode": True}
    assert route_of(payload) == ROUTE_FALLBACK


def test_a_provider_fallback_on_a_retrieval_query_stays_rag_service():
    """Update 37A. The primary /rag/chat path always retrieves, then may fall
    back to a backup LLM provider mid-generation — carrying mode_used /
    retrievers_used AND fallback_used. Retrieval still ran, so the route is
    RAG_SERVICE. Counting it as FALLBACK (the old behaviour) moved
    retrieved_without_need with provider quotas, not with routing."""
    payload = {"provider": "gemini", "mode_used": "hybrid",
               "retrievers_used": ["bm25", "vector"], "fallback_used": True}
    assert route_of(payload) == ROUTE_RAG_SERVICE


def test_provider_fallback_is_not_a_route_on_its_own():
    """fallback_used with no retrieval metadata and no backend fallback_mode is
    a plain provider fallback on a direct call — still a general-model answer,
    not a route of its own."""
    assert route_of({"provider": "groq", "fallback_used": True}) == ROUTE_GENERAL_LLM


def test_a_direct_provider_call_is_the_general_route():
    assert route_of({"provider": "groq"}) == ROUTE_GENERAL_LLM


@pytest.mark.parametrize("payload", [None, {}, [], "groq", {"provider": ""}])
def test_an_unreadable_payload_is_unknown_not_a_guess(payload):
    assert route_of(payload) == ROUTE_UNKNOWN


def test_chart_and_vision_win_over_retrieval_metadata():
    # Both return before retrieval can run; if a payload somehow carries both,
    # the earlier branch is the truthful answer.
    assert route_of({"provider": "chart", "mode_used": "hybrid"}) == ROUTE_CHART
    assert route_of({"provider": "vision-gemini",
                     "retrievers_used": ["bm25"]}) == ROUTE_VISION


# ── B: grounding ─────────────────────────────────────────────────────────────
def test_grounded_means_the_answer_cited_something():
    assert grounded_of({"sources": ["a.pdf"]}) is True
    assert grounded_of({"sources": []}) is False
    assert grounded_of({}) is False
    assert grounded_of(None) is False


# ── C: only enum labels are ever stored ──────────────────────────────────────
def test_a_row_holds_labels_and_counts_only():
    b = {}
    merge_event(b, "DIRECT", ROUTE_RAG_SERVICE, False)
    row = rows_for_upsert(b)[0]
    assert set(row) == {"day", "strategy", "route", "answered", "grounded"}
    assert row["strategy"] in VALID_STRATEGIES
    assert row["route"] in VALID_ROUTES


@pytest.mark.parametrize("bad_strategy", [
    "what the user asked about their divorce", "direct", "", "SELECT * FROM x",
])
def test_an_unknown_strategy_is_dropped(bad_strategy):
    b = {}
    assert merge_event(b, bad_strategy, ROUTE_RAG_SERVICE, False) is False
    assert b == {}


@pytest.mark.parametrize("bad_route", ["the pdf about salaries", "rag", ""])
def test_an_unknown_route_is_dropped(bad_route):
    b = {}
    assert merge_event(b, "DIRECT", bad_route, False) is False
    assert b == {}


def test_the_strategy_enum_matches_the_cognitive_engine(engine_strategies):
    """If this copy drifts, real strategies start being silently dropped and
    the matrix quietly loses a column."""
    assert VALID_STRATEGIES == engine_strategies


@pytest.fixture(scope="module")
def engine_strategies():
    import os
    import sys
    p = os.path.abspath(os.path.dirname(__file__))
    if p not in sys.path:
        sys.path.insert(0, p)
    try:
        from cognitive.state import ReasoningStrategy
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"cognitive package not importable: {exc}")
    return frozenset(s.value for s in ReasoningStrategy)


# ── D: counting ──────────────────────────────────────────────────────────────
def test_pairs_accumulate_separately():
    b = {}
    merge_event(b, "DIRECT", ROUTE_RAG_SERVICE, False)
    merge_event(b, "DIRECT", ROUTE_RAG_SERVICE, True)
    merge_event(b, "RETRIEVAL", ROUTE_RAG_SERVICE, True)
    rows = {(r["strategy"], r["route"]): r for r in rows_for_upsert(b)}
    assert rows[("DIRECT", ROUTE_RAG_SERVICE)]["answered"] == 2
    assert rows[("DIRECT", ROUTE_RAG_SERVICE)]["grounded"] == 1
    assert rows[("RETRIEVAL", ROUTE_RAG_SERVICE)]["answered"] == 1


def test_days_are_separate_and_utc():
    b = {}
    ist = timezone(timedelta(hours=5, minutes=30))
    # 04:00 on the 8th in Kolkata is the 7th in UTC.
    merge_event(b, "DIRECT", ROUTE_RAG_SERVICE, False,
                now=datetime(2026, 8, 8, 4, 0, tzinfo=ist))
    assert rows_for_upsert(b)[0]["day"] == "2026-08-07"
    assert today_key(datetime(2026, 8, 7, 23, 30, tzinfo=timezone.utc)) == "2026-08-07"


# ── E: the number Stage 1 exists to produce ──────────────────────────────────
def test_retrieval_without_need_is_counted():
    rows = [
        {"day": "d", "strategy": "DIRECT", "route": ROUTE_RAG_SERVICE,
         "answered": 70, "grounded": 5},
        {"day": "d", "strategy": "RETRIEVAL", "route": ROUTE_RAG_SERVICE,
         "answered": 30, "grounded": 25},
    ]
    out = summarize(rows)
    assert out["answered"] == 100
    assert out["retrieved_without_need"]["count"] == 70
    assert out["retrieved_without_need"]["share"] == pytest.approx(0.70)
    assert out["retrieved_without_need"]["of_which_grounded"] == 5


def test_no_data_gives_a_null_share_not_zero():
    """"Nothing observed" and "never retrieves unnecessarily" are opposite
    findings and must not look identical."""
    out = summarize([])
    assert out["retrieved_without_need"]["share"] is None
    assert out["answered"] == 0


def test_direct_answered_directly_is_not_counted_as_waste():
    rows = [{"day": "d", "strategy": "DIRECT", "route": ROUTE_GENERAL_LLM,
             "answered": 50, "grounded": 0}]
    assert summarize(rows)["retrieved_without_need"]["count"] == 0


def test_the_matrix_keeps_every_pair():
    rows = [
        {"day": "d", "strategy": "CALCULATION", "route": ROUTE_RAG_SERVICE,
         "answered": 40, "grounded": 0},
        {"day": "d", "strategy": "CODE", "route": ROUTE_GENERAL_LLM,
         "answered": 12, "grounded": 0},
    ]
    m = summarize(rows)["matrix"]
    assert m["CALCULATION"][ROUTE_RAG_SERVICE] == 40
    assert m["CODE"][ROUTE_GENERAL_LLM] == 12


def test_summarize_ignores_rows_outside_the_enums():
    rows = [
        {"day": "d", "strategy": "DIRECT", "route": ROUTE_RAG_SERVICE,
         "answered": 10, "grounded": 0},
        {"day": "d", "strategy": "MADE_UP", "route": ROUTE_RAG_SERVICE,
         "answered": 999, "grounded": 999},
    ]
    assert summarize(rows)["answered"] == 10


@pytest.mark.parametrize("junk", [None, [], [{}], [{"strategy": "DIRECT"}]])
def test_summarize_survives_junk(junk):
    assert isinstance(summarize(junk)["answered"], int)


def test_no_verdict_about_correct_routing_is_encoded():
    """Stage 1 collects evidence; it must not decide what the evidence means.
    A key like "correct" or "agreement_rate" would bake in the conclusion the
    data is supposed to establish."""
    out = summarize([{"day": "d", "strategy": "CALCULATION",
                      "route": ROUTE_RAG_SERVICE, "answered": 5, "grounded": 0}])
    flat = repr(out).lower()
    for verdict_word in ("correct", "wrong", "agree", "mismatch", "should"):
        assert verdict_word not in flat
