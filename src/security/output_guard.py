import re
from datetime import datetime

SENSITIVE_PATTERNS = [

    r"aws_secret_access_key",
    r"private key",
    r"password",
    r"token",
    r"access key",
    r"database uri",
    r"mongodb://",
    r"postgres://",
    r"api_key",
    r"secret_key",
]

SEVERITY = {
    "SAFE": 0,
    "LOW": 2,
    "MEDIUM": 5,
    "HIGH": 10,
    "CRITICAL": 20
}


def validate_output(ai_response):

    response = ai_response.lower()

    detected_leaks = []

    for pattern in SENSITIVE_PATTERNS:

        if re.search(pattern, response):

            detected_leaks.append(pattern)

    if detected_leaks:

        return {
            "blocked": True,
            "severity": "CRITICAL",
            "risk_score": SEVERITY["CRITICAL"],
            "detected_patterns": detected_leaks,
            "timestamp": str(datetime.utcnow()),
            "safe_response": "Sensitive information blocked by AI Security Layer"
        }

    return {
        "blocked": False,
        "severity": "SAFE",
        "risk_score": SEVERITY["SAFE"],
        "detected_patterns": [],
        "timestamp": str(datetime.utcnow()),
        "safe_response": ai_response
    }


if __name__ == "__main__":

    test_response = '''
    AWS_SECRET_ACCESS_KEY=123456789
    '''

    result = validate_output(test_response)

    print(result)