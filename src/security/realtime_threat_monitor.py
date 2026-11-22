"""
Realtime threat monitor — rate limiting, IP blocking, threat log.

Fix 0 rewrite. The previous implementation had three defects that made it
unsafe to put in the enforcement path:

1. check_rate_limit() was a monotonic LIFETIME counter, not a rate limit.
   There was no time window and no decay, so the 21st request since process
   start always tripped it — regardless of how much time had passed.

2. On tripping, it called block_ip(), which added the address to a set that
   was never cleared. The block was permanent for the life of the process.

3. Combined with the hardcoded ip_address = "127.0.0.1" in AIFirewall,
   every user shared one bucket. Enabling enforcement would therefore have
   denied every request from every user, forever, after 20 total messages.

Now: a sliding window, time-based blocks that expire, and no automatic
blocking from rate limiting alone. Also bounded memory — the old
request_counter and threat_logs both grew without limit.
"""

import time
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional

# Defaults. Callers should pass explicit values; these exist so the module is
# safe if called bare.
DEFAULT_LIMIT = 20
DEFAULT_WINDOW_SECONDS = 60
DEFAULT_BLOCK_SECONDS = 300

# Memory bounds. Without these a long-lived process accumulates one entry per
# distinct key forever.
MAX_THREAT_LOGS = 500
MAX_TRACKED_KEYS = 10_000


class RealtimeThreatMonitor:

    def __init__(
        self,
        limit: int = DEFAULT_LIMIT,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
        block_seconds: int = DEFAULT_BLOCK_SECONDS,
    ):
        self.limit = limit
        self.window_seconds = window_seconds
        self.block_seconds = block_seconds

        self.threat_logs: List[Dict[str, Any]] = []

        # key -> monotonic deadline after which the block lapses.
        # None means an explicit, indefinite block set by an operator.
        self._blocked: Dict[str, Optional[float]] = {}

        # key -> deque of monotonic timestamps inside the current window
        self._hits: Dict[str, deque] = {}

    # ── internals ────────────────────────────────────────────────────────

    @staticmethod
    def _now() -> float:
        # monotonic, not wall clock: immune to NTP steps and DST.
        return time.monotonic()

    def _prune_keys(self) -> None:
        """Drop tracking for keys with no activity in the current window."""
        if len(self._hits) <= MAX_TRACKED_KEYS:
            return
        cutoff = self._now() - self.window_seconds
        for key in [k for k, dq in self._hits.items() if not dq or dq[-1] <= cutoff]:
            self._hits.pop(key, None)

    # ── threat log ───────────────────────────────────────────────────────

    def log_threat(self, ip_address, attack_type, severity):
        event = {
            "ip": ip_address,
            "attack_type": attack_type,
            "severity": severity,
            "timestamp": str(datetime.utcnow()),
        }
        self.threat_logs.append(event)
        if len(self.threat_logs) > MAX_THREAT_LOGS:
            del self.threat_logs[:-MAX_THREAT_LOGS]
        return {"success": True, "event": event}

    # ── rate limiting ────────────────────────────────────────────────────

    def check_rate_limit(
        self,
        ip_address,
        limit: Optional[int] = None,
        window_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Sliding-window rate limit.

        Denies only the current request. It deliberately does NOT block the
        key: exceeding a rate limit is not evidence of an attack, and a
        self-inflicted permanent block is far more damaging than the traffic
        it prevents. Blocking is an explicit operator/threat decision made
        via block_ip().
        """
        key = str(ip_address or "unknown")
        limit = self.limit if limit is None else limit
        window = self.window_seconds if window_seconds is None else window_seconds

        now = self._now()
        cutoff = now - window

        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= cutoff:
            hits.popleft()

        if len(hits) >= limit:
            retry_after = max(0, int(hits[0] + window - now)) if hits else window
            return {
                "allowed": False,
                "message": "Rate limit exceeded",
                "requests": len(hits),
                "limit": limit,
                "window_seconds": window,
                "retry_after_seconds": retry_after,
            }

        hits.append(now)
        self._prune_keys()

        return {
            "allowed": True,
            "requests": len(hits),
            "limit": limit,
            "window_seconds": window,
        }

    # ── blocking ─────────────────────────────────────────────────────────

    def block_ip(self, ip_address, duration_seconds: Optional[int] = None):
        """
        Block a key. Expires after duration_seconds; pass duration_seconds=0
        for an indefinite block (operator action, survives until unblock_ip
        or process restart).
        """
        key = str(ip_address or "unknown")
        if duration_seconds is None:
            duration_seconds = self.block_seconds

        if duration_seconds <= 0:
            self._blocked[key] = None
            expires = None
        else:
            self._blocked[key] = self._now() + duration_seconds
            expires = duration_seconds

        return {
            "success": True,
            "blocked_ip": key,
            "expires_in_seconds": expires,
        }

    def unblock_ip(self, ip_address):
        """Escape hatch. A bad block must be reversible without a redeploy."""
        key = str(ip_address or "unknown")
        existed = self._blocked.pop(key, "__missing__") != "__missing__"
        self._hits.pop(key, None)
        return {"success": True, "unblocked": existed}

    def is_blocked(self, ip_address) -> bool:
        key = str(ip_address or "unknown")
        if key not in self._blocked:
            return False
        deadline = self._blocked[key]
        if deadline is None:
            return True
        if self._now() >= deadline:
            del self._blocked[key]
            return False
        return True

    # ── introspection ────────────────────────────────────────────────────

    def get_logs(self):
        return self.threat_logs

    def get_blocked_ips(self):
        return [key for key in list(self._blocked) if self.is_blocked(key)]

    def reset(self):
        """Clear all state. Intended for tests and operator recovery."""
        self._blocked.clear()
        self._hits.clear()
        self.threat_logs.clear()
        return {"success": True}

    # Backwards compatibility: the old attribute names were part of the
    # de-facto surface even though nothing outside this package read them.
    @property
    def blocked_ips(self):
        return set(self.get_blocked_ips())

    @property
    def request_counter(self):
        return {key: len(dq) for key, dq in self._hits.items()}
