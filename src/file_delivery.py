"""Put a generated file somewhere the user can actually download it.

Render's free plan has no persistent disk, so a file written next to the
process is gone on the next deploy and often sooner. Cloudinary is already
configured for this project (CLOUDINARY_URL in render.yaml) and was, until
now, declared and never used.

Signed REST upload over httpx and hashlib rather than the cloudinary SDK: the
signature is a sorted parameter string plus the API secret, hashed once, and
the whole client is thirty lines. A dependency for that is not worth carrying.

THE SECRET IS USED, NEVER RETURNED. Everything here reports outcomes as fixed
codes; the credential appears in exactly one place, the signature digest, and
never in a return value, an exception path or a log line.
"""

import hashlib
import os
import re
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

__all__ = ["credentials", "signature", "upload_raw", "MAX_UPLOAD_BYTES"]

# A chat-generated spreadsheet that exceeds this is a bug upstream, not a file
# worth shipping. Cloudinary's own free-tier limit is far higher; this is about
# refusing to spend a slow upload on something nobody asked for.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def credentials() -> Optional[Tuple[str, str, str]]:
    """(cloud_name, api_key, api_secret) from CLOUDINARY_URL, or None.

    Format is cloudinary://<api_key>:<api_secret>@<cloud_name>. Parsed rather
    than pattern-matched so a malformed value fails here, cleanly, instead of
    producing a request that looks valid and is rejected remotely.
    """
    raw = os.getenv("CLOUDINARY_URL", "").strip()
    if not raw:
        return None
    try:
        parsed = urlparse(raw)
        if parsed.scheme != "cloudinary":
            return None
        cloud = (parsed.hostname or "").strip()
        key = (parsed.username or "").strip()
        secret = (parsed.password or "").strip()
        if not (cloud and key and secret):
            return None
        return cloud, key, secret
    except Exception:
        return None


def signature(params: Dict[str, Any], api_secret: str) -> str:
    """Cloudinary's signature: sorted key=value pairs, then the secret, SHA-1.

    `signature` and `file` are excluded by the API's own rules — including
    them produces a valid-looking request that is always rejected.
    """
    parts = [f"{k}={params[k]}" for k in sorted(params)
             if k not in ("file", "signature", "api_key") and params[k] != ""]
    return hashlib.sha1(("&".join(parts) + api_secret).encode()).hexdigest()


_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]+")


def public_id(stem: str, now: Optional[float] = None) -> str:
    """A collision-resistant, filesystem-safe id.

    Timestamped because two users asking for "sales" in the same minute must
    not overwrite each other's download — Cloudinary upserts on public_id.
    """
    cleaned = _SAFE_ID.sub("-", (stem or "file").strip()).strip("-") or "file"
    return f"eva/{cleaned[:48]}-{int(now or time.time())}"


async def upload_raw(data: bytes, filename: str,
                     timeout: float = 20.0) -> Tuple[Optional[str], str]:
    """Upload bytes as a downloadable file. Returns (url, code).

    `raw` rather than `auto`: an .xlsx classified as an image or video would be
    transformed, and a transformed spreadsheet is a corrupt one.
    """
    if not data:
        return None, "empty"
    if len(data) > MAX_UPLOAD_BYTES:
        return None, "too_large"

    creds = credentials()
    if not creds:
        return None, "not_configured"
    cloud, api_key, api_secret = creds

    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    params = {"timestamp": int(time.time()), "public_id": public_id(stem)}
    params["signature"] = signature(params, api_secret)
    params["api_key"] = api_key

    try:
        import httpx
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"https://api.cloudinary.com/v1_1/{cloud}/raw/upload",
                data={k: str(v) for k, v in params.items()},
                files={"file": (filename, data,
                                "application/vnd.openxmlformats-officedocument."
                                "spreadsheetml.sheet")},
            )
        if resp.status_code >= 400:
            return None, f"http_{resp.status_code}"
        url = (resp.json() or {}).get("secure_url")
        return (url, "ok") if url else (None, "no_url")
    except Exception as exc:
        # Class only. Cloudinary errors quote the request, which carries the
        # api_key and the signed parameters.
        return None, f"error_{type(exc).__name__}"
