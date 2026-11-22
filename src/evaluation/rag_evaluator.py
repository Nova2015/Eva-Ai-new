from typing import Iterable


def retrieval_quality_score(items: Iterable[dict]) -> float:
    rows = list(items)
    if not rows:
        return 0.0
    with_expected = sum(1 for row in rows if row.get("expected_answer"))
    return round((with_expected / len(rows)) * 100, 1)
