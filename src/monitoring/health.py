from fastapi import APIRouter

from eva_phase_common import now_iso
from monitoring.alerts import active_alerts
from monitoring.cost_tracker import cost_snapshot
from monitoring.logger import append_log, list_logs
from monitoring.metrics import runtime_metrics
from monitoring.usage_tracker import usage_snapshot


router = APIRouter(tags=["monitoring"])


@router.get("/monitoring/status")
def monitoring_status():
    metrics = runtime_metrics()
    costs = cost_snapshot()
    return {
        "ok": True,
        "status": "online",
        "generated_at": now_iso(),
        "metrics": metrics,
        "costs": costs,
        "alerts": active_alerts(metrics, costs),
    }


@router.get("/monitoring/metrics")
def monitoring_metrics():
    return {"ok": True, "metrics": runtime_metrics()}


@router.get("/monitoring/usage")
def monitoring_usage():
    return {"ok": True, "usage": usage_snapshot()}


@router.get("/monitoring/costs")
def monitoring_costs():
    return {"ok": True, "costs": cost_snapshot()}


@router.get("/monitoring/logs")
def monitoring_logs():
    append_log("monitoring_logs_viewed")
    return {"ok": True, "logs": list_logs()}
