from typing import Iterable


def citation_match_score(items: Iterable[dict]) -> float:
    rows = list(items)
    if not rows:
        return 0.0
    cited = sum(1 for row in rows if row.get("citation") or row.get("source"))
    return round((cited / len(rows)) * 100, 1)
