from typing import Any, Dict, Optional

from . import run_events
from .run_store import (
    add_event,
    create_run as store_create_run,
    dashboard_metrics,
    get_run,
    list_events,
    list_runs,
    now_iso,
    update_run,
)


def create_run(
    user_id: str,
    source: str,
    run_type: str,
    title: str,
    organization_id: str = "default-org",
    instruction: str = "",
    payload: Optional[Dict[str, Any]] = None,
    priority: int = 3,
    metadata: Optional[Dict[str, Any]] = None,
):
    run = store_create_run(
        user_id=user_id,
        organization_id=organization_id,
        source=source,
        run_type=run_type,
        title=title,
        instruction=instruction,
        payload=payload or {},
        priority=priority,
        metadata=metadata or {},
    )
    add_run_event(run["id"], run_events.RUN_CREATED, "queued", "Run created", {"source": source, "run_type": run_type})
    return run


def start_run(run_id: str, message: str = "Run started"):
    run = update_run(run_id, status="running", progress=5, started_at=now_iso())
    if run:
        add_run_event(run_id, run_events.RUN_STARTED, "running", message, {"progress": run.get("progress", 5)})
    return run


def add_run_event(run_id: str, event_type: str, status: str, message: str, data: Optional[Dict[str, Any]] = None):
    progress = None
    if data and "progress" in data:
        progress = data.get("progress")
    event = add_event(run_id, event_type, status, message, data or {})
    if progress is not None:
        update_run(run_id, status=status if status in ("queued", "running") else None, progress=int(progress))
    return event


def complete_run(run_id: str, result: Optional[Dict[str, Any]] = None, message: str = "Run completed"):
    run = update_run(run_id, status="completed", progress=100, result=result or {}, completed_at=now_iso())
    if run:
        add_run_event(run_id, run_events.RUN_COMPLETED, "completed", message, {"progress": 100, "result": result or {}})
    return run


def fail_run(run_id: str, error: str, result: Optional[Dict[str, Any]] = None, message: str = "Run failed"):
    run = update_run(run_id, status="failed", error=error, result=result or {}, completed_at=now_iso())
    if run:
        add_run_event(run_id, run_events.RUN_FAILED, "failed", message, {"error": str(error or "")[:1000], "result": result or {}})
    return run


def cancel_run(run_id: str, reason: str = "Cancelled by user", user_id: str = "user_001"):
    current = get_run(run_id)
    if not current:
        return None
    if current["status"] in ("completed", "failed", "cancelled"):
        return current
    run = update_run(run_id, status="cancelled", error=reason, cancelled_at=now_iso())
    add_run_event(run_id, run_events.RUN_CANCELLED, "cancelled", reason, {"user_id": user_id})
    return run


def get_run_with_events(run_id: str):
    run = get_run(run_id)
    if not run:
        return None
    run["events"] = list_events(run_id)
    return run


def get_runs(**filters):
    return list_runs(**filters)


def get_run_events(run_id: str):
    return list_events(run_id)


def get_metrics(user_id: str = ""):
    return dashboard_metrics(user_id=user_id)
