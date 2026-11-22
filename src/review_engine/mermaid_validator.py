"""Deterministic structural checks for ```mermaid fences in EVA responses.

THIS IS NOT FULL MERMAID PARSING. Real validation happens on the frontend,
where Chat.js loads mermaid@10.9.1 from CDN and calls mermaid.parse() /
render() (see frontend/src/pages/Chat.js MermaidBlock). These checks only
catch structural garbage cheaply and deterministically on the backend:
missing/unknown diagram header, empty diagram bodies, unbalanced brackets,
and prose masquerading as a diagram.

Formats discovered in the codebase (not invented):
- Fence tag is exactly ```mermaid (Chat.js routes lc === 'mermaid').
- EVA's system prompt mandates "flowchart TD|LR" and the frontend normalizes
  a leading "graph TD/TB/BT/LR/RL" to "flowchart ..." — both are accepted here.
"""

import re

_FENCE_RE = re.compile(r"```(\w*)[ \t]*\n?(.*?)```", re.S)

_HEADERS = (
    "graph",
    "flowchart",
    "sequenceDiagram",
    "pie",
    "gantt",
    "classDiagram",
    "stateDiagram-v2",
    "stateDiagram",
    "erDiagram",
    "journey",
)

# Tokens that essentially never appear in plain prose but do in mermaid bodies.
_MERMAID_TOKEN_RE = re.compile(
    r"-->|---|->>|-\.->|==>|:::|\bclassDef\b|\bsubgraph\b|\bparticipant\b|[\[\]{}()]|;\s*$",
    re.M,
)


def _body_lines(block):
    """Non-empty, non-comment lines of a mermaid block."""
    out = []
    for line in block.splitlines():
        s = line.strip()
        if s and not s.startswith("%%"):
            out.append(s)
    return out


def _brackets_balanced(block):
    """Count-based balance of [] () {} outside double-quoted strings."""
    counts = {"[": 0, "(": 0, "{": 0}
    close = {"]": "[", ")": "(", "}": "{"}
    in_str = False
    for c in block:
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c in counts:
            counts[c] += 1
        elif c in close:
            counts[close[c]] -= 1
    return all(v == 0 for v in counts.values())


def _looks_like_prose(lines):
    """Sentence-shaped text with none of the tokens mermaid bodies use."""
    joined = " ".join(lines)
    if _MERMAID_TOKEN_RE.search(joined):
        return False
    words = joined.split()
    return len(words) >= 6


def validate_mermaid(text: str) -> dict:
    """Validate ```mermaid fences. Returns {"passed", "issues", "applicable"}."""
    text = text or ""
    issues = []
    blocks = [body for lang, body in _FENCE_RE.findall(text) if (lang or "").lower() == "mermaid"]

    for i, block in enumerate(blocks):
        label = f"mermaid block {i + 1}"
        lines = _body_lines(block)

        if not lines:
            issues.append({"code": "empty_diagram", "detail": f"{label} is empty"})
            continue

        header = lines[0]
        has_header = any(
            re.match(rf"^{re.escape(h)}\b", header) for h in _HEADERS
        )

        if not has_header:
            if _looks_like_prose(lines):
                issues.append({
                    "code": "prose_not_diagram",
                    "detail": f"{label} contains sentences, not mermaid syntax",
                })
            else:
                issues.append({
                    "code": "missing_diagram_type",
                    "detail": f"{label} does not start with a known diagram type "
                              f"(first line: {header[:60]!r})",
                })
            # Header problems make the remaining structural checks moot.
            continue

        if len(lines) == 1:
            issues.append({
                "code": "empty_diagram",
                "detail": f"{label} has a '{header.split()[0]}' header but no nodes/edges",
            })

        if not _brackets_balanced(block):
            issues.append({
                "code": "unbalanced_brackets",
                "detail": f"{label} has unbalanced []/(){{}} brackets",
            })

    return {"passed": not issues, "issues": issues, "applicable": bool(blocks)}
