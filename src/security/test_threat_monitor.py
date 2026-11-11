"""
Standalone checks for RealtimeThreatMonitor (Fix 0).

No pytest, no deps. Run from the repo root:

    python src/security/test_threat_monitor.py

Exit code 0 means every check passed. These target the three defects that
made the old implementation unsafe to enforce with:

  * lifetime counter instead of a sliding window
  * permanent block on rate-limit trip
  * one shared bucket for all users
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from realtime_threat_monitor import RealtimeThreatMonitor  # noqa: E402


PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL  {name}  {detail}")


def test_window_allows_under_limit():
    m = RealtimeThreatMonitor(limit=5, window_seconds=60)
    results = [m.check_rate_limit("1.2.3.4")["allowed"] for _ in range(5)]
    check("5 requests under a limit of 5 are allowed", all(results), results)


def test_denies_at_limit():
    m = RealtimeThreatMonitor(limit=3, window_seconds=60)
    for _ in range(3):
        m.check_rate_limit("1.2.3.4")
    r = m.check_rate_limit("1.2.3.4")
    check("4th request over a limit of 3 is denied", r["allowed"] is False, r)
    check("denial reports retry_after_seconds", "retry_after_seconds" in r, r)


def test_denial_does_not_block():
    """The old code called block_ip() here, permanently."""
    m = RealtimeThreatMonitor(limit=2, window_seconds=60)
    for _ in range(5):
        m.check_rate_limit("1.2.3.4")
    check(
        "exceeding the rate limit does NOT block the key",
        m.is_blocked("1.2.3.4") is False,
        f"blocked={m.get_blocked_ips()}",
    )


def test_window_expires():
    """The old counter never decayed; the 21st request ever was fatal."""
    m = RealtimeThreatMonitor(limit=2, window_seconds=1)
    m.check_rate_limit("1.2.3.4")
    m.check_rate_limit("1.2.3.4")
    denied = m.check_rate_limit("1.2.3.4")["allowed"]
    time.sleep(1.1)
    recovered = m.check_rate_limit("1.2.3.4")["allowed"]
    check("denied while inside the window", denied is False)
    check("allowed again once the window passes", recovered is True)


def test_buckets_are_independent():
    """The regression that would have taken every user down at once."""
    m = RealtimeThreatMonitor(limit=2, window_seconds=60)
    for _ in range(5):
        m.check_rate_limit("10.0.0.1")
    other = m.check_rate_limit("10.0.0.2")
    check(
        "one key exhausting its limit does not affect another key",
        other["allowed"] is True,
        other,
    )


def test_block_expires():
    m = RealtimeThreatMonitor()
    m.block_ip("9.9.9.9", duration_seconds=1)
    during = m.is_blocked("9.9.9.9")
    time.sleep(1.1)
    after = m.is_blocked("9.9.9.9")
    check("timed block is active during its window", during is True)
    check("timed block lapses afterwards", after is False)


def test_indefinite_block_and_unblock():
    m = RealtimeThreatMonitor()
    m.block_ip("8.8.8.8", duration_seconds=0)
    check("duration 0 blocks indefinitely", m.is_blocked("8.8.8.8") is True)
    check("blocked key is listed", "8.8.8.8" in m.get_blocked_ips())
    m.unblock_ip("8.8.8.8")
    check("unblock_ip releases it", m.is_blocked("8.8.8.8") is False)


def test_unknown_key_not_blocked():
    m = RealtimeThreatMonitor()
    check("an unseen key is not blocked", m.is_blocked("nope") is False)
    check("None collapses to 'unknown' without raising",
          m.check_rate_limit(None)["allowed"] is True)


def test_threat_log_is_bounded():
    m = RealtimeThreatMonitor()
    for i in range(600):
        m.log_threat("1.1.1.1", f"attack-{i}", "LOW")
    check("threat log stays bounded", len(m.get_logs()) <= 500, len(m.get_logs()))


if __name__ == "__main__":
    print("RealtimeThreatMonitor — Fix 0 checks\n")
    for fn in [
        test_window_allows_under_limit,
        test_denies_at_limit,
        test_denial_does_not_block,
        test_window_expires,
        test_buckets_are_independent,
        test_block_expires,
        test_indefinite_block_and_unblock,
        test_unknown_key_not_blocked,
        test_threat_log_is_bounded,
    ]:
        print(f"\n{fn.__name__}")
        fn()

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    sys.exit(1 if FAILED else 0)
