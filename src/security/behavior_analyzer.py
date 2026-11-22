# src/security/behavior_analyzer.py

from datetime import datetime


class BehaviorAnalyzer:

    def __init__(self):

        self.user_behavior = {}

    # TRACK USER ACTIVITY
    def track_activity(

        self,
        user_id,
        action
    ):

        if user_id not in self.user_behavior:

            self.user_behavior[user_id] = []

        self.user_behavior[user_id].append({

            "action": action,

            "timestamp": str(datetime.utcnow())
        })

        return {

            "success": True,

            "message": "Behavior tracked"
        }

    # ANALYZE BEHAVIOR
    def analyze_behavior(

        self,
        user_id
    ):

        actions = self.user_behavior.get(
            user_id,
            []
        )

        suspicious_actions = [

            "multiple_failed_logins",
            "prompt_injection_attempt",
            "vector_dump_attempt",
            "token_bypass_attempt"
        ]

        detected = []

        for activity in actions:

            if activity["action"] in suspicious_actions:

                detected.append(
                    activity["action"]
                )

        if detected:

            return {

                "safe": False,

                "severity": "HIGH",

                "detected": detected,

                "message": "Suspicious behavior detected"
            }

        return {

            "safe": True,

            "message": "Behavior normal"
        }


if __name__ == "__main__":

    analyzer = BehaviorAnalyzer()

    analyzer.track_activity(

        "admin",

        "prompt_injection_attempt"
    )

    result = analyzer.analyze_behavior(
        "admin"
    )

    print(result)