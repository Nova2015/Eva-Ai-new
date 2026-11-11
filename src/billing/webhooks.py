from eva_phase_common import now_iso, read_state, write_state


def record_webhook(payload):
    state = read_state("billing_webhooks", {"events": []})
    item = {"payload_type": payload.get("type", "unknown"), "created_at": now_iso()}
    state.setdefault("events", []).insert(0, item)
    state["events"] = state["events"][:100]
    write_state("billing_webhooks", state)
    return item
