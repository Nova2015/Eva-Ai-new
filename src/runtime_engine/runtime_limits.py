"""Input/output limits for the runtime engine (slice 4).

- Code size: oversized code is REJECTED up front (status UNKNOWN with error
  "code exceeds max size") before any HTTP call. Code is never truncated and
  then run — running half a program would produce a lying verdict.
  Default cap 10,000 chars — same cap src/feature_routes.py /sandbox/run uses.
- Output size: stdout/stderr are truncated past ~10KB each with
  truncated=True. Piston already caps execution server-side; this caps our
  payload (and keeps logs sane).
Both env-configurable: RUNTIME_MAX_CODE_SIZE, RUNTIME_MAX_OUTPUT.
"""

import os

DEFAULT_MAX_CODE_SIZE = 10_000   # chars, matches feature_routes.py sandbox cap
DEFAULT_MAX_OUTPUT = 10_000      # chars per stream


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def max_code_chars() -> int:
    return _env_int("RUNTIME_MAX_CODE_SIZE", DEFAULT_MAX_CODE_SIZE)


def max_output_chars() -> int:
    return _env_int("RUNTIME_MAX_OUTPUT", DEFAULT_MAX_OUTPUT)


def code_too_large(code: str) -> bool:
    return len(code or "") > max_code_chars()


def truncate_output(text) -> tuple:
    """Return (text, was_truncated), enforcing the per-stream output cap."""
    text = text if isinstance(text, str) else ("" if text is None else str(text))
    limit = max_output_chars()
    if len(text) <= limit:
        return text, False
    return text[:limit] + "\n…[truncated]", True
