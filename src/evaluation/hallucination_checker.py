from typing import Iterable


def hallucination_score(items: Iterable[dict]) -> float:
    rows = list(items)
    if not rows:
        return 0.0
    risky = sum(1 for row in rows if not row.get("expected_answer") and row.get("question"))
    return round((risky / len(rows)) * 100, 1)
