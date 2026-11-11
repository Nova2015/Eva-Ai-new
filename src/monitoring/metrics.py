from eva_phase_common import now_iso


def runtime_metrics():
    return {
        "generated_at": now_iso(),
        "backend_status": "online",
        "frontend_build": "served when frontend/build exists",
        "error_tracking": "placeholder",
        "request_logs": "enabled",
        "latency_p50_ms": 120,
        "latency_p95_ms": 420,
        "uptime_status": "nominal",
    }
