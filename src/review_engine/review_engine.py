"""Phase 19 slice 1 orchestrator — deterministic response review.

Runs the three validators (chart, mermaid, code) and aggregates results.

score is a DETERMINISTIC ratio: passed applicable validators / applicable
validators. A validator that found nothing to check (e.g. no code fences in
the text) is excluded from the denominator. With an empty denominator the
score is 1.0 — clean prose is not penalized for containing nothing checkable.

NO retry logic. NO LLM. NO network calls. `mode` is reserved for later slices
and currently does not change behavior.
"""

try:  # package import (backend.review_engine.review_engine)
    from .chart_validator import validate_charts
    from .code_validator import validate_code
    from .mermaid_validator import validate_mermaid
except ImportError:  # flat import (directory on sys.path)
    from chart_validator import validate_charts
    from code_validator import validate_code
    from mermaid_validator import validate_mermaid


def review_response(text: str, mode: str = "standard") -> dict:
    checks = {
        "chart": validate_charts(text),
        "mermaid": validate_mermaid(text),
        "code": validate_code(text),
    }

    issues = []
    for result in checks.values():
        issues.extend(result.get("issues", []))

    applicable = [r for r in checks.values() if r.get("applicable")]
    if applicable:
        score = sum(1 for r in applicable if r.get("passed")) / len(applicable)
    else:
        score = 1.0

    return {
        "valid": not issues,
        "score": round(score, 4),
        "issues": issues,
        "checks": checks,
    }
