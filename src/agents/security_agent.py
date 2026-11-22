AGENT_ID = "security"
DISPLAY_NAME = "Security Agent"
ICON = "🔒"

SYSTEM_INSTRUCTIONS = """
You are EVA Security Agent.
Analyze threats, PII exposure, suspicious prompts, malware indicators, audit events, and security dashboard findings.
Give practical risk levels and defensive remediation.
"""


SECURITY_TERMS = ("password", "secret", "token", "api_key", "credential", "malware", "exploit", "pii")


def run_security_task(instruction="", payload=None):
    payload = payload or {}
    logs = payload.get("logs") or instruction or ""
    matches = []
    lower_logs = logs.lower()
    for term in SECURITY_TERMS:
        if term in lower_logs:
            matches.append(term)

    risk = "medium" if matches else "low"
    if any(term in matches for term in ("password", "secret", "token", "credential", "api_key")):
        risk = "high"

    return {
        "status": "completed",
        "summary": "Security Agent scanned the provided task context and logs.",
        "risk": risk,
        "signals": matches,
        "recommendations": [
            "Rotate exposed credentials if any token or secret appears in logs.",
            "Move sensitive values into environment variables.",
            "Keep security dashboard monitoring enabled for suspicious requests.",
        ] if matches else [
            "No obvious high-risk security keywords were found in the provided context.",
            "Continue monitoring firewall events and deployment logs.",
        ],
    }
