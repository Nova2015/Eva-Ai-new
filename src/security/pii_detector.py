import re
from datetime import datetime


PII_PATTERNS = {

    "EMAIL": r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",

    "PHONE": r"\b\d{10}\b",

    "CREDIT_CARD": r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b",

    "AADHAAR": r"\b\d{4}\s?\d{4}\s?\d{4}\b",

    "IP_ADDRESS": r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b",

    "API_KEY": r"(?i)(api[_-]?key\s*[:=]\s*[A-Za-z0-9-_]+)",

    "AWS_KEY": r"AKIA[0-9A-Z]{16}"
}


def detect_pii(text):

    detected = []

    for pii_type, pattern in PII_PATTERNS.items():

        matches = re.findall(pattern, text)

        if matches:

            detected.append({

                "type": pii_type,

                "matches": matches
            })

    if detected:

        return {

            "pii_detected": True,

            "severity": "HIGH",

            "timestamp": str(datetime.utcnow()),

            "detected_items": detected,

            "message": "Sensitive PII detected"
        }

    return {

        "pii_detected": False,

        "severity": "SAFE",

        "timestamp": str(datetime.utcnow()),

        "detected_items": [],

        "message": "No PII detected"
    }


# ─────────────────────────────────────────
# TEST
# ─────────────────────────────────────────

if __name__ == "__main__":

    sample_text = '''

    Email: admin@gmail.com

    Phone: 9876543210

    Card: 4111 1111 1111 1111

    AWS: AKIAIOSFODNN7EXAMPLE
    '''

    result = detect_pii(sample_text)

    print(result)