"""Pytest suite for slice 3 status derivation.

Run:  pytest backend/review_engine -v
"""

try:
    from backend.review_engine.integration_adapter import run_review_pipeline
    from backend.review_engine.review_status import derive_status, FATAL_CODES, WARN_CODES
except ImportError:
    from integration_adapter import run_review_pipeline
    from review_status import derive_status, FATAL_CODES, WARN_CODES


def test_fatal_issue_maps_to_failed():
    review = run_review_pipeline("```mermaid\ngraph TD\n  A[Start --> B(End)\n```")
    assert "unbalanced_brackets" in [i["code"] for i in review["issues"]]
    s = derive_status(review)
    assert s["status"] == "FAILED"
    assert s["badge"] is True


def test_warn_only_issue_maps_to_warning():
    review = run_review_pipeline("Done! I've created a pie chart of your sales above.")
    codes = [i["code"] for i in review["issues"]]
    assert codes == ["claim_without_block"]
    s = derive_status(review)
    assert s["status"] == "WARNING"
    assert s["badge"] is True


def test_clean_response_with_valid_chart_block_is_valid():
    review = run_review_pipeline(
        '```chart\n{"type": "pie", "title": "Sales", "data": [{"label": "A", "value": 40}]}\n```'
    )
    assert review["issues"] == []
    s = derive_status(review)
    assert s["status"] == "VALID"
    assert s["badge"] is True


def test_plain_prose_gets_no_badge():
    """KEY case: nothing checkable -> no status, no badge. Never default-green."""
    review = run_review_pipeline("Paris is the capital of France.")
    assert review["issues"] == []
    s = derive_status(review)
    assert s["status"] is None
    assert s["badge"] is False


def test_review_meta_error_maps_to_unknown():
    review = {
        "valid": True, "score": None, "issues": [], "checks": {},
        "review_meta": {"mode": "standard", "validator_version": "v1",
                        "execution_ms": 0, "error": "RuntimeError: boom"},
    }
    s = derive_status(review)
    assert s["status"] == "UNKNOWN"
    assert s["badge"] is True


def test_fatal_beats_warn_when_both_present():
    review = run_review_pipeline(
        "Here are the pie chart and bar chart:\n\n"   # merged_datasets (warn)
        '```chart\n{"type": "pie", "data": [\n```'    # malformed_block (fatal)
    )
    codes = [i["code"] for i in review["issues"]]
    assert "malformed_block" in codes
    s = derive_status(review)
    assert s["status"] == "FAILED"


def test_unrecognized_code_is_warning_not_valid():
    review = {
        "valid": False, "score": 0.5,
        "issues": [{"code": "some_future_code", "detail": "x"}],
        "checks": {"chart": {"passed": False, "issues": [], "applicable": True}},
        "review_meta": {"mode": "standard", "validator_version": "v1",
                        "execution_ms": 1, "error": None},
    }
    s = derive_status(review)
    assert s["status"] == "WARNING"
    assert s["badge"] is True


def test_code_sets_match_validators():
    """Guard against drift between validators and severity sets."""
    emitted = {
        "claim_without_block", "malformed_block", "empty_data", "merged_datasets",
        "missing_diagram_type", "empty_diagram", "unbalanced_brackets",
        "prose_not_diagram", "python_syntax_error", "json_parse_error",
        "js_syntax_error", "unclosed_fence",
    }
    assert FATAL_CODES | WARN_CODES == emitted
    assert not (FATAL_CODES & WARN_CODES)
