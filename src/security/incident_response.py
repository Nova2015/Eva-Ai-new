# src/security/incident_response.py

from datetime import datetime


class IncidentResponse:

    def __init__(self):

        self.incidents = []

    def create_incident(

        self,
        incident_type,
        severity,
        description,
        user_id="public_user"
    ):

        incident = {

            "id": len(self.incidents) + 1,

            "type": incident_type,

            "severity": severity,

            "description": description,

            "user_id": user_id,

            "status": "OPEN",

            "created_at": str(datetime.utcnow())
        }

        self.incidents.append(incident)

        return incident

    def close_incident(

        self,
        incident_id
    ):

        for incident in self.incidents:

            if incident["id"] == incident_id:

                incident["status"] = "CLOSED"

                incident["closed_at"] = str(datetime.utcnow())

                return {

                    "success": True,

                    "incident": incident
                }

        return {

            "success": False,

            "message": "Incident not found"
        }

    def get_incidents(self):

        return self.incidents


if __name__ == "__main__":

    ir = IncidentResponse()

    incident = ir.create_incident(

        "Prompt Injection",

        "HIGH",

        "User tried to bypass system prompt"
    )

    print(incident)

    print(ir.get_incidents())