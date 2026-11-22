from eva_phase_common import read_state


def usage_snapshot():
    settings = read_state("monitoring_usage", {})
    return {
        "ai_requests": settings.get("ai_requests", 0),
        "tokens": settings.get("tokens", 0),
        "agent_runs": settings.get("agent_runs", 0),
        "file_uploads": settings.get("file_uploads", 0),
    }
