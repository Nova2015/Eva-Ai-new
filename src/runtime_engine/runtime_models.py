"""Standard 4-state runtime result model (slice 4). NOT a boolean.

Status semantics -- the distinction is the whole point:
- SUCCESS        code ran, exit 0, clean stderr.
- RUNTIME_ERROR  code RAN and failed: non-zero exit, stderr from the code,
                 or a compile-stage failure. A statement about the code.
- TIMEOUT        Piston killed the run (signal / run_timeout exceeded).
- UNKNOWN        the code NEVER ran: Piston unreachable, non-200, bad JSON,
                 unsupported language, oversized input. A statement about the
                 provider/inputs -- NEVER to be reported as a code failure.
                 "Couldn't run it" and "it ran and failed" are different
                 states; merging them is a user-facing lie.

error is set ONLY for UNKNOWN. execution_ms is wall time of the provider
call (None when the code never ran). Output truncation per runtime_limits.
"""

try:  # package import
    from .runtime_limits import truncate_output
except ImportError:  # flat import
    from runtime_limits import truncate_output

STATUS_SUCCESS = "SUCCESS"
STATUS_RUNTIME_ERROR = "RUNTIME_ERROR"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_UNKNOWN = "UNKNOWN"

RUNTIME_SOURCE = "piston"


def make_result(
    status: str,
    language: str,
    stdout: str = "",
    stderr: str = "",
    exit_code=None,
    execution_ms=None,
    timed_out: bool = False,
    error=None,
) -> dict:
    stdout, t_out = truncate_output(stdout)
    stderr, t_err = truncate_output(stderr)
    return {
        "status": status,
        "language": language,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code if isinstance(exit_code, int) else None,
        "execution_ms": execution_ms if isinstance(execution_ms, int) else None,
        "timed_out": bool(timed_out),
        "truncated": bool(t_out or t_err),
        "runtime_source": RUNTIME_SOURCE,
        "error": error if status == STATUS_UNKNOWN else None,
    }
