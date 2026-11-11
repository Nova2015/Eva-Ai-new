def plan_task(goal: str):
    goal = (goal or "Run agent task").strip()
    return [
        {"step": "Understand objective", "detail": goal},
        {"step": "Select approved tools", "detail": "Use only tools enabled for this agent."},
        {"step": "Run workflow", "detail": "Pause for approval before dangerous actions."},
    ]
