# src/security/bedrock_guard.py

from datetime import datetime


ALLOWED_BEDROCK_MODELS = [

    "anthropic.claude-v2",
    "anthropic.claude-3-sonnet",
    "meta.llama3-70b",
    "mistral.mistral-large"
]


BLOCKED_PROMPTS = [

    "jailbreak",
    "bypass",
    "reveal system prompt",
    "disable security"
]


def validate_bedrock_request(

    model_id,
    prompt
):

    # MODEL VALIDATION
    if model_id not in ALLOWED_BEDROCK_MODELS:

        return {

            "allowed": False,

            "severity": "HIGH",

            "timestamp": str(datetime.utcnow()),

            "message": "Unauthorized Bedrock model"
        }

    # PROMPT VALIDATION
    detected = []

    lower_prompt = prompt.lower()

    for attack in BLOCKED_PROMPTS:

        if attack in lower_prompt:

            detected.append(attack)

    if detected:

        return {

            "allowed": False,

            "severity": "CRITICAL",

            "timestamp": str(datetime.utcnow()),

            "detected_patterns": detected,

            "message": "Malicious Bedrock prompt detected"
        }

    return {

        "allowed": True,

        "severity": "SAFE",

        "timestamp": str(datetime.utcnow()),

        "message": "Bedrock request approved"
    }


# TEST
if __name__ == "__main__":

    result = validate_bedrock_request(

        "anthropic.claude-v2",

        "Explain cloud security"
    )

    print(result)