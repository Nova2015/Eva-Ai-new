"""Pytest suite for Phase 19 slice 1 deterministic validators.

Run:  pytest backend/review_engine/test_review_engine.py -v
"""

try:
    from backend.review_engine.review_engine import review_response
except ImportError:
    from review_engine import review_response


def _codes(result):
    return [i["code"] for i in result["issues"]]


# ── Required fixtures ─────────────────────────────────────────────────────────

def test_fake_chart_claim():
    """Text says a chart was created but no chart block exists."""
    text = "Done! I've created a pie chart of your sales data above."
    r = review_response(text)
    assert r["valid"] is False
    assert "claim_without_block" in _codes(r)
    assert r["checks"]["chart"]["passed"] is False


def test_broken_mermaid():
    """graph TD with unbalanced brackets."""
    text = (
        "Here is the flow:\n\n"
        "```mermaid\n"
        "graph TD\n"
        "  A[Start --> B(End)\n"
        "```\n"
    )
    r = review_response(text)
    assert r["valid"] is False
    assert "unbalanced_brackets" in _codes(r)


def test_python_syntax_error():
    text = "```python\ndef f( :\n```"
    r = review_response(text)
    assert r["valid"] is False
    assert "python_syntax_error" in _codes(r)
    detail = next(i["detail"] for i in r["issues"] if i["code"] == "python_syntax_error")
    assert "line" in detail  # lineno is reported


def test_valid_json_block():
    text = 'Config:\n\n```json\n{"a": 1, "b": [2, 3]}\n```\n'
    r = review_response(text)
    assert r["valid"] is True
    assert r["issues"] == []
    assert r["checks"]["code"]["passed"] is True


def test_clean_prose_empty_denominator():
    """No blocks, no claims: valid, and score defined (1.0) with empty denominator."""
    text = "Paris is the capital of France. Berlin is the capital of Germany."
    r = review_response(text)
    assert r["valid"] is True
    assert r["score"] == 1.0
    assert all(not c["applicable"] for c in r["checks"].values())


def test_multi_chart_merged():
    """Prose requests pie AND bar AND line, but one block holds all 9 values."""
    text = (
        "Here are the pie chart, bar chart and line chart you asked for:\n\n"
        "```chart\n"
        '{"type": "pie", "title": "Everything", "data": ['
        '{"label": "A", "value": 40}, {"label": "B", "value": 30}, {"label": "C", "value": 30}, '
        '{"label": "Food", "value": 500}, {"label": "Rent", "value": 1000}, {"label": "Travel", "value": 300}, '
        '{"label": "Jan", "value": 10}, {"label": "Feb", "value": 20}, {"label": "Mar", "value": 30}]}\n'
        "```\n"
    )
    r = review_response(text)
    assert r["valid"] is False
    assert "merged_datasets" in _codes(r)


# ── Additional coverage ───────────────────────────────────────────────────────

def test_malformed_chart_block():
    text = '```chart\n{"type": "pie", "data": [\n```'
    r = review_response(text)
    assert r["valid"] is False
    assert "malformed_block" in _codes(r)


def test_empty_chart_data():
    text = '```chart\n{"type": "bar", "title": "Empty", "data": []}\n```'
    r = review_response(text)
    assert r["valid"] is False
    assert "empty_data" in _codes(r)


def test_legacy_labels_series_format_valid():
    """Format B (labels + series) is a REAL supported format — must pass."""
    text = (
        "```chart\n"
        '{"type": "pie", "title": "Sales", "labels": ["A", "B"], '
        '"series": [{"name": "Revenue", "data": [40, 30]}]}\n'
        "```"
    )
    r = review_response(text)
    assert r["valid"] is True


def test_three_separate_chart_blocks_valid():
    """The correct multi-chart shape (one block per request) must NOT be flagged."""
    text = (
        "Pie chart, bar chart and line chart:\n\n"
        '```chart\n{"type": "pie", "title": "Sales", "data": [{"label": "A", "value": 40}]}\n```\n\n'
        '```chart\n{"type": "bar", "title": "Expenses", "data": [{"label": "Food", "value": 500}]}\n```\n\n'
        '```chart\n{"type": "line", "title": "Revenue", "data": [{"label": "Jan", "value": 10}]}\n```\n'
    )
    r = review_response(text)
    assert r["valid"] is True
    assert r["score"] == 1.0


def test_unclosed_fence():
    text = "Here is code:\n```python\nprint('hi')\n"
    r = review_response(text)
    assert r["valid"] is False
    assert "unclosed_fence" in _codes(r)


def test_mermaid_prose_not_diagram():
    text = (
        "```mermaid\n"
        "This diagram shows how the user logs in and then reaches the dashboard eventually.\n"
        "```"
    )
    r = review_response(text)
    assert r["valid"] is False
    assert "prose_not_diagram" in _codes(r)


def test_mermaid_missing_header():
    text = "```mermaid\nA --> B\nB --> C\n```"
    r = review_response(text)
    assert r["valid"] is False
    assert "missing_diagram_type" in _codes(r)


def test_valid_mermaid_flowchart():
    text = (
        "```mermaid\n"
        "flowchart TD\n"
        "  S([Start]) --> A[Collect input]\n"
        "  A --> B{Valid?}\n"
        "  B -->|Yes| C(Save)\n"
        "```"
    )
    r = review_response(text)
    assert r["valid"] is True


def test_js_heuristic_unbalanced():
    text = "```js\nfunction f() { if (x) { return 1; \n```"
    r = review_response(text)
    assert r["valid"] is False
    assert "js_syntax_error" in _codes(r)


def test_score_is_ratio_of_applicable_validators():
    """One failing validator out of two applicable -> score 0.5."""
    text = (
        'Valid json:\n```json\n{"ok": true}\n```\n\n'
        "Broken mermaid:\n```mermaid\ngraph TD\n  A[Start --> B\n```\n"
    )
    r = review_response(text)
    assert r["valid"] is False
    assert r["checks"]["code"]["passed"] is True
    assert r["checks"]["mermaid"]["passed"] is False
    assert r["checks"]["chart"]["applicable"] is False
    assert r["score"] == 0.5
