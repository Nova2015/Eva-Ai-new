import os
import json
from datetime import datetime

LOG_FOLDER = "logs"

if not os.path.exists(LOG_FOLDER):

    os.makedirs(LOG_FOLDER)


def log_security_event(event_data):

    today = datetime.utcnow().strftime(
        "%Y-%m-%d"
    )

    log_file = f"{LOG_FOLDER}/{today}.log"

    log_entry = {

        "timestamp": str(datetime.utcnow()),

        "event": event_data
    }

    with open(log_file, "a") as file:

        file.write(
            json.dumps(log_entry) + "\n"
        )

    return {

        "logged": True,

        "file": log_file
    }


if __name__ == "__main__":

    sample_event = {

        "threat_level": "HIGH",

        "message": "Prompt injection detected",

        "ip": "127.0.0.1"
    }

    result = log_security_event(
        sample_event
    )

    print(result)