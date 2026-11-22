"""Phase 19 slice 2 — safe integration adapter around review_response().

Purpose: app.py never talks to the validators directly. It calls
run_review_pipeline(), which is guaranteed to return a well-formed payload
even if a validator crashes — a review failure must NEVER break the reply.

Also owns the two pieces of wiring logic that need unit tests without
importing the 8,400-line app.py:
- attach_review_if_enabled(): the debug gate (DEBUG_REVIEW env var or the
  request's debug_review flag) deciding whether the payload is attached to
  the response body. The response text itself is never altered.
- format_review_log(): the one-line structured log record.

Deterministic only. Zero network calls. No retries, no regeneration, no
response mutation.
"""

import os
import time

try:  # package import (backend.review_engine.integration_adapter)
    from .review_engine import review_response
except ImportError:  # flat import (directory on sys.path)
    from review_engine import review_response

VALIDATOR_VERSION = "v1"


def run_review_pipeline(response_text: str, mode: str = "standard",
                        metadata: dict | None = None) -> dict:
    """Run the deterministic review pipeline, never raising.

    Returns:
    {
      "valid": bool, "score": float | None, "issues": [...], "checks": {...},
      "review_meta": {"mode", "validator_version", "execution_ms", "error"}
    }
    On any validator crash: valid=True, score=None, issues=[], error set —
    fail-open, because review is observational and must not block replies.
    """
    t0 = time.perf_counter()
    error = None
    try:
        result = review_response(response_text or "", mode)
        valid = bool(result.get("valid", True))
        score = result.get("score")
        issues = list(result.get("issues", []))
        checks = dict(result.get("checks", {}))
    except Exception as e:  # fail-open: a crash must never break the reply
        valid, score, issues, checks = True, None, [], {}
        error = f"{type(e).__name__}: {e}"

    execution_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "valid": valid,
        "score": score,
        "issues": issues,
        "checks": checks,
        "review_meta": {
            "mode": mode,
            "validator_version": VALIDATOR_VERSION,
            "execution_ms": execution_ms,
            "error": error,
        },
    }


def attach_review_if_enabled(body: dict, review: dict,
                             request_debug: bool = False) -> dict:
    """Attach the review payload under body["review"] ONLY when debugging is on.

    Debug is on when os.environ["DEBUG_REVIEW"] == "true" or the request
    carried debug_review=True. Never modifies any other key of body.
    """
    if os.getenv("DEBUG_REVIEW") == "true" or request_debug is True:
        body["review"] = review
    return body


def format_review_log(review: dict) -> str:
    """One structured log line per reviewed response."""
    meta = review.get("review_meta", {}) or {}
    return (
        f"[REVIEW] score={review.get('score')} valid={review.get('valid')} "
        f"issues={len(review.get('issues', []))} "
        f"execution_ms={meta.get('execution_ms')} mode={meta.get('mode')}"
    )
