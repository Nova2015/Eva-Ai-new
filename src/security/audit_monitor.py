# src/security/audit_monitor.py

from datetime import datetime


class AuditMonitor:

    def __init__(self):

        self.audit_logs = []

    # ADD EVENT
    def log_event(

        self,
        user_id,
        action,
        status
    ):

        event = {

            "timestamp": str(datetime.utcnow()),

            "user_id": user_id,

            "action": action,

            "status": status
        }

        self.audit_logs.append(event)

        return {

            "success": True,

            "event": event
        }

    # GET LOGS
    def get_logs(self):

        return self.audit_logs

    # FILTER LOGS
    def get_user_logs(

        self,
        user_id
    ):

        return [

            log

            for log in self.audit_logs

            if log["user_id"] == user_id
        ]


# TEST
if __name__ == "__main__":

    audit = AuditMonitor()

    audit.log_event(

        "admin",

        "LOGIN",

        "SUCCESS"
    )

    audit.log_event(

        "admin",

        "PROMPT_REQUEST",

        "BLOCKED"
    )

    print(audit.get_logs())