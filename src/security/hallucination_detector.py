from datetime import datetime


SUSPICIOUS_WORDS = [

    "definitely guaranteed",
    "100 percent accurate",
    "no possibility of error",
    "always correct",
    "unlimited access",
    "hack successful",
    "security bypassed"
]


def detect_hallucination(ai_response):

    response = ai_response.lower()

    detected = []

    for word in SUSPICIOUS_WORDS:

        if word in response:

            detected.append(word)

    if detected:

        return {

            "hallucination_detected": True,

            "severity": "MEDIUM",

            "timestamp": str(datetime.utcnow()),

            "detected_patterns": detected,

            "message": "Potential AI hallucination detected"
        }

    return {

        "hallucination_detected": False,

        "severity": "SAFE",

        "timestamp": str(datetime.utcnow()),

        "detected_patterns": [],

        "message": "Response appears safe"
    }


# TEST
if __name__ == "__main__":

    sample = """

    This system is definitely guaranteed
    to bypass all security.
    """

    result = detect_hallucination(sample)

    print(result)