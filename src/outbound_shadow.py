"""Durable shadow statistics for the outbound firewall.

ENFORCE_FIREWALL has been False since the gate was built, which is correct: you
do not arm a filter before you know what it would have caught. But the counters
behind that decision live in process memory and reset on every restart, and
this project deploys often — around ten times in a single day recently. So the
evidence needed to answer "is it safe to enforce?" has never survived long
enough to be read, and the question could only ever be settled on nerve.

WHAT IS STORED, AND WHAT IS NOT

One row per (day, reason_code) holding two counts. That is the whole schema.

No prompt, no answer, no generated content, no user identifier, no IP, no
verdict message. reason_code is validated against a fixed set before anything
is written, so a free-text string cannot reach storage even if a caller
constructs one — the same rule the logging path already follows, enforced here
rather than assumed.

Growth is bounded by construction: at most one row per reason code per day,
which is single digits of rows a day regardless of traffic.

WHY AGGREGATES AND NOT EVENTS

Per-event rows would answer richer questions and would also grow without limit,
carry timestamps precise enough to correlate with individual users, and turn a
counter into a log of what people asked. Daily buckets answer the question that
is actually blocking — what proportion would have been blocked, and under which
reason — and cannot become anything else.

This module is pure. It does no I/O and imports nothing from the app; the
transport lives in app.py so this can be tested in milliseconds.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

__all__ = [
    "VALID_REASON_CODES",
    "today_key",
    "merge_event",
    "rows_for_upsert",
    "summarize",
    "TABLE",
]

# The table name is fixed here rather than configured. A misconfigured name
# would silently write to nothing and look identical to "no traffic yet".
TABLE = "outbound_shadow_daily"

# Mirrors the OUTBOUND_REASON_* constants in app.py. Duplicated deliberately:
# importing app.py here would drag a thirty-second import into a pure module,
# and a test asserts the two sets are identical so the copy cannot drift.
VALID_REASON_CODES = frozenset({
    "APPROVED",
    "HALLUCINATION",
    "BLOCKED_OTHER",
    "GATE_ERROR",
    "GATE_TIMEOUT",
    "UNAVAILABLE",
})


def today_key(now: Optional[datetime] = None) -> str:
    """UTC day bucket. UTC, not local time, so buckets do not shift with the
    host's timezone and two processes cannot disagree about which day it is."""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d")


def merge_event(buckets: Dict[str, Dict[str, int]], reason_code: str,
                would_block: bool, now: Optional[datetime] = None) -> bool:
    """Fold one inspection into `buckets`. Returns whether it was recorded.

    An unknown reason code is dropped rather than stored. The gate only ever
    produces values from the enum, so a rejection here means something upstream
    changed — and silently persisting free text would be worse than losing a
    count.
    """
    if reason_code not in VALID_REASON_CODES:
        return False
    key = f"{today_key(now)}|{reason_code}"
    row = buckets.setdefault(key, {"inspected": 0, "would_block": 0})
    row["inspected"] += 1
    if would_block:
        row["would_block"] += 1
    return True


def rows_for_upsert(buckets: Dict[str, Dict[str, int]]) -> List[Dict[str, Any]]:
    """Buckets as rows ready to send. Empty input gives an empty list, so a
    flush with nothing pending sends no request at all."""
    rows = []
    for key, counts in sorted(buckets.items()):
        day, _, reason_code = key.partition("|")
        rows.append({
            "day": day,
            "reason_code": reason_code,
            "inspected": counts["inspected"],
            "would_block": counts["would_block"],
        })
    return rows


def summarize(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Totals and per-reason breakdown over whatever rows are given.

    block_rate is the number this whole exercise exists to produce: the share
    of real traffic that enforcing would have refused. Reported as None rather
    than 0.0 when nothing has been inspected, because "no data" and "nothing
    would be blocked" are opposite conclusions and must not look alike.
    """
    inspected = 0
    would_block = 0
    by_reason: Dict[str, Dict[str, int]] = {}
    days = set()

    for row in rows or []:
        try:
            i = int(row.get("inspected") or 0)
            w = int(row.get("would_block") or 0)
        except (TypeError, ValueError):
            continue
        code = str(row.get("reason_code") or "")
        if code not in VALID_REASON_CODES:
            continue
        inspected += i
        would_block += w
        entry = by_reason.setdefault(code, {"inspected": 0, "would_block": 0})
        entry["inspected"] += i
        entry["would_block"] += w
        if row.get("day"):
            days.add(str(row["day"]))

    return {
        "inspected": inspected,
        "would_block": would_block,
        "block_rate": (would_block / inspected) if inspected else None,
        "days_observed": len(days),
        "by_reason_code": by_reason,
    }
