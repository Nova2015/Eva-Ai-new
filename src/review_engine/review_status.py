"""Phase 19 slice 3 — severity mapping from review issues to a badge status.

Issue codes below were grepped from the slice 1 validators (chart_validator,
mermaid_validator, code_validator) — they are the EXACT strings emitted.
NOTE one deliberate deviation from the slice 3 spec draft: the spec listed
"js_heuristic" as a warn code, but the validator emits "js_syntax_error"
(for both the `node --check` path and the heuristic path). The emitted
string is used here.

Severity model:
- FATAL  -> the block would break rendering (chart won't draw, mermaid won't
            parse, code is syntactically dead, fence never closes) -> FAILED
- WARN   -> content still renders but is suspect (claimed chart missing,
            datasets look merged, JS flagged by a heuristic)        -> WARNING
- Unrecognized future codes are treated as WARNING, never silently VALID.

Badge rule: a badge is shown only when there was something to verify.
"Checkable" is derived from review["checks"][*]["applicable"] (set by the
validators when they actually found blocks/claims) — NEVER from prose, and
the status NEVER defaults to VALID for plain chat.
"""

FATAL_CODES = {
    # chart
    "malformed_block",
    "empty_data",
    # mermaid
    "missing_diagram_type",
    "empty_diagram",
    "unbalanced_brackets",
    "prose_not_diagram",
    # code
    "python_syntax_error",
    "json_parse_error",
    "unclosed_fence",
}

WARN_CODES = {
    "claim_without_block",
    "merged_datasets",
    "js_syntax_error",  # spec draft said "js_heuristic"; this is the emitted code
}


def derive_status(review: dict) -> dict:
    """Map a run_review_pipeline() payload to {"status": str|None, "badge": bool}."""
    review = review or {}

    meta = review.get("review_meta") or {}
    if meta.get("error"):
        return {"status": "UNKNOWN", "badge": True}

    codes = [i.get("code") for i in review.get("issues", []) if isinstance(i, dict)]
    if any(c in FATAL_CODES for c in codes):
        return {"status": "FAILED", "badge": True}
    if codes:  # warn codes and any unrecognized code -> WARNING, never VALID
        return {"status": "WARNING", "badge": True}

    checks = review.get("checks") or {}
    checkable = any(
        isinstance(c, dict) and c.get("applicable") for c in checks.values()
    )
    if checkable:
        return {"status": "VALID", "badge": True}

    # Plain prose: nothing was verifiable, so assert nothing.
    return {"status": None, "badge": False}
