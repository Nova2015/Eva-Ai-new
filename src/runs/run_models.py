from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


RUN_STATUSES = ("queued", "running", "completed", "failed", "cancelled")


class RunCreateRequest(BaseModel):
    user_id: str = "user_001"
    organization_id: str = "default-org"
    source: str = "manual"
    run_type: str
    title: str
    instruction: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)
    priority: int = 3
    metadata: Dict[str, Any] = Field(default_factory=dict)
    auto_start: bool = True


class RunCancelRequest(BaseModel):
    user_id: str = "user_001"
    reason: str = "Cancelled by user"


class RunEventCreate(BaseModel):
    event_type: str = "event"
    status: str = "running"
    message: str
    data: Dict[str, Any] = Field(default_factory=dict)


class RunListFilters(BaseModel):
    user_id: str = ""
    organization_id: str = ""
    status: str = ""
    source: str = ""
    run_type: str = ""
    limit: int = 100
