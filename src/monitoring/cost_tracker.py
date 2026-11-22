from monitoring.usage_tracker import usage_snapshot


def cost_snapshot():
    usage = usage_snapshot()
    estimated_cost = round((usage.get("tokens", 0) / 1_000_000) * 2.5, 4)
    return {
        "currency": "USD",
        "estimated_monthly_cost": estimated_cost,
        "budget": 25,
        "status": "within_budget" if estimated_cost <= 25 else "over_budget",
    }
