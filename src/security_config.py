# src/security_config.py

SECURITY_CONFIG = {

    # FIREWALL
    "ENABLE_FIREWALL": True,

    # Whether a "not allowed" verdict actually blocks the request.
    # False  = evaluate and log only (shadow). Nothing is rejected.
    # True   = enforce.
    # Keep this False until the [FIREWALL-SHADOW] logs show an acceptable
    # false-positive rate. The PII patterns match any bare 10-digit number
    # and any IPv4-shaped string, which is very likely to fire on ordinary
    # messages in a coding assistant.
    "ENFORCE_FIREWALL": False,

    # Hard cap on how long the outbound response inspection may take, in
    # seconds. Past this, the answer is returned uninspected (fail-open).
    "OUTBOUND_INSPECT_TIMEOUT_SECONDS": 2.0,

    # PII
    "ENABLE_PII_DETECTION": True,

    # HALLUCINATION
    "ENABLE_HALLUCINATION_DETECTION": True,

    # VECTOR DB
    "ENABLE_VECTOR_GUARD": True,

    # RAG
    "ENABLE_RAG_POLICY": True,

    # MODEL SECURITY
    "ENABLE_MODEL_SECURITY": True,

    # BEDROCK
    "ENABLE_BEDROCK_GUARD": True,

    # IAM
    "ENABLE_IAM_GUARD": True,

    # RATE LIMIT
    "MAX_REQUESTS_PER_MINUTE": 20,

    # MEMORY
    "ENABLE_SECURE_MEMORY": True,

    # LOGGING
    "ENABLE_SECURITY_LOGS": True,

    # AGENT SECURITY
    "ENABLE_AGENT_ISOLATION": True,

    # THREAT LEVELS
    "BLOCK_LEVELS": [

        "HIGH",
        "CRITICAL"
    ]
}