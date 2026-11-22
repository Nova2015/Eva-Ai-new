import json
import os
import urllib.request


DEFAULT_HEALTH_URLS = [
    os.getenv("EVA_LOCAL_HEALTH_URL", "http://localhost:8002/health"),
    os.getenv("EVA_RENDER_HEALTH_URL", "https://eva-ai-1-9wfc.onrender.com/health"),
]


def _check_url(url, timeout=6):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read(1200).decode("utf-8", errors="ignore")
            return {
                "url": url,
                "ok": 200 <= response.status < 400,
                "status_code": response.status,
                "body": body,
            }
    except Exception as exc:
        return {
            "url": url,
            "ok": False,
            "status_code": 0,
            "error": str(exc),
        }


def run_deployment_task(instruction="", payload=None):
    payload = payload or {}
    urls = payload.get("urls") or DEFAULT_HEALTH_URLS
    checks = [_check_url(url) for url in urls if url]
    failures = [item for item in checks if not item["ok"]]
    suggestions = []
    if failures:
        suggestions.extend([
            "Check Render logs for import errors, invalid characters, missing modules, or port binding failures.",
            "Confirm the service binds to the port from the PORT environment variable.",
            "Verify required env vars such as GROQ_API_KEY, GITHUB_TOKEN, and Google credentials.",
        ])
    else:
        suggestions.append("All checked health endpoints responded successfully.")

    return {
        "status": "warning" if failures else "completed",
        "summary": f"Deployment Agent checked {len(checks)} endpoints for: {instruction or 'service health'}.",
        "checks": checks,
        "suggestions": suggestions,
    }


def status_label():
    local = _check_url(DEFAULT_HEALTH_URLS[0], timeout=2)
    return "ready" if local["ok"] else "warning"
