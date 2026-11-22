"""Shadow comparison: the strategy EVA reasons its way to, against the route
that actually answered.

The cognitive engine already selects one of eight strategies for every message,
using understanding, assessment and conversation history. It is tested,
mutation-verified, and measured over 906 real messages. And it decides nothing:
select_strategy runs inside refine(), which runs in _finalize_response, AFTER
the answer exists. chat_bridge.py says so in a comment — "Reported, never acted
on".

What actually routes a message is a regex cascade in route_query(), thirteen
literal document phrases in use_rag, and an unconditional call to the RAG
service that answers almost everything. Observed live: "name three prime
numbers" came back with mode_used=hybrid and retrievers=bm25,vector while the
cognitive engine said DIRECT. Retrieval ran because retrieval always runs.

So the question worth measuring before changing any of it is not "do the two
deciders agree" but: HOW OFTEN DOES EVA RETRIEVE WHEN ITS OWN REASONING SAYS IT
DOES NOT NEED TO, and does that retrieval end up grounding anything.

NO JUDGEMENT IS ENCODED HERE. This records the pair and the grounding outcome,
and reports a matrix. Deciding that DIRECT-plus-retrieval is waste, or that
CALCULATION-plus-general-LLM is a missing tool, is what the evidence is FOR —
building that opinion into the collector would bias the data it gathers.

Pure module: no I/O, no imports from app. Storage and transport live in app.py.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

__all__ = [
    "TABLE", "VALID_STRATEGIES", "VALID_ROUTES",
    "route_of", "merge_event", "rows_for_upsert", "summarize",
]

TABLE = "routing_shadow_daily"

# Mirrors cognitive.state.ReasoningStrategy. Duplicated rather than imported so
# this module stays free of the cognitive package; a test asserts the two sets
# are identical so the copy cannot drift.
VALID_STRATEGIES = frozenset({
    "DIRECT", "RETRIEVAL", "CALCULATION", "CODE",
    "ANALYSIS", "MULTI_STEP", "TOOL_ASSISTED", "CLARIFICATION",
})

# What actually produced the answer, as far as the response body can show.
ROUTE_CHART = "CHART"              # deterministic chart / table-to-chart
ROUTE_SPREADSHEET = "SPREADSHEET"  # a generated .xlsx
ROUTE_VISION = "VISION"            # _run_vision_agent
ROUTE_RAG_SERVICE = "RAG_SERVICE"  # the unconditional /rag/chat passthrough
ROUTE_FALLBACK = "FALLBACK"        # _llm_fallback after low confidence
ROUTE_GENERAL_LLM = "GENERAL_LLM"  # the direct provider call
ROUTE_UNKNOWN = "UNKNOWN"

VALID_ROUTES = frozenset({
    ROUTE_CHART, ROUTE_SPREADSHEET, ROUTE_VISION, ROUTE_RAG_SERVICE,
    ROUTE_FALLBACK, ROUTE_GENERAL_LLM, ROUTE_UNKNOWN,
})

# Providers that identify an artifact route rather than a text answer. Kept as
# a mapping so adding a tool means adding a line here, not editing a chain of
# conditionals and hoping the order is right.
_ARTIFACT_PROVIDERS = {
    "chart": ROUTE_CHART,
    "spreadsheet": ROUTE_SPREADSHEET,
}


def route_of(payload: Optional[Dict[str, Any]]) -> str:
    """Which path answered, read from the response body only.

    Order matters. The chart and vision branches return before anything else
    can run, so they are read first.

    Then RETRIEVAL: if the retrieval service produced the answer — mode_used or
    retrievers_used is present — the route is RAG_SERVICE, EVEN IF the LLM
    provider fell back to a backup while generating. This is Update 37A's
    correction. `fallback_used` on the wire is route_and_call's
    used_fallback (the primary provider failed and a backup answered); it is a
    property of WHICH MODEL answered, not of whether retrieval ran. Reading it
    as a route mislabelled retrieval queries as FALLBACK whenever a provider
    fell back — which spikes on quota-heavy days — so the count of DIRECT
    questions answered by retrieval moved with provider availability rather
    than with routing. Provider reliability is already tracked by the
    AI-outcome telemetry; it does not belong in this route.

    FALLBACK now means only what the enum comment always said: the backend's
    low-confidence _llm_fallback, which answers from the general model WITHOUT
    retrieval and sets fallback_mode with no retrieval metadata attached.

    NOTE ON HISTORICAL DATA: rows written before this change used the old
    precedence, so DIRECT->RAG_SERVICE was undercounted then (retrieval queries
    with a provider fallback sat in DIRECT->FALLBACK). A rise in
    retrieved_without_need across the change is the label being corrected, not
    retrieval increasing.
    """
    if not isinstance(payload, dict):
        return ROUTE_UNKNOWN

    provider = str(payload.get("provider") or "").lower()

    if provider in _ARTIFACT_PROVIDERS:
        return _ARTIFACT_PROVIDERS[provider]
    if provider.startswith("vision"):
        return ROUTE_VISION
    # Retrieval ran → RAG_SERVICE, before any fallback signal. A provider
    # fallback does not unmake the retrieval that already happened.
    if payload.get("mode_used") or payload.get("retrievers_used"):
        return ROUTE_RAG_SERVICE
    # Backend low-confidence fallback: no retrieval metadata is attached.
    if payload.get("fallback_mode"):
        return ROUTE_FALLBACK
    if provider:
        return ROUTE_GENERAL_LLM
    return ROUTE_UNKNOWN


def grounded_of(payload: Optional[Dict[str, Any]]) -> bool:
    """Whether the answer cited anything retrieval found.

    Retrieval that grounds nothing is the expensive case: it costs a network
    call and can push irrelevant context at the model, which is what the
    grounded-sources work exists to contain.
    """
    if not isinstance(payload, dict):
        return False
    sources = payload.get("sources")
    return bool(isinstance(sources, (list, tuple)) and len(sources) > 0)


def today_key(now: Optional[datetime] = None) -> str:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d")


def merge_event(buckets: Dict[str, Dict[str, int]], strategy: str, route: str,
                grounded: bool, now: Optional[datetime] = None) -> bool:
    """Fold one answered message in. Returns whether it was recorded.

    Both labels are enum-checked before anything is stored. Neither can carry
    text derived from the question or the answer, and a value from outside the
    enum means something upstream changed rather than something worth keeping.
    """
    if strategy not in VALID_STRATEGIES or route not in VALID_ROUTES:
        return False
    key = f"{today_key(now)}|{strategy}|{route}"
    row = buckets.setdefault(key, {"answered": 0, "grounded": 0})
    row["answered"] += 1
    if grounded:
        row["grounded"] += 1
    return True


def rows_for_upsert(buckets: Dict[str, Dict[str, int]]) -> List[Dict[str, Any]]:
    rows = []
    for key, counts in sorted(buckets.items()):
        day, strategy, route = key.split("|", 2)
        rows.append({
            "day": day,
            "strategy": strategy,
            "route": route,
            "answered": counts["answered"],
            "grounded": counts["grounded"],
        })
    return rows


def summarize(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """The matrix, and the one number this was built to produce.

    retrieved_without_need counts messages the engine judged DIRECT that were
    answered by the retrieval service anyway. It is reported as a count and a
    share, never as a verdict: whether that is waste depends on whether the
    retrieval grounded anything, which is why grounded travels alongside it.
    """
    total = 0
    matrix: Dict[str, Dict[str, int]] = {}
    by_strategy: Dict[str, int] = {}
    by_route: Dict[str, int] = {}
    direct_via_retrieval = 0
    direct_via_retrieval_grounded = 0
    days = set()

    for row in rows or []:
        strategy = str(row.get("strategy") or "")
        route = str(row.get("route") or "")
        if strategy not in VALID_STRATEGIES or route not in VALID_ROUTES:
            continue
        try:
            answered = int(row.get("answered") or 0)
            grounded = int(row.get("grounded") or 0)
        except (TypeError, ValueError):
            continue

        total += answered
        matrix.setdefault(strategy, {})
        matrix[strategy][route] = matrix[strategy].get(route, 0) + answered
        by_strategy[strategy] = by_strategy.get(strategy, 0) + answered
        by_route[route] = by_route.get(route, 0) + answered
        if row.get("day"):
            days.add(str(row["day"]))

        if strategy == "DIRECT" and route == ROUTE_RAG_SERVICE:
            direct_via_retrieval += answered
            direct_via_retrieval_grounded += grounded

    return {
        "answered": total,
        "days_observed": len(days),
        "matrix": matrix,
        "by_strategy": by_strategy,
        "by_route": by_route,
        "retrieved_without_need": {
            "count": direct_via_retrieval,
            "share": (direct_via_retrieval / total) if total else None,
            "of_which_grounded": direct_via_retrieval_grounded,
        },
    }
