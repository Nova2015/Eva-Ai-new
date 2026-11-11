from datetime import datetime, timedelta


class SessionGuard:

    def __init__(self):

        self.sessions = {}

    def create_session(

        self,
        user_id,
        session_id,
        minutes=60
    ):

        self.sessions[session_id] = {

            "user_id": user_id,

            "created_at": str(datetime.utcnow()),

            "expires_at": datetime.utcnow() + timedelta(
                minutes=minutes
            ),

            "active": True
        }

        return {

            "success": True,

            "session_id": session_id
        }

    def validate_session(

        self,
        session_id
    ):

        session = self.sessions.get(
            session_id
        )

        if not session:

            return {

                "valid": False,

                "message": "Session not found"
            }

        if not session["active"]:

            return {

                "valid": False,

                "message": "Session inactive"
            }

        if datetime.utcnow() > session["expires_at"]:

            session["active"] = False

            return {

                "valid": False,

                "message": "Session expired"
            }

        return {

            "valid": True,

            "user_id": session["user_id"]
        }

    def end_session(

        self,
        session_id
    ):

        if session_id in self.sessions:

            self.sessions[session_id]["active"] = False

        return {

            "success": True,

            "message": "Session ended"
        }


if __name__ == "__main__":

    guard = SessionGuard()

    guard.create_session(

        "public_user",

        "session_001"
    )

    print(
        guard.validate_session("session_001")
    )