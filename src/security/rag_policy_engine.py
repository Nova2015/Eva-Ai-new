# src/security/rag_policy_engine.py

from datetime import datetime


ALLOWED_DOCUMENT_TYPES = [

    ".pdf",
    ".txt",
    ".docx"
]


BLOCKED_KEYWORDS = [

    "password",
    "secret",
    "token",
    "private key",
    "api key",
    "confidential"
]


def validate_rag_policy(

    filename,
    content
):

    # FILE TYPE CHECK
    allowed_file = False

    for ext in ALLOWED_DOCUMENT_TYPES:

        if filename.endswith(ext):

            allowed_file = True

            break

    if not allowed_file:

        return {

            "allowed": False,

            "severity": "HIGH",

            "timestamp": str(datetime.utcnow()),

            "message": "Blocked file type"
        }

    # CONTENT CHECK
    detected = []

    lower_content = content.lower()

    for keyword in BLOCKED_KEYWORDS:

        if keyword in lower_content:

            detected.append(keyword)

    if detected:

        return {

            "allowed": False,

            "severity": "CRITICAL",

            "timestamp": str(datetime.utcnow()),

            "detected_keywords": detected,

            "message": "Sensitive RAG content detected"
        }

    return {

        "allowed": True,

        "severity": "SAFE",

        "timestamp": str(datetime.utcnow()),

        "message": "RAG policy passed"
    }


# TEST
if __name__ == "__main__":

    result = validate_rag_policy(

        "company.pdf",

        "this contains api key"
    )

    print(result)