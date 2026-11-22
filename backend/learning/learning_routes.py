from __future__ import annotations

import hashlib
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .course_manager import get_course, get_courses, get_paths
from .interview_prep import get_interview_prep
from .progress_tracker import get_progress, update_progress
from .quiz_manager import submit_quiz


router = APIRouter()


def _user_id(request: Request) -> str:
    explicit = request.headers.get("x-user-id")
    if explicit:
        return explicit[:120]
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        digest = hashlib.sha256(authorization.encode("utf-8")).hexdigest()[:32]
        return f"token:{digest}"
    return "local-user"


class QuizSubmitRequest(BaseModel):
    course_id: str = Field(..., max_length=80)
    lesson_id: str = Field(..., max_length=80)
    answers: dict[str, str]


class ProgressUpdateRequest(BaseModel):
    completed_lessons: Optional[list[str]] = None
    completed_tasks: Optional[list[str]] = None
    bookmarks: Optional[list[str]] = None
    notes: Optional[dict[str, str]] = None
    book_notes: Optional[list[dict]] = None
    quiz_scores: Optional[dict[str, int]] = None
    roadmap_progress: Optional[dict[str, int]] = None
    flashcards: Optional[list[dict]] = None
    learning_history: Optional[list[dict]] = None
    daily_plan: Optional[list[str]] = None
    skill_scores: Optional[dict[str, int]] = None
    certificate_ready: Optional[bool] = None
    xp: Optional[int] = None
    badges: Optional[list[str]] = None
    streak: Optional[int] = None


@router.get("/paths")
async def learning_paths():
    return {"paths": get_paths()}


@router.get("/courses")
async def learning_courses(path_id: Optional[str] = Query(default=None, max_length=80)):
    return {"courses": get_courses(path_id)}


@router.get("/course/{course_id}")
async def learning_course(course_id: str):
    course = get_course(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="course not found")
    return course


@router.post("/quiz/submit")
async def learning_quiz_submit(payload: QuizSubmitRequest, request: Request):
    try:
        result = submit_quiz(payload.course_id, payload.lesson_id, payload.answers)
        progress = get_progress(_user_id(request))
        quiz_scores = dict(progress.get("quiz_scores", {}))
        quiz_scores[f"{payload.course_id}:{payload.lesson_id}"] = result["score"]
        update_progress(_user_id(request), {"quiz_scores": quiz_scores})
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/progress")
async def learning_progress(request: Request):
    return get_progress(_user_id(request))


@router.post("/progress")
async def learning_progress_update(payload: ProgressUpdateRequest, request: Request):
    try:
        return update_progress(_user_id(request), payload.dict(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/interview-prep")
async def learning_interview_prep():
    return get_interview_prep()
