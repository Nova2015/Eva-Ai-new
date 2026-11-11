"""Slice 6 — testable handler behind POST /runtime/execute.

app.py's endpoint is a thin wrapper around handle_execute_request() so the
gating and payload behavior are unit-testable offline without importing the
8,000-line app.py.

Behavior:
- Gated by env EVA_ENABLE_RUNTIME_EXECUTION, DEFAULT FALSE. Disabled ->
  (403, detail) and Piston is NEVER contacted.
- Enabled -> (200, slice-4 runtime result verbatim). Slice 4 limits apply
  (code size cap rejects up front, timeout, output truncation).
- Never leaks env values or stack traces: any unexpected failure returns
  (200, UNKNOWN payload) with only the exception TYPE name.
"""

import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

try:  # package import
    from .execution_service import execute_code
    from .runtime_models import STATUS_UNKNOWN, make_result
    from .input_validation import appears_executable
except ImportError:  # flat import
    from execution_service import execute_code
    from runtime_models import STATUS_UNKNOWN, make_result
    from input_validation import appears_executable

# Reuse app.py's slowapi limiter when importable (same instance registered on
# app.state), but stay standalone-importable for offline unit tests: if the
# shared module isn't on the path, _limit is a no-op passthrough.
try:
    from rate_limit import limiter as _limiter
except Exception:  # pragma: no cover - only when src/ not on sys.path
    _limiter = None


def _limit(spec: str):
    def deco(fn):
        return _limiter.limit(spec)(fn) if _limiter is not None else fn
    return deco


def execution_enabled() -> bool:
    return os.getenv("EVA_ENABLE_RUNTIME_EXECUTION") == "true"


async def handle_execute_request(language: str, code: str, *, enabled=None):
    """Returns (http_status, payload)."""
    if enabled is None:
        enabled = execution_enabled()
    if not enabled:
        return 403, {"detail": "Runtime execution is disabled"}
    # Parse-first INVALID_INPUT gate for the manual code box — BEFORE Piston.
    # Rejects ONLY pure prose; broken code falls through to Piston for the real error.
    v = appears_executable(code or "", language or "")
    if not v["executable"]:
        return 200, {
            "status": "INVALID_INPUT",
            "language": language or "",
            "stdout": "", "stderr": "",
            "exit_code": None, "execution_ms": 0,
            "timed_out": False, "truncated": False,
            "runtime_source": "validator",
            "error": "Input does not appear to be executable code.",
            "reason": v["reason"],
        }
    try:
        return 200, await execute_code(language or "", code or "")
    except Exception as e:  # execute_code is no-raise by design; belt & braces.
        # Type name only — no message, no traceback, nothing internal.
        return 200, make_result(STATUS_UNKNOWN, (language or "?").lower(),
                                error=f"runtime engine failure: {type(e).__name__}")


# ── HTTP surface (Piston-backed) ──────────────────────────────────────────────
# The canonical execute endpoint + a minimal honest health check live on this
# router, which app.py mounts. Isolation is Piston's; there is NO local
# subprocess, NO streaming, NO cancellation of a server-side process.
router = APIRouter(tags=["Runtime"])


class RuntimeExecuteRequest(BaseModel):
    language: str = "python"
    code: str = ""


@router.post("/runtime/execute")
@_limit("10/minute")
async def runtime_execute(request: Request, req: RuntimeExecuteRequest):
    """Execute ONE code block on Piston, on explicit user click only.

    Gated by EVA_ENABLE_RUNTIME_EXECUTION (default OFF -> 403, no execution).
    Returns the slice-4 runtime model verbatim; runtime failures come back as
    status UNKNOWN with HTTP 200. Isolation is Piston's; the public instance
    sends code to a third-party service.
    """
    status_code, payload = await handle_execute_request(req.language, req.code)
    if status_code != 200:
        raise HTTPException(
            status_code=status_code,
            detail=payload.get("detail", "Runtime execution is disabled"),
        )
    return payload


@router.get("/runtime/health")
async def runtime_health():
    """Minimal, honest health: only what's true without a durable store.

    No avg_runtime_ms / success_rate / timeout_count — there is no persistence,
    so those would be fabricated or reset every restart.
    """
    return {"status": "ok", "runtime_enabled": execution_enabled(), "provider": "piston"}
