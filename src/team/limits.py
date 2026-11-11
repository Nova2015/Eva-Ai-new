def workspace_limits(plan: str = "Free"):
    limits = {
        "Free": {"members": 1, "messages": 500, "file_uploads": 25, "tokens": 100000},
        "Pro": {"members": 3, "messages": 5000, "file_uploads": 500, "tokens": 1000000},
        "Team": {"members": 15, "messages": 50000, "file_uploads": 2500, "tokens": 5000000},
        "Enterprise": {"members": 250, "messages": 500000, "file_uploads": 25000, "tokens": 25000000},
    }
    return limits.get(plan, limits["Free"])
