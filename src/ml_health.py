"""Small, bounded health probe for EVA's separately hosted ML/RAG service."""

from typing import Optional


async def probe_ml_health(base_url: Optional[str], timeout: float = 2.0) -> int:
    """Return the ML service's HTTP status, or 0 when it cannot be reached."""
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return 0

    try:
        import httpx

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.get(f"{base}/ml/health")
            return int(response.status_code)
    except Exception:
        # Health endpoints must not leak internal network errors or block startup.
        return 0
