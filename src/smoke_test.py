"""
EVA /chat smoke test.

Sends a few fixed test questions to the running EVA backend and checks:
  1. The request succeeds (HTTP 200)
  2. The response has a non-empty "answer"
  3. The provider is one of the expected values (not an error/blocked path)

Exit code 0 = all tests passed (safe to keep the change).
Exit code 1 = something failed (roll back).

Usage:
    python smoke_test.py
    python smoke_test.py --url http://localhost:8000/chat
    python smoke_test.py --expect-provider eva_local
"""

import argparse
import sys
import time

import httpx

DEFAULT_URL = "http://localhost:8000/chat"

TEST_QUESTIONS = [
    "hello",
    "what is 2 plus 2",
    "what is data science",
]

# Providers considered a healthy answer. Add/remove as your setup changes.
ACCEPTABLE_PROVIDERS = {"eva_local", "rag", "gemini", "groq", "openai"}

# Providers/answers that mean something is broken even though HTTP was 200.
FAILURE_PROVIDERS = {"firewall", "unavailable", ""}


def run_one(client: httpx.Client, url: str, question: str, user_id: str) -> dict:
    started = time.perf_counter()
    payload = {
        "question": question,
        "voice_response": False,
        "memory_enabled": False,
        "mode": "automatic",
        "user_id": user_id,
    }
    try:
        resp = client.post(url, json=payload, timeout=60.0)
    except httpx.RequestError as exc:
        return {
            "question": question,
            "ok": False,
            "reason": f"request failed: {exc}",
            "elapsed_s": time.perf_counter() - started,
        }

    elapsed = time.perf_counter() - started

    if resp.status_code != 200:
        return {
            "question": question,
            "ok": False,
            "reason": f"HTTP {resp.status_code}",
            "elapsed_s": elapsed,
        }

    try:
        data = resp.json()
    except ValueError:
        return {
            "question": question,
            "ok": False,
            "reason": "response was not valid JSON",
            "elapsed_s": elapsed,
        }

    answer = (data.get("answer") or data.get("response") or "").strip()
    provider = str(data.get("provider") or "").strip()

    if not answer:
        return {
            "question": question,
            "ok": False,
            "reason": "empty answer",
            "provider": provider,
            "elapsed_s": elapsed,
        }

    if provider in FAILURE_PROVIDERS:
        return {
            "question": question,
            "ok": False,
            "reason": f"failure provider: {provider!r}",
            "provider": provider,
            "elapsed_s": elapsed,
        }

    if provider not in ACCEPTABLE_PROVIDERS:
        return {
            "question": question,
            "ok": False,
            "reason": f"unexpected provider: {provider!r}",
            "provider": provider,
            "elapsed_s": elapsed,
        }

    return {
        "question": question,
        "ok": True,
        "provider": provider,
        "answer_preview": answer[:80],
        "elapsed_s": elapsed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="EVA /chat smoke test")
    parser.add_argument("--url", default=DEFAULT_URL, help="Full /chat URL")
    parser.add_argument(
        "--expect-provider",
        default=None,
        help="If set, every test must use exactly this provider (e.g. eva_local). "
        "Use this after a change meant to force local-first routing.",
    )
    parser.add_argument(
        "--user-id", default="smoke-test-user", help="user_id sent in each request"
    )
    args = parser.parse_args()

    print(f"EVA smoke test -> {args.url}")
    print("-" * 60)

    results = []
    with httpx.Client() as client:
        for q in TEST_QUESTIONS:
            r = run_one(client, args.url, q, args.user_id)
            results.append(r)

            status = "PASS" if r["ok"] else "FAIL"
            provider = r.get("provider", "?")
            elapsed = r.get("elapsed_s", 0.0)
            print(f"[{status}] \"{q}\" -> provider={provider} time={elapsed:.2f}s")
            if not r["ok"]:
                print(f"        reason: {r['reason']}")
            elif "answer_preview" in r:
                print(f"        answer: {r['answer_preview']}...")

            if r["ok"] and args.expect_provider and provider != args.expect_provider:
                r["ok"] = False
                r["reason"] = (
                    f"provider mismatch: expected {args.expect_provider!r}, got {provider!r}"
                )
                print(f"        [EXPECT-PROVIDER FAIL] {r['reason']}")

    print("-" * 60)
    passed = sum(1 for r in results if r["ok"])
    total = len(results)
    print(f"Result: {passed}/{total} passed")

    if passed < total:
        print("SMOKE TEST FAILED - do not keep this change without investigating.")
        return 1

    print("SMOKE TEST PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
