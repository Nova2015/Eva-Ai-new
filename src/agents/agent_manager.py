from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from agents.agent_logs import append_agent_log
from agents.approval_gate import approval_required
from agents.task_planner import plan_task
from agents.tool_executor import allowed_tool_summary
from agents.workflow_engine import build_workflow
from eva_phase_common import new_id, now_iso, read_state, write_state


router = APIRouter(tags=["agents"])


def _agent_state():
    return read_state("agent_studio", {"agents": [], "runs": []})


def _save(state):
    state["updated_at"] = now_iso()
    write_state("agent_studio", state)
    return state


def _find_agent(agent_id: str):
    return next((item for item in _agent_state().get("agents", []) if item.get("id") == agent_id), None)


@router.post("/agents/create")
def create_agent(payload: Dict[str, Any]):
    state = _agent_state()
    agent = {
        "id": new_id("agent"),
        "name": payload.get("name", "New Agent"),
        "role": payload.get("role") or payload.get("persona") or "General assistant",
        "persona": payload.get("persona", ""),
        "allowed_tools": payload.get("allowed_tools", []),
        "knowledge_base": payload.get("knowledge_base", "Default"),
        "approval_required": bool(payload.get("approval_required", True)),
        "workflow": build_workflow({"id": "pending"}, payload.get("workflow_steps")),
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    agent["workflow"]["agent_id"] = agent["id"]
    state.setdefault("agents", []).insert(0, agent)
    _save(state)
    append_agent_log(agent["id"], "agent_created")
    return {"ok": True, "agent": agent}


@router.get("/agents")
def list_agents():
    return {"ok": True, "agents": _agent_state().get("agents", [])}


@router.post("/agents/run")
def run_agent(payload: Dict[str, Any]):
    agent_id = payload.get("agent_id")
    agent = _find_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    run = {
        "id": new_id("run"),
        "agent_id": agent_id,
        "status": "waiting_for_approval" if approval_required(agent, "run") else "running",
        "goal": payload.get("goal", ""),
        "plan": plan_task(payload.get("goal", "")),
        "tools": allowed_tool_summary(agent.get("allowed_tools")),
        "created_at": now_iso(),
    }
    state = _agent_state()
    state.setdefault("runs", []).insert(0, run)
    _save(state)
    append_agent_log(agent_id, "agent_run_created", {"run_id": run["id"], "status": run["status"]})
    return {"ok": True, "run": run}


@router.post("/agents/stop")
def stop_agent(payload: Dict[str, Any]):
    run_id = payload.get("run_id")
    state = _agent_state()
    for run in state.get("runs", []):
        if run.get("id") == run_id:
            run["status"] = "stopped"
            run["stopped_at"] = now_iso()
            _save(state)
            append_agent_log(run.get("agent_id", ""), "agent_run_stopped", {"run_id": run_id})
            return {"ok": True, "run": run}
    raise HTTPException(status_code=404, detail="Agent run not found")


@router.get("/agents/runs")
def agent_runs():
    return {"ok": True, "runs": _agent_state().get("runs", [])}


@router.get("/agents/workflow/{agent_id}")
def get_agent_workflow(agent_id: str):
    agent = _find_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"ok": True, "workflow": agent.get("workflow") or build_workflow(agent)}


@router.post("/agents/workflow/save")
def save_agent_workflow(payload: Dict[str, Any]):
    agent_id = payload.get("agent_id")
    state = _agent_state()
    for agent in state.get("agents", []):
        if agent.get("id") == agent_id:
            agent["workflow"] = build_workflow(agent, payload.get("steps"))
            agent["updated_at"] = now_iso()
            _save(state)
            append_agent_log(agent_id, "workflow_saved")
            return {"ok": True, "workflow": agent["workflow"]}
    raise HTTPException(status_code=404, detail="Agent not found")
