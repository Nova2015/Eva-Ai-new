from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from .run_models import RunCancelRequest, RunCreateRequest
from .run_service import cancel_run, create_run, get_metrics, get_run_events, get_run_with_events, get_runs, start_run
from .run_worker import execute_placeholder_run


router = APIRouter(prefix="/runs", tags=["Run Engine"])


@router.post("/create")
def create_run_route(req: RunCreateRequest, background_tasks: BackgroundTasks):
    run = create_run(
        user_id=req.user_id,
        organization_id=req.organization_id,
        source=req.source,
        run_type=req.run_type,
        title=req.title,
        instruction=req.instruction,
        payload=req.payload,
        priority=req.priority,
        metadata=req.metadata,
    )
    if req.auto_start:
        start_run(run["id"], "Run queued for execution")
        background_tasks.add_task(execute_placeholder_run, run["id"])
        run = get_run_with_events(run["id"])
    return {"ok": True, "run": run}


@router.get("")
def list_runs_route(
    user_id: str = "",
    organization_id: str = "",
    status: str = "",
    source: str = "",
    run_type: str = "",
    limit: int = Query(default=100, ge=1, le=500),
):
    runs = get_runs(
        user_id=user_id,
        organization_id=organization_id,
        status=status,
        source=source,
        run_type=run_type,
        limit=limit,
    )
    return {
        "ok": True,
        "count": len(runs),
        "runs": runs,
        "metrics": get_metrics(user_id=user_id),
    }


@router.get("/{run_id}")
def get_run_route(run_id: str):
    run = get_run_with_events(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"ok": True, "run": run}


@router.get("/{run_id}/events")
def get_run_events_route(run_id: str):
    run = get_run_with_events(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    events = get_run_events(run_id)
    return {"ok": True, "count": len(events), "events": events}


@router.post("/{run_id}/cancel")
def cancel_run_route(run_id: str, req: RunCancelRequest):
    run = cancel_run(run_id, reason=req.reason, user_id=req.user_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"ok": True, "run": get_run_with_events(run_id)}
