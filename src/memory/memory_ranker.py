import re
from datetime import datetime


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z0-9_]+", (text or "").lower()))


def rank_items(query: str, items: list[dict], limit: int = 8) -> list[dict]:
    query_tokens = _tokens(query)
    ranked = []

    for item in items:
        if item.get("validation_status") == "superseded":
            continue

        content = item.get("content") or item.get("message") or ""
        item_tokens = _tokens(content)
        overlap = len(query_tokens & item_tokens)

        importance = int(item.get("importance") or 1)
        recency = 0.0

        created_at = item.get("created_at")
        if created_at:
            try:
                age_days = max(
                    (datetime.utcnow() - datetime.fromisoformat(created_at)).days,
                    0,
                )
                recency = max(
                    0.0,
                    1.0 - min(age_days, 30) / 30,
                )
            except Exception:
                recency = 0.0

        tier = item.get("memory_tier") or "episodic"
        validation = item.get("validation_status") or "unvalidated"

        lifecycle_bonus = 0.0

        if tier == "semantic":
            lifecycle_bonus += 2.0

        if validation == "user_confirmed":
            lifecycle_bonus += 1.0
        elif validation == "system_verified":
            lifecycle_bonus += 1.5

        score = (
            overlap * 2.0
            + importance * 1.2
            + recency
            + lifecycle_bonus
        )

        ranked.append({
            **item,
            "score": score,
        })

    ranked.sort(
        key=lambda row: row.get("score", 0),
        reverse=True,
    )

    return ranked[:limit]