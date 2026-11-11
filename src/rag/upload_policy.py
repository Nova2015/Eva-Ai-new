"""Upload policy for the main EVA RAG routes.

This mirrors the hosted/local limits used by the hosted RAG service so the
main app advertises the same size and chunk ceilings consistently.
"""

import os


def is_local_mode() -> bool:
    return os.getenv("EVA_RUNTIME_MODE", "local").strip().lower() == "local"


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def get_upload_limit_mb() -> int:
    return _int_env("EVA_MAX_UPLOAD_MB", 200 if is_local_mode() else 20)


def get_max_chunks() -> int:
    return _int_env("EVA_MAX_CHUNKS", 50000 if is_local_mode() else 1200)


def validate_upload_size(size_bytes: int):
    limit_mb = get_upload_limit_mb()
    if size_bytes > limit_mb * 1024 * 1024:
        return {
            "error": "FILE_TOO_LARGE",
            "max_mb": limit_mb,
            "mode": "local" if is_local_mode() else "hosted",
            "detail": f"File exceeds the {limit_mb} MB limit for {'local' if is_local_mode() else 'hosted'} mode.",
        }
    return None


def validate_chunk_count(n_chunks: int):
    max_chunks = get_max_chunks()
    if n_chunks > max_chunks:
        return {
            "error": "TOO_MANY_CHUNKS",
            "max_chunks": max_chunks,
            "chunks": n_chunks,
            "mode": "local" if is_local_mode() else "hosted",
            "detail": f"Document produced {n_chunks} chunks, over the {max_chunks}-chunk limit for {'local' if is_local_mode() else 'hosted'} mode.",
        }
    return None


def limits_payload() -> dict:
    max_mb = get_upload_limit_mb()
    return {
        "mode": "local" if is_local_mode() else "hosted",
        "max_upload_mb": max_mb,
        "max_upload_label": f"{max_mb}MB",
        "max_chunks": get_max_chunks(),
        "async_jobs": True,
    }
