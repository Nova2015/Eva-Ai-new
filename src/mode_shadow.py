"""Daily counts of the persona the classifier WOULD pick — Update 37, observe.

Mirrors routing_shadow.py exactly: append-only daily buckets, summed on read,
so two flushes of the same day cannot race and nothing needs an upsert. It
stores a count per (day, mode, signal) and NOTHING else — never the message,
the answer, the user, or an IP. The classifier's guess is an enum; how strongly
it fired is an enum; that is all a durable record of "how EVA would route" needs.

No verdict is encoded here. Whether a mode fires too often or too rarely is the
question the evidence answers; building an opinion into the collector would bias
the data toward it — the same discipline the routing shadow keeps.

Pure module: no I/O, no app imports. Storage and transport live in app.py.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

try:
    from mode_classifier import VALID_MODES, VALID_SIGNALS
except Exception:  # pragma: no cover
    from src.mode_classifier import VALID_MODES, VALID_SIGNALS  # type: ignore

__all__ = ["TABLE", "VALID_MODES", "VALID_SIGNALS",
           "merge_event", "rows_for_upsert", "summarize"]

TABLE = "mode_shadow_daily"


def today_key(now: Optional[datetime] = None) -> str:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d")


def merge_event(buckets: Dict[str, int], mode: str, signal: str,
                now: Optional[datetime] = None) -> bool:
    """Fold one classified message into the daily buckets. Returns whether it
    was recorded.

    Both labels are enum-checked before anything is stored. Neither can carry
    text derived from the message; a value from outside the enum means the
    classifier changed shape, not that a new label is worth keeping.
    """
    if mode not in VALID_MODES or signal not in VALID_SIGNALS:
        return False
    key = f"{today_key(now)}|{mode}|{signal}"
    buckets[key] = buckets.get(key, 0) + 1
    return True


def rows_for_upsert(buckets: Dict[str, int]) -> List[Dict[str, Any]]:
    rows = []
    for key, count in sorted(buckets.items()):
        day, mode, signal = key.split("|", 2)
        rows.append({"day": day, "mode": mode, "signal": signal, "count": count})
    return rows


def summarize(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """The distribution, summed across the append-only rows.

    by_mode answers "how would traffic split across personas"; the strong/weak
    split within by_signal is what a later confidence threshold would use to
    decide which guesses are trustworthy enough to act on.
    """
    total = 0
    by_mode: Dict[str, int] = {}
    by_signal: Dict[str, int] = {}
    matrix: Dict[str, Dict[str, int]] = {}
    days = set()

    for row in rows or []:
        mode = str(row.get("mode") or "")
        signal = str(row.get("signal") or "")
        if mode not in VALID_MODES or signal not in VALID_SIGNALS:
            continue
        try:
            count = int(row.get("count") or 0)
        except (TypeError, ValueError):
            continue
        total += count
        by_mode[mode] = by_mode.get(mode, 0) + count
        by_signal[signal] = by_signal.get(signal, 0) + count
        matrix.setdefault(mode, {})
        matrix[mode][signal] = matrix[mode].get(signal, 0) + count
        if row.get("day"):
            days.add(str(row["day"]))

    # The share of traffic that fired a NON-general mode at STRONG strength —
    # the population Update 37 would actually route on.
    strong_non_general = sum(
        matrix.get(m, {}).get("strong", 0)
        for m in VALID_MODES if m != "general")

    return {
        "classified": total,
        "days_observed": len(days),
        "by_mode": by_mode,
        "by_signal": by_signal,
        "matrix": matrix,
        "strong_non_general": strong_non_general,
        "strong_non_general_share": (strong_non_general / total) if total else None,
    }
