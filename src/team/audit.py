from eva_phase_common import now_iso, read_state, write_state


def record_audit(event: str, actor: str = "user_001", metadata=None):
    state = read_state("team_audit", {"events": []})
    item = {"event": event, "actor": actor, "metadata": metadata or {}, "created_at": now_iso()}
    state.setdefault("events", []).insert(0, item)
    state["events"] = state["events"][:200]
    write_state("team_audit", state)
    return item


def list_audit():
    return read_state("team_audit", {"events": []}).get("events", [])
