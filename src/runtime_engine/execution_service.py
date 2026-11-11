"""Public entry point for runtime validation (slice 4 / wired in slice 4.5).

execute_code() is what app.py calls. It:
1. normalizes the language (py/js/node aliases),
2. enforces input limits (oversized code -> UNKNOWN, no HTTP call ever made),
3. delegates to the Piston adapter,
4. emits one structured log line per call.

The log line NEVER contains code contents, outputs, or environment values --
only language, status, duration, and the timed_out flag.

NEVER raises into a request path.
"""

import logging
import re

try:  # package import
    from .piston_adapter import LANG_VERSIONS, run_on_piston
    from .runtime_limits import code_too_large, max_code_chars
    from .runtime_models import STATUS_UNKNOWN, make_result
except ImportError:  # flat import
    from piston_adapter import LANG_VERSIONS, run_on_piston
    from runtime_limits import code_too_large, max_code_chars
    from runtime_models import STATUS_UNKNOWN, make_result

logger = logging.getLogger(__name__)

_ALIASES = {"py": "python", "python3": "python", "js": "javascript", "node": "javascript"}

# -- Slice 4.5: code-block extraction for chat wiring -------------------------
_FENCE_RE = re.compile(r"```(\w+)[ \t]*\n(.*?)```", re.S)
_RUNNABLE_TAGS = {"python", "py", "python3", "javascript", "js", "node"}


def extract_first_runnable_block(text: str):
    """(normalized_language, code) of the FIRST python/javascript fence in an
    assistant answer, or None. chart/mermaid/json/untagged fences are ignored.
    Only the first runnable block is executed per response -- deliberate cost
    and latency bound, not a limitation of the runtime engine."""
    for lang, body in _FENCE_RE.findall(text or ""):
        lc = lang.lower()
        if lc in _RUNNABLE_TAGS and body.strip():
            return _ALIASES.get(lc, lc), body.strip()
    return None


def _log(result: dict) -> None:
    try:
        logger.info(
            f"[RUNTIME] source=piston lang={result.get('language')} "
            f"status={result.get('status')} ms={result.get('execution_ms')} "
            f"timed_out={result.get('timed_out')}"
        )
    except Exception:
        pass  # observability must never break the call


async def execute_code(language: str, code: str, *, stdin: str = "") -> dict:
    """Run code on Piston and return the standard 4-state result dict."""
    lang = (language or "").lower().strip()
    lang = _ALIASES.get(lang, lang)

    if lang not in LANG_VERSIONS:
        result = make_result(
            STATUS_UNKNOWN, lang or "?",
            error=f"unsupported language '{language}' -- supported: {', '.join(sorted(LANG_VERSIONS))}",
        )
        _log(result)
        return result

    if code_too_large(code):
        # Rejected BEFORE any HTTP call. Never truncate code and run half a
        # program -- that would produce a verdict about code nobody wrote.
        result = make_result(
            STATUS_UNKNOWN, lang,
            error=f"code exceeds max size ({len(code or '')} > {max_code_chars()} chars)",
        )
        _log(result)
        return result

    try:
        result = await run_on_piston(lang, code, stdin=stdin)
    except Exception as e:  # adapter is no-raise by design; belt and braces
        result = make_result(STATUS_UNKNOWN, lang, error=f"{type(e).__name__}: {e}")

    _log(result)
    return result
