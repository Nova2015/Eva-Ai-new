from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


ROOT_DIR = Path(__file__).resolve().parent
DATA_FILE = ROOT_DIR / "learning_progress.json"
LOCK = Lock()


def _read_all() -> dict:
    if not DATA_FILE.exists():
        return {}
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_all(data: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def default_progress() -> dict:
    return {
        "completed_lessons": [],
        "completed_tasks": [],
        "bookmarks": [],
        "notes": {},
        "book_notes": [],
        "quiz_scores": {},
        "roadmap_progress": {},
        "flashcards": [],
        "learning_history": [],
        "daily_plan": [
            "Read one lesson",
            "Complete one practice question",
            "Take one quiz",
            "Ask EVA to explain one weak area",
        ],
        "skill_scores": {
            "Python": 18,
            "Data Science": 12,
            "Machine Learning": 16,
            "AI Engineering": 20,
            "RAG": 22,
            "Prompt Engineering": 26,
            "Mechanical Design": 14,
        },
        "certificate_ready": False,
        "xp": 0,
        "badges": ["First login"],
        "streak": 1,
        "updated_at": None,
    }


def get_progress(user_id: str) -> dict:
    with LOCK:
        data = _read_all()
        progress = default_progress()
        progress.update(data.get(user_id, {}))
        return progress


def update_progress(user_id: str, patch: dict) -> dict:
    if not isinstance(patch, dict):
        raise ValueError("progress payload must be an object")

    allowed = {
        "completed_lessons",
        "completed_tasks",
        "bookmarks",
        "notes",
        "book_notes",
        "quiz_scores",
        "roadmap_progress",
        "flashcards",
        "learning_history",
        "daily_plan",
        "skill_scores",
        "certificate_ready",
        "xp",
        "badges",
        "streak",
    }
    clean_patch = {key: value for key, value in patch.items() if key in allowed}
    clean_patch["updated_at"] = datetime.now(timezone.utc).isoformat()

    with LOCK:
        data = _read_all()
        current = default_progress()
        current.update(data.get(user_id, {}))
        current.update(clean_patch)
        data[user_id] = current
        _write_all(data)
        return current
