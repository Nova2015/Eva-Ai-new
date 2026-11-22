"""Low-level async Piston adapter (slice 4).

Reuses the exact request pattern already in the repo (src/feature_routes.py
POST /sandbox/run): same public base URL default, same /execute endpoint,
same payload keys, same version pins for the two supported languages.

Config (env — public vs self-hosted Piston is an env change, not a rewrite):
- PISTON_URL              default https://emkc.org/api/v2/piston
- PISTON_TIMEOUT_SECONDS  default 10 (hard client timeout AND run_timeout)

Guarantees:
- NO subprocess, no local execution anywhere in this package.
- run_on_piston() never raises into the request path: any exception,
  non-200, or unparseable body returns an UNKNOWN payload with error set.
- Compile stage: python3 and javascript on Piston have no compile stage,
  but the stage is handled anyway (present + non-zero -> RUNTIME_ERROR),
  so adding a compiled language later is a map entry, not a rewrite.
- Piston kill signals (run_timeout / memory) -> TIMEOUT.

Isolation is provided by Piston. With the default public instance, submitted
code is sent to a third-party service (emkc.org).
"""

import os
import time

import httpx

try:  # package import
    from .runtime_models import (
        STATUS_RUNTIME_ERROR,
        STATUS_SUCCESS,
        STATUS_TIMEOUT,
        STATUS_UNKNOWN,
        make_result,
    )
except ImportError:  # flat import
    from runtime_models import (
        STATUS_RUNTIME_ERROR,
        STATUS_SUCCESS,
        STATUS_TIMEOUT,
        STATUS_UNKNOWN,
        make_result,
    )

# Same default base URL as src/feature_routes.py PISTON_URL.
DEFAULT_PISTON_URL = "https://emkc.org/api/v2/piston"

# Version pins copied from src/feature_routes.py LANG_VERSIONS —
# slice 4 supports exactly these two languages.
LANG_VERSIONS = {
    "python": "3.10.0",
    "javascript": "18.15.0",
}

_EXT = {"python": "py", "javascript": "js"}

# Signals Piston reports when it kills a run (time/memory limits).
_KILL_SIGNALS = {"SIGKILL", "SIGTERM", "SIGXCPU"}


def piston_url() -> str:
    return os.getenv("PISTON_URL", DEFAULT_PISTON_URL).rstrip("/")


def piston_timeout_s() -> float:
    try:
        return float(os.getenv("PISTON_TIMEOUT_SECONDS", "10"))
    except (TypeError, ValueError):
        return 10.0


async def run_on_piston(language: str, code: str, stdin: str = "") -> dict:
    """POST to Piston /execute and map the response to the 4-state model."""
    version = LANG_VERSIONS.get(language)
    if version is None:
        return make_result(
            STATUS_UNKNOWN, language or "?",
            error=f"unsupported language '{language}' — supported: {', '.join(sorted(LANG_VERSIONS))}",
        )

    timeout_s = piston_timeout_s()
    payload = {
        "language": language,
        "version": version,
        "files": [{"name": f"main.{_EXT[language]}", "content": code or ""}],
        "stdin": stdin or "",
        "args": [],
        "compile_timeout": 10000,
        "run_timeout": int(timeout_s * 1000),
    }

    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(f"{piston_url()}/execute", json=payload)
    except Exception as e:  # unreachable / DNS / TLS / client-side timeout
        return make_result(STATUS_UNKNOWN, language,
                           error=f"piston unreachable: {type(e).__name__}: {e}")
    ms = int((time.perf_counter() - t0) * 1000)

    if resp.status_code != 200:
        return make_result(STATUS_UNKNOWN, language, error=f"piston http {resp.status_code}")

    try:
        data = resp.json()
    except Exception as e:
        return make_result(STATUS_UNKNOWN, language, error=f"piston bad json: {e}")

    run = data.get("run") or {}
    comp = data.get("compile") or None

    # Compile-stage failure (not applicable to python3/javascript, handled anyway).
    if isinstance(comp, dict) and comp.get("code") not in (0, None):
        return make_result(
            STATUS_RUNTIME_ERROR, language,
            stdout=comp.get("stdout", ""), stderr=comp.get("stderr", ""),
            exit_code=comp.get("code"), execution_ms=ms,
        )

    stdout = run.get("stdout", "")
    stderr = run.get("stderr", "")
    exit_code = run.get("code")
    signal = run.get("signal")

    if signal in _KILL_SIGNALS:
        return make_result(STATUS_TIMEOUT, language, stdout=stdout, stderr=stderr,
                           exit_code=exit_code, execution_ms=ms, timed_out=True)

    if exit_code == 0 and not (stderr or "").strip():
        return make_result(STATUS_SUCCESS, language, stdout=stdout, stderr=stderr,
                           exit_code=0, execution_ms=ms)

    # Ran and failed: non-zero exit OR stderr output from the code.
    return make_result(STATUS_RUNTIME_ERROR, language, stdout=stdout, stderr=stderr,
                       exit_code=exit_code, execution_ms=ms)
