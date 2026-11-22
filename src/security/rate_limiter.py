from collections import defaultdict
from datetime import datetime, timedelta


class RateLimiter:

    def __init__(

        self,

        max_requests=10,

        window_seconds=60
    ):

        self.max_requests = max_requests

        self.window_seconds = window_seconds

        self.requests = defaultdict(list)

    # ─────────────────────────────────────
    # CLEAN OLD REQUESTS
    # ─────────────────────────────────────

    def cleanup(

        self,

        user_id
    ):

        now = datetime.utcnow()

        valid_time = now - timedelta(

            seconds=self.window_seconds
        )

        self.requests[user_id] = [

            req_time

            for req_time in self.requests[user_id]

            if req_time > valid_time
        ]

    # ─────────────────────────────────────
    # CHECK LIMIT
    # ─────────────────────────────────────

    def is_allowed(

        self,

        user_id
    ):

        self.cleanup(user_id)

        current_count = len(
            self.requests[user_id]
        )

        if current_count >= self.max_requests:

            return {

                "allowed": False,

                "message": "Rate limit exceeded",

                "requests": current_count,

                "limit": self.max_requests
            }

        self.requests[user_id].append(
            datetime.utcnow()
        )

        return {

            "allowed": True,

            "requests": current_count + 1,

            "limit": self.max_requests
        }


# ─────────────────────────────────────────
# TEST
# ─────────────────────────────────────────

if __name__ == "__main__":

    limiter = RateLimiter(

        max_requests=3,

        window_seconds=30
    )

    user = "admin"

    for i in range(5):

        result = limiter.is_allowed(user)

        print(f"Request {i+1}:", result)