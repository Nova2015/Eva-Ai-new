"""In-memory async ingestion job manager for EVA RAG uploads."""

import threading
import time
from typing import Any, Dict, Optional

QUEUED = "QUEUED"
PARSING = "PARSING"
CHUNKING = "CHUNKING"
VALIDATING = "VALIDATING"
EMBEDDING = "EMBEDDING"
INDEXING = "INDEXING"
COMPLETE = "COMPLETE"
FAILED = "FAILED"
CANCELLED = "CANCELLED"
TERMINAL = frozenset({COMPLETE, FAILED, CANCELLED})

_JOBS: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()


def create_job(job_id: str, filename: str = "") -> Dict[str, Any]:
    now = time.time()
    job = {
        "job_id": job_id,
        "filename": filename,
        "status": QUEUED,
        "stage": QUEUED,
        "progress": 0,
        "current_step": "Queued",
        "message": "Queued",
        "created_at": now,
        "updated_at": now,
        "chunk_count": 0,
        "error": None,
        "result": None,
        "cancel": False,
    }
    with _LOCK:
        _JOBS[job_id] = job
    return _public(job)


def update_job(
    job_id: str,
    *,
    status: Optional[str] = None,
    progress: Optional[int] = None,
    current_step: Optional[str] = None,
    message: Optional[str] = None,
    chunk_count: Optional[int] = None,
    error: Optional[str] = None,
    result: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        if status is not None:
            job["status"] = status
            job["stage"] = status
        if progress is not None:
            job["progress"] = max(job["progress"], min(100, int(progress)))
        if current_step is not None:
            job["current_step"] = current_step
            job["message"] = current_step
        if message is not None:
            job["message"] = message
        if chunk_count is not None:
            job["chunk_count"] = max(0, int(chunk_count))
        if error is not None:
            job["error"] = error
        if result is not None:
            job["result"] = result
        job["updated_at"] = time.time()
        return _public(job)


def get_job(job_id: str) -> Dict[str, Any]:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return {
                "job_id": job_id,
                "status": "NOT_FOUND",
                "stage": "NOT_FOUND",
                "progress": 0,
                "current_step": None,
                "message": "Job not found",
                "chunk_count": 0,
                "error": "job not found",
                "result": None,
            }
        return _public(job)


def cleanup_finished_jobs(max_age_seconds: int = 3600) -> int:
    now = time.time()
    with _LOCK:
        stale = [
            job_id
            for job_id, job in _JOBS.items()
            if job["status"] in TERMINAL and (now - job["updated_at"]) > max_age_seconds
        ]
        for job_id in stale:
            _JOBS.pop(job_id, None)
    return len(stale)


def _public(job: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "job_id": job["job_id"],
        "filename": job.get("filename", ""),
        "status": job["status"],
        "stage": job.get("stage", job["status"]),
        "progress": job["progress"],
        "current_step": job.get("current_step"),
        "message": job.get("message") or job.get("current_step"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "chunk_count": job.get("chunk_count", 0),
        "error": job.get("error"),
        "result": job.get("result"),
    }


def _reset_for_tests() -> None:
    with _LOCK:
        _JOBS.clear()
