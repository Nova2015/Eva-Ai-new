"""Deterministic chart-block validator for EVA responses.

REAL FORMATS SUPPORTED (discovered in the codebase, not invented):

1. Primary fence — what the backend emits (src/app.py deterministic_chart_response,
   eva-ml-service/model_router.py deterministic_chart_answer, and CHART_SYSTEM_PROMPT):

       ```chart
       {"type": "pie", "title": "Sales", "data": [{"label": "A", "value": 40}]}
       ```

2. Content-detected fences — the frontend (Chat.js `looksLikeChartSpec`) ALSO routes
   ```json and untagged ``` fences to the chart renderer when the content parses to a
   JSON object with type in {pie, bar, line} AND (data[] OR labels[]+series[]).

3. Spec shapes (Chat.js `normalizeChartSpec`):
   - Format A:        {"type", "title", "data": [{"label"|"name"|"x": .., "value"|"y": ..}]}
   - Format B legacy: {"type", "title", "labels": [...], "series": [{"name", "data": [...]}]}

4. One fence may contain several concatenated top-level JSON objects; the frontend
   splits them (Chat.js `splitJsonObjects`) and renders each independently. That
   pattern is therefore treated as multiple charts, NOT as merged datasets.

Checks are pure functions of the input text. No LLM, no network, no retry.
"""

import json
import re

_FENCE_RE = re.compile(r"```(\w*)[ \t]*\n?(.*?)```", re.S)
_CHART_TYPES = {"pie", "bar", "line"}

# Word-boundary claim detection (same rationale as CHART_INTENT in model_router.py:
# bare substrings false-positive on navbar / command line / paragraph).
_CLAIM_RE = re.compile(
    r"\b(pie|bar|line)\s*(chart|graph)\b|\bchart\b|\bplot\b|\bvisuali[sz]ation\b|\bgraph\b",
    re.I,
)
_TYPE_MENTION_RE = re.compile(r"\b(pie|bar|line)\s*(?:chart|graph)\b", re.I)


def _split_json_objects(src):
    """Split concatenated top-level JSON objects (mirror of Chat.js splitJsonObjects)."""
    out = []
    depth, start, in_str, esc = 0, -1, False, False
    for i, c in enumerate(src):
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                out.append(src[start : i + 1])
                start = -1
    return out


def _is_chart_spec(obj):
    """Mirror of Chat.js looksLikeChartSpec: what the frontend treats as a chart."""
    return (
        isinstance(obj, dict)
        and obj.get("type") in _CHART_TYPES
        and (
            isinstance(obj.get("data"), list)
            or (isinstance(obj.get("labels"), list) and isinstance(obj.get("series"), list))
        )
    )


def _spec_is_empty(spec):
    """True when the spec would render nothing (mirrors normalizeChartSpec fail paths)."""
    data = spec.get("data")
    if isinstance(data, list):
        return len(data) == 0
    labels = spec.get("labels")
    series = spec.get("series")
    if isinstance(labels, list) and isinstance(series, list):
        if not labels or not series:
            return True
        return all(not (isinstance(s, dict) and s.get("data")) for s in series)
    # No data AND no labels/series at all.
    return True


def _labels_of(spec):
    data = spec.get("data")
    if isinstance(data, list):
        out = []
        for d in data:
            if isinstance(d, dict):
                label = d.get("label", d.get("name", d.get("x")))
                if label is not None:
                    out.append(str(label))
        return out
    labels = spec.get("labels")
    return [str(l) for l in labels] if isinstance(labels, list) else []


def validate_charts(text: str) -> dict:
    """Validate chart usage in a response. Returns {"passed", "issues", "applicable"}."""
    text = text or ""
    issues = []

    fences = _FENCE_RE.findall(text)
    prose = _FENCE_RE.sub(" ", text)

    chart_specs = []       # parsed spec dicts from chart-routed fences
    malformed_chart = 0    # ```chart fences that do not parse
    chart_block_count = 0  # fences the frontend would render as chart(s)
    has_mermaid = False

    for lang, body in fences:
        lc = (lang or "").lower()
        body = body.strip()
        if lc == "mermaid":
            has_mermaid = True
            continue
        if lc == "chart":
            chart_block_count += 1
            try:
                chart_specs.append(json.loads(body))
            except (ValueError, TypeError):
                pieces = _split_json_objects(body)
                parsed = []
                for p in pieces:
                    try:
                        parsed.append(json.loads(p))
                    except (ValueError, TypeError):
                        pass
                if len(pieces) > 1 and parsed:
                    chart_specs.extend(parsed)
                else:
                    malformed_chart += 1
                    issues.append({
                        "code": "malformed_block",
                        "detail": "```chart block exists but its JSON does not parse",
                    })
        elif lc in ("json", ""):
            # Content-detected chart (frontend behavior). Non-chart JSON is NOT
            # a chart block — the frontend shows it as a code block.
            try:
                obj = json.loads(body)
            except (ValueError, TypeError):
                continue
            if _is_chart_spec(obj):
                chart_block_count += 1
                chart_specs.append(obj)

    # empty_data
    for spec in chart_specs:
        if _is_chart_spec(spec) or spec.get("type") in _CHART_TYPES:
            if _spec_is_empty(spec):
                issues.append({
                    "code": "empty_data",
                    "detail": f"chart block '{spec.get('title', '?')}' parses but data/datasets/labels are empty",
                })

    # merged_datasets (heuristic — flag, do not fix):
    # (a) duplicate labels inside one block (two series collapsed into one), or
    # (b) prose requests >= 2 distinct chart types but only ONE chart block exists.
    for spec in chart_specs:
        labels = _labels_of(spec)
        if labels and len(labels) != len(set(labels)):
            issues.append({
                "code": "merged_datasets",
                "detail": f"chart block '{spec.get('title', '?')}' repeats labels — looks like multiple series merged into one dataset",
            })
    distinct_types_requested = {m.group(1).lower() for m in _TYPE_MENTION_RE.finditer(prose)}
    if len(distinct_types_requested) >= 2 and chart_block_count == 1:
        issues.append({
            "code": "merged_datasets",
            "detail": f"prose requests {len(distinct_types_requested)} distinct chart types but only one chart block is present",
        })

    # claim_without_block
    claim = _CLAIM_RE.search(prose)
    if claim and chart_block_count == 0 and malformed_chart == 0:
        claimed = claim.group(0).lower()
        # A bare "graph" claim satisfied by a mermaid diagram is not a chart failure.
        if not (has_mermaid and "graph" in claimed and not _TYPE_MENTION_RE.search(prose)):
            issues.append({
                "code": "claim_without_block",
                "detail": f"text mentions '{claim.group(0)}' but contains no chart block",
            })

    applicable = bool(chart_block_count or malformed_chart or claim)
    return {"passed": not issues, "issues": issues, "applicable": applicable}
