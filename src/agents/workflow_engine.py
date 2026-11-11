from eva_phase_common import now_iso


def build_workflow(agent: dict, steps=None):
    steps = steps or agent.get("workflow", {}).get("steps") or [
        {"id": "plan", "name": "Plan task", "type": "planner"},
        {"id": "execute", "name": "Execute approved tools", "type": "tool"},
        {"id": "report", "name": "Report outcome", "type": "summary"},
    ]
    return {"agent_id": agent.get("id"), "steps": steps, "updated_at": now_iso()}
