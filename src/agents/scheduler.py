from . import task_manager


DEFAULT_SCHEDULES = [
    {
        "name": "Backend health check",
        "agent_type": "deployment",
        "cron_label": "Every hour",
        "instruction": "Check backend health and report deployment failures.",
    },
    {
        "name": "Repository review",
        "agent_type": "repo",
        "cron_label": "Every day",
        "instruction": "Review the GitHub repository for bugs and patch opportunities.",
    },
    {
        "name": "Project status report",
        "agent_type": "report",
        "cron_label": "Every week",
        "instruction": "Generate a project report with bugs, security, deployment, database, memory, and model usage.",
    },
    {
        "name": "Memory database cleanup",
        "agent_type": "memory",
        "cron_label": "Every month",
        "instruction": "Organize memories, merge duplicates, and create project summaries.",
    },
]


def ensure_default_schedules(user_id="user_001"):
    current = task_manager.list_schedules(user_id)
    if current:
        return current
    for item in DEFAULT_SCHEDULES:
        task_manager.create_schedule(user_id=user_id, enabled=True, **item)
    return task_manager.list_schedules(user_id)


def create_agent_schedule(user_id, name, agent_type, cron_label, instruction, enabled=True):
    return task_manager.create_schedule(
        user_id=user_id,
        name=name,
        agent_type=agent_type,
        cron_label=cron_label,
        instruction=instruction,
        enabled=enabled,
    )
