"""Slice 6 — eligibility detection for the chat Run button.

mark_runnable() CLASSIFIES ONLY — it executes nothing, calls nothing.
Eligible iff ALL of:
  - EXACTLY ONE fenced code block in the text (chart/mermaid fences are EVA
    visualization payloads, not code, and are not counted),
  - language is python or javascript (incl. py/python3/js/node aliases),
  - code length within the runtime_limits cap.
No prose-vs-code judgment — the single-block rule is the gate.

runnable_payload() is the chat-route wrapper: it NEVER raises; any internal
failure degrades to {"eligible": False, "language": None} so chat always
returns. It deliberately omits the code — the frontend already has the block.
"""

import re

try:  # package import
    from .runtime_limits import max_code_chars
except ImportError:  # flat import
    from runtime_limits import max_code_chars

_FENCE_RE = re.compile(r"```(\w*)[ \t]*\n?(.*?)```", re.S)

# EVA visualization fences — not code blocks for eligibility purposes.
_NON_CODE_TAGS = {"chart", "mermaid"}

_ALIASES = {"py": "python", "python3": "python", "js": "javascript", "node": "javascript"}
_SUPPORTED = {"python", "javascript"}


def mark_runnable(text: str) -> dict:
    """Classify a chat answer's runnability. EXECUTES NOTHING."""
    blocks = [
        (lang.lower(), body.strip())
        for lang, body in _FENCE_RE.findall(text or "")
        if lang.lower() not in _NON_CODE_TAGS
    ]

    if len(blocks) == 0:
        return {"eligible": False, "reason": "no_code_block", "language": None, "code": None}
    if len(blocks) > 1:
        return {"eligible": False, "reason": "multiple_code_blocks", "language": None, "code": None}

    lang, code = blocks[0]
    lang = _ALIASES.get(lang, lang)
    if lang not in _SUPPORTED:
        return {"eligible": False, "reason": "unsupported_language", "language": None, "code": None}
    if len(code) > max_code_chars():
        return {"eligible": False, "reason": "too_large", "language": lang, "code": None}

    return {"eligible": True, "reason": "eligible", "language": lang, "code": code}


def runnable_payload(text: str) -> dict:
    """Chat-route attach point: {"eligible", "language"} — code omitted, never raises."""
    try:
        m = mark_runnable(text)
        return {"eligible": bool(m.get("eligible")), "language": m.get("language")}
    except Exception:
        return {"eligible": False, "language": None}
