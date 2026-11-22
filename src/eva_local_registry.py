"""Phase 2 Step 14 — backend reader for the eva_local registry block.

The model registry (`model_config_versions`) is OWNED by eva-ml-service and
lives in Supabase. Step 7 gave it an optional `eva_local` block — the machines,
their base_url/model/quant/context, the runtime, and the health thresholds.
Until now only the ML service could read it, so the backend resolved EVA Server
Local from environment variables alone and the two services could silently
disagree about which local model was in use.

This module gives the backend READ-ONLY access to the same active version, so
both resolve from one source of truth. It writes nothing and owns no schema.

Fail-safe by construction. No credentials, no active version, an HTTP error, a
malformed body, a missing block — every path returns {} and the caller falls
back to the environment bootstrap, which is exactly today's behaviour. The
registry can never make local resolution worse than it is now.

Deliberately NOT imported by providers.py: that module documents that it
"carries no storage dependency and there is no import cycle". app.py injects
this reader at start-up via providers.set_eva_local_registry_reader().
"""

import logging
import os
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

__all__ = ["read", "fetch_active_eva_local", "invalidate", "TABLE"]

TABLE = "model_config_versions"
STATUS_ACTIVE = "ACTIVE"

# Mirrors the ML router's _REGISTRY_TTL_S: a deploy takes effect within the
# window with no restart, and a burst of requests costs one read, not one each.
_TTL_S = 15.0
_HTTP_TIMEOUT_S = 5.0

_lock = threading.Lock()
_cache: Dict[str, Any] = {"at": 0.0, "value": {}}


def _ttl() -> float:
    raw = (os.getenv("EVA_LOCAL_REGISTRY_TTL_S", "") or "").strip()
    if not raw:
        return _TTL_S
    try:
        return max(0.0, float(raw))
    except ValueError:
        return _TTL_S


def _supabase() -> Optional[tuple]:
    """Same credentials the provider shadow already uses. Read here rather than
    imported from app.py, which would be an import cycle."""
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("SUPABASE_KEY", "").strip()
    return (url, key) if url and key else None


def fetch_active_eva_local() -> Dict[str, Any]:
    """Uncached read of the ACTIVE version's eva_local block, or {}.

    Never raises: the caller is on the request path and a registry outage must
    degrade to the env bootstrap, not fail a chat.
    """
    creds = _supabase()
    if not creds:
        return {}
    url, key = creds
    try:
        import httpx
        with httpx.Client(timeout=_HTTP_TIMEOUT_S) as client:
            resp = client.get(
                f"{url}/rest/v1/{TABLE}",
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
                params={"select": "version,config",
                        "status": f"eq.{STATUS_ACTIVE}",
                        "order": "version.desc",
                        "limit": "1"},
            )
        if resp.status_code >= 400:
            # Status code only — a Supabase error body can carry the project URL.
            logger.warning("eva_local registry read: http_%s", resp.status_code)
            return {}
        rows = resp.json() or []
    except Exception as exc:
        logger.warning("eva_local registry read failed: %s", type(exc).__name__)
        return {}

    if not isinstance(rows, list) or not rows:
        return {}
    config = (rows[0] or {}).get("config")
    if not isinstance(config, dict):
        return {}
    block = config.get("eva_local")
    return block if isinstance(block, dict) else {}


def read() -> Dict[str, Any]:
    """Cached eva_local block, or {} when there is nothing to serve. This is the
    function injected into providers.py."""
    now = time.monotonic()
    with _lock:
        if now - _cache["at"] < _ttl():
            return _cache["value"]
    value = fetch_active_eva_local()
    with _lock:
        _cache["at"] = now
        _cache["value"] = value
    return value


def invalidate() -> None:
    """Drop the cache so the next read hits the registry (tests, admin action)."""
    with _lock:
        _cache["at"] = 0.0
        _cache["value"] = {}
