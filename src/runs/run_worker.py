from . import run_events
from .run_service import add_run_event, complete_run, fail_run, start_run


def execute_placeholder_run(run_id: str):
    """Default worker shim for manually created runs.

    Existing EVA workflows execute through their current endpoints and use the
    Run Engine for lifecycle tracking. This placeholder keeps /runs/create
    useful for manual operational runs without changing existing APIs.
    """
    try:
        start_run(run_id, "Manual run started")
        add_run_event(run_id, run_events.RUN_PROGRESS, "running", "No worker adapter configured for this run type", {"progress": 50})
        return complete_run(run_id, {"message": "Run recorded. Attach a worker adapter for automated execution."})
    except Exception as exc:
        return fail_run(run_id, str(exc))
