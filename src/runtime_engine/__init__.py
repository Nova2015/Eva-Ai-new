"""Phase 19 slice 4 — Piston-backed runtime validation client.

Execution happens on a Piston instance (default: the public emkc.org API,
the same one src/feature_routes.py /sandbox/run already uses). There is NO
subprocess and NO local execution in this package. Isolation is provided by
Piston, and when PISTON_URL points at the public instance, submitted code is
sent to a third-party service.
"""

from .runtime_api import router, handle_execute_request, execution_enabled

__all__ = ["router", "handle_execute_request", "execution_enabled"]
