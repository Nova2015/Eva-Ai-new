RUN_CREATED = "run_created"
RUN_STARTED = "run_started"
RUN_PROGRESS = "run_progress"
RUN_COMPLETED = "run_completed"
RUN_FAILED = "run_failed"
RUN_CANCELLED = "run_cancelled"
ARTIFACT_CREATED = "artifact_created"


def progress_message(step: str, progress: int):
    return {
        "event_type": RUN_PROGRESS,
        "status": "running",
        "message": step,
        "data": {"progress": max(0, min(int(progress or 0), 100))},
    }
