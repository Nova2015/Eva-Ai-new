"""Durable per-provider health — JARVIS 2A, observe only.

Mirrors mode_shadow.py exactly: append-only daily buckets, summed on read, so
two flushes of the same day cannot race and nothing needs an upsert. It stores a
count per (day, service, provider, outcome, latency_bucket) and NOTHING else —
never a prompt, an answer, a key, or a provider's raw message.

Every dimension is a fixed enum: the service that made the call, the provider,
the outcome (ok, or one of providers.ERROR_CODES), and a coarse latency bucket.
Latency is bucketed rather than stored raw so it stays append-delta-summable and
carries no free-text — the endpoint can still answer "what share of Groq calls
came back under 2s" without a row per call.

One table is shared by both services (the `service` column separates them), so
the backend endpoint can read a combined picture once the ML side also emits.

Pure module: no I/O, no app imports. Storage and transport live in app.py; the
ML service appends to the same table over its own Postgres connection.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

try:
    from providers import ERROR_CODES
except Exception:  # pragma: no cover
    from src.providers import ERROR_CODES  # type: ignore

__all__ = [
    "TABLE", "VALID_SERVICES", "VALID_PROVIDERS", "VALID_OUTCOMES",
    "VALID_LATENCY_BUCKETS", "latency_bucket",
    "merge_event", "rows_for_upsert", "summarize",
]

TABLE = "provider_shadow_daily"

VALID_SERVICES = frozenset({"backend", "ml"})

# The union across both services. The backend emits groq/openai/gemini; the ML
# side adds openrouter (JARVIS 2B). Listed here now so 2B needs no change to this
# module — an unknown label is still dropped, so the set only ever widens on
# purpose. eva_local joins it for Phase 2 Step 13: Step 12 records local calls
# through the same contract, and without this every one of those rows was
# discarded here, leaving the one provider with no durable history at all.
VALID_PROVIDERS = frozenset({"groq", "gemini", "openai", "openrouter", "local", "eva_local"})

# "ok" plus the fixed error enum shared with providers.classify_error. Imported
# so the two cannot drift; a value from outside means the enum changed shape.
VALID_OUTCOMES = frozenset({"ok"}) | frozenset(ERROR_CODES)

# Coarse, ordered latency buckets in milliseconds. "unknown" covers a call whose
# latency was not measured (e.g. an outcome recorded without timing).
VALID_LATENCY_BUCKETS = frozenset(
    {"lt_500", "lt_1000", "lt_2000", "lt_5000", "gte_5000", "unknown"})

# The buckets that count as "fast" for the under-2s share.
_UNDER_2S = ("lt_500", "lt_1000", "lt_2000")


def today_key(now: Optional[datetime] = None) -> str:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d")


def latency_bucket(latency_ms: Optional[float]) -> str:
    """Map a latency in ms to its bucket. None / non-numeric -> "unknown"."""
    if latency_ms is None:
        return "unknown"
    try:
        ms = float(latency_ms)
    except (TypeError, ValueError):
        return "unknown"
    if ms < 500:
        return "lt_500"
    if ms < 1000:
        return "lt_1000"
    if ms < 2000:
        return "lt_2000"
    if ms < 5000:
        return "lt_5000"
    return "gte_5000"


def merge_event(buckets: Dict[str, int], service: str, provider: str,
                outcome: str, latency_ms: Optional[float] = None,
                now: Optional[datetime] = None) -> bool:
    """Fold one provider call into the daily buckets. Returns whether it was
    recorded.

    service, provider and outcome are enum-checked before anything is stored;
    none can carry text derived from a prompt or a provider message. Latency is
    reduced to a bucket, never kept raw.
    """
    if (service not in VALID_SERVICES
            or provider not in VALID_PROVIDERS
            or outcome not in VALID_OUTCOMES):
        return False
    bucket = latency_bucket(latency_ms)
    key = f"{today_key(now)}|{service}|{provider}|{outcome}|{bucket}"
    buckets[key] = buckets.get(key, 0) + 1
    return True


def rows_for_upsert(buckets: Dict[str, int]) -> List[Dict[str, Any]]:
    rows = []
    for key, count in sorted(buckets.items()):
        day, service, provider, outcome, bucket = key.split("|", 4)
        rows.append({"day": day, "service": service, "provider": provider,
                     "outcome": outcome, "latency_bucket": bucket, "count": count})
    return rows


def summarize(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """The per-provider health picture, summed across the append-only rows.

    Per provider: how many calls, how many failed, the failure rate, and the
    share that returned under 2s. by_outcome shows which failures dominate
    (RATE_LIMITED vs TIMEOUT vs ...) — the signal that says whether a provider
    is unreliable or merely throttled.
    """
    total = 0
    days = set()
    by_service: Dict[str, int] = {}
    by_outcome: Dict[str, int] = {}
    per_provider: Dict[str, Dict[str, Any]] = {}

    for row in rows or []:
        service = str(row.get("service") or "")
        provider = str(row.get("provider") or "")
        outcome = str(row.get("outcome") or "")
        bucket = str(row.get("latency_bucket") or "")
        if (service not in VALID_SERVICES or provider not in VALID_PROVIDERS
                or outcome not in VALID_OUTCOMES
                or bucket not in VALID_LATENCY_BUCKETS):
            continue
        try:
            count = int(row.get("count") or 0)
        except (TypeError, ValueError):
            continue
        total += count
        by_service[service] = by_service.get(service, 0) + count
        by_outcome[outcome] = by_outcome.get(outcome, 0) + count
        p = per_provider.setdefault(
            provider, {"requests": 0, "ok": 0, "failures": 0, "latency": {}})
        p["requests"] += count
        if outcome == "ok":
            p["ok"] += count
        else:
            p["failures"] += count
        p["latency"][bucket] = p["latency"].get(bucket, 0) + count
        if row.get("day"):
            days.add(str(row["day"]))

    by_provider: Dict[str, Any] = {}
    for pid, p in per_provider.items():
        req = p["requests"]
        known = sum(v for b, v in p["latency"].items() if b != "unknown")
        under2 = sum(p["latency"].get(b, 0) for b in _UNDER_2S)
        by_provider[pid] = {
            "requests": req,
            "ok": p["ok"],
            "failures": p["failures"],
            "failure_rate": (p["failures"] / req) if req else None,
            "latency": p["latency"],
            "under_2s_share": (under2 / known) if known else None,
        }

    # The provider currently failing least (ties broken by volume). A fact about
    # observed reliability, not a routing instruction — nothing acts on it.
    healthiest = None
    ranked = [(pid, v) for pid, v in by_provider.items()
              if v["requests"] > 0 and v["failure_rate"] is not None]
    if ranked:
        healthiest = sorted(
            ranked, key=lambda kv: (kv[1]["failure_rate"], -kv[1]["requests"]))[0][0]

    return {
        "calls": total,
        "days_observed": len(days),
        "by_service": by_service,
        "by_outcome": by_outcome,
        "by_provider": by_provider,
        "healthiest_provider": healthiest,
    }
