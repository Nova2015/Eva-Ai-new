from eva_phase_common import read_state, write_state, now_iso


def append_log(event: str, level: str = "info", metadata=None):
    state = read_state("monitoring_logs", {"logs": []})
    item = {"event": event, "level": level, "metadata": metadata or {}, "created_at": now_iso()}
    state.setdefault("logs", []).insert(0, item)
    state["logs"] = state["logs"][:200]
    write_state("monitoring_logs", state)
    return item


def list_logs():
    return read_state("monitoring_logs", {"logs": []}).get("logs", [])
