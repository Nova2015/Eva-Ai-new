from eva_phase_common import now_iso, read_state, write_state


def append_agent_log(agent_id: str, event: str, metadata=None):
    state = read_state("agent_logs", {"logs": []})
    item = {"agent_id": agent_id, "event": event, "metadata": metadata or {}, "created_at": now_iso()}
    state.setdefault("logs", []).insert(0, item)
    state["logs"] = state["logs"][:200]
    write_state("agent_logs", state)
    return item
