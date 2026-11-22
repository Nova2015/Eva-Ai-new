PLAN_LIMITS = {
    "free": {"messages": 500, "file_uploads": 25, "tokens": 100000, "image_generation": 10, "video_generation": 0, "team_seats": 1},
    "pro": {"messages": 5000, "file_uploads": 500, "tokens": 1000000, "image_generation": 250, "video_generation": 25, "team_seats": 3},
    "team": {"messages": 50000, "file_uploads": 2500, "tokens": 5000000, "image_generation": 1000, "video_generation": 100, "team_seats": 15},
    "enterprise": {"messages": 500000, "file_uploads": 25000, "tokens": 25000000, "image_generation": 10000, "video_generation": 1000, "team_seats": 250},
}


def limits_for_plan(plan_id: str):
    return PLAN_LIMITS.get((plan_id or "free").lower(), PLAN_LIMITS["free"])
