#!/usr/bin/env python
"""
EVA deploy verifier.

Usage:
    python verify_deploy.py https://eva-ai-1-9wfc.onrender.com
    python verify_deploy.py https://eva-ai-1-9wfc.onrender.com --ml-url https://keshav1212-eva-ml-service.hf.space
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def join_url(base, path):
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def fetch_json(base_url, path, timeout=15):
    url = join_url(base_url, path)
    started = time.perf_counter()
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read().decode("utf-8", errors="replace")
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            try:
                data = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                data = {"raw": raw[:300]}
            return {
                "ok": res.status == 200,
                "status": res.status,
                "url": url,
                "response_time_ms": elapsed_ms,
                "data": data,
                "error": "",
            }
    except urllib.error.HTTPError as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        body = exc.read().decode("utf-8", errors="replace")[:300]
        return {
            "ok": False,
            "status": exc.code,
            "url": url,
            "response_time_ms": elapsed_ms,
            "data": {"raw": body},
            "error": str(exc),
        }
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        return {
            "ok": False,
            "status": None,
            "url": url,
            "response_time_ms": elapsed_ms,
            "data": {},
            "error": str(exc),
        }


def has_version(data):
    if not isinstance(data, dict):
        return False
    return bool(data.get("commit") or data.get("backend_commit") or data.get("frontend_version"))


def main():
    parser = argparse.ArgumentParser(description="Verify EVA deployment health and version endpoints.")
    parser.add_argument("base_url", help="Backend base URL, for example https://eva-ai-1-9wfc.onrender.com")
    parser.add_argument("--ml-url", default=None, help="Optional ML service base URL. Defaults to backend base URL.")
    parser.add_argument("--timeout", type=int, default=15)
    args = parser.parse_args()

    backend = args.base_url.rstrip("/")
    ml_base = (args.ml_url or backend).rstrip("/")
    checks = [
        ("backend /api/health", backend, "/api/health"),
        ("backend /api/health/full", backend, "/api/health/full"),
        ("ml /ml/health", ml_base, "/ml/health"),
        ("backend /api/version", backend, "/api/version"),
    ]

    results = []
    for name, base, path in checks:
        result = fetch_json(base, path, timeout=args.timeout)
        result["name"] = name
        results.append(result)

    full = next((item for item in results if item["name"] == "backend /api/health/full"), {})
    version = next((item for item in results if item["name"] == "backend /api/version"), {})

    failures = []
    for result in results:
        if not result["ok"]:
            failures.append(f"{result['name']} returned {result['status']} ({result['error'] or result['url']})")
    if full.get("ok"):
        data = full.get("data") or {}
        if data.get("backend_status") != 200:
            failures.append("/api/health/full backend_status is not 200")
        if "response_time_ms" not in data:
            failures.append("/api/health/full missing response_time_ms")
        if not data.get("backend_commit"):
            failures.append("/api/health/full missing backend_commit")
        if not data.get("frontend_version"):
            failures.append("/api/health/full missing frontend_version")
    if version.get("ok") and not has_version(version.get("data")):
        failures.append("/api/version missing commit/version fields")

    print("EVA deploy verification")
    print("=" * 24)
    for result in results:
        label = "PASS" if result["ok"] else "FAIL"
        print(f"{label} {result['name']} [{result['status']}] {result['response_time_ms']} ms")
        if result["error"]:
            print(f"     error: {result['error']}")
    print()

    if failures:
        print("FAILURES")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("All deploy checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
