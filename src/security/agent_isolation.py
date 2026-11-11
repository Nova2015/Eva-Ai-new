from datetime import datetime


class AgentIsolation:

    def __init__(self):

        self.agent_sessions = {}

    # CREATE SESSION
    def create_session(

        self,
        agent_id,
        user_id
    ):

        session = {

            "agent_id": agent_id,

            "user_id": user_id,

            "created_at": str(datetime.utcnow()),

            "status": "ACTIVE"
        }

        self.agent_sessions[agent_id] = session

        return {

            "success": True,

            "session": session
        }

    # VALIDATE ACCESS
    def validate_access(

        self,
        agent_id,
        user_id
    ):

        session = self.agent_sessions.get(
            agent_id
        )

        if not session:

            return {

                "allowed": False,

                "message": "Agent session not found"
            }

        if session["user_id"] != user_id:

            return {

                "allowed": False,

                "message": "Unauthorized agent access"
            }

        return {

            "allowed": True,

            "message": "Agent access approved"
        }

    # CLOSE SESSION
    def close_session(

        self,
        agent_id
    ):

        if agent_id in self.agent_sessions:

            self.agent_sessions[agent_id][
                "status"
            ] = "CLOSED"

        return {

            "success": True,

            "message": "Session closed"
        }


# TEST
if __name__ == "__main__":

    isolation = AgentIsolation()

    isolation.create_session(

        "agent_001",

        "admin"
    )

    result = isolation.validate_access(

        "agent_001",

        "admin"
    )

    print(result)