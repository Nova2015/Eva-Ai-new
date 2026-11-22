import json

from . import deployment_agent, memory_agent, repo_agent, report_agent, scheduler, security_agent, task_manager


MARKETPLACE = [
    {
        "id": "repo",
        "name": "Repo Agent",
        "category": "Development",
        "description": "Review repositories, find bugs, generate patch plans, and prepare PR workflows.",
        "status": "installed",
    },
    {
        "id": "deployment",
        "name": "Deployment Agent",
        "category": "Operations",
        "description": "Check Render health, API status, deployment failures, and fix suggestions.",
        "status": "installed",
    },
    {
        "id": "security",
        "name": "Security Agent",
        "category": "Security",
        "description": "Scan logs, detect risky signals, and generate alerts.",
        "status": "installed",
    },
    {
        "id": "memory",
        "name": "Memory Agent",
        "category": "Memory",
        "description": "Organize memories, find duplicates, and build project summaries.",
        "status": "installed",
    },
    {
        "id": "report",
        "name": "Report Agent",
        "category": "Reporting",
        "description": "Generate project status reports with bugs, security, deployment, database, memory, and model usage.",
        "status": "installed",
    },
]


def _json(data):
    return json.dumps(data, indent=2, ensure_ascii=False)


def get_dashboard(user_id="user_001"):
    scheduler.ensure_default_schedules(user_id)
    snapshot = task_manager.dashboard_snapshot(user_id)
    for agent in snapshot["agents"]:
        if agent["id"] == "deployment":
            agent["status"] = deployment_agent.status_label()
    return snapshot


def list_marketplace():
    return MARKETPLACE


def run_agent_task(user_id, agent_type, instruction, payload=None, title="", priority=3):
    payload = payload or {}
    task = task_manager.create_task(
        user_id=user_id,
        agent_type=agent_type,
        title=title,
        instruction=instruction,
        payload=_json(payload),
        priority=priority,
    )
    task_manager.add_history(task["id"], user_id, agent_type, "started", instruction)

    try:
        if agent_type == "repo":
            result = repo_agent.run_repo_task(instruction, payload)
        elif agent_type == "deployment":
            result = deployment_agent.run_deployment_task(instruction, payload)
        elif agent_type == "security":
            result = security_agent.run_security_task(instruction, payload)
        elif agent_type == "memory":
            result = memory_agent.run_memory_task(user_id, instruction, payload)
        elif agent_type == "report":
            result = report_agent.run_report_task(user_id, instruction, payload)
        else:
            result = {
                "status": "failed",
                "summary": f"Unknown agent type: {agent_type}",
                "available_agents": [agent["id"] for agent in MARKETPLACE],
            }

        status = "completed" if result.get("status") in ("completed", "warning") else "failed"
        task = task_manager.update_task(task["id"], status=status, result=_json(result))
        task_manager.add_history(task["id"], user_id, agent_type, status, result.get("summary", "Task finished"))
        return {"task": task, "result": result}
    except Exception as exc:
        result = {"status": "failed", "summary": str(exc)}
        task = task_manager.update_task(task["id"], status="failed", result=_json(result))
        task_manager.add_history(task["id"], user_id, agent_type, "failed", str(exc))
        return {"task": task, "result": result}


def list_tasks(user_id="user_001", status=""):
    return task_manager.list_tasks(user_id, status=status, limit=100)


def list_history(user_id="user_001"):
    return task_manager.list_history(user_id, limit=100)


def list_schedules(user_id="user_001"):
    return scheduler.ensure_default_schedules(user_id)


def create_schedule(user_id, name, agent_type, cron_label, instruction, enabled=True):
    return scheduler.create_agent_schedule(user_id, name, agent_type, cron_label, instruction, enabled)
