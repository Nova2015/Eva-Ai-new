def approval_required(agent: dict, action: str = "run") -> bool:
    if agent.get("approval_required", True):
        return True
    return action in {"delete", "deploy", "external_write"}
