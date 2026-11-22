# src/security/model_router_security.py

from datetime import datetime


ALLOWED_MODELS = [

    "claude",
    "llama",
    "mistral",
    "gemini"
]


BLOCKED_MODELS = [

    "unknown_model",
    "unsafe_model"
]


def validate_model_access(

    model_name
):

    model = model_name.lower()

    if model in BLOCKED_MODELS:

        return {

            "allowed": False,

            "severity": "HIGH",

            "timestamp": str(datetime.utcnow()),

            "message": "Blocked AI model"
        }

    if model not in ALLOWED_MODELS:

        return {

            "allowed": False,

            "severity": "MEDIUM",

            "timestamp": str(datetime.utcnow()),

            "message": "Unauthorized model access"
        }

    return {

        "allowed": True,

        "severity": "SAFE",

        "timestamp": str(datetime.utcnow()),

        "message": "Model allowed"
    }


# TEST
if __name__ == "__main__":

    result = validate_model_access(
        "claude"
    )

    print(result)