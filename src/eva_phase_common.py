import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from fastapi import HTTPException, UploadFile


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
PHASE_STATE_DIR = DATA_DIR / "phase11_25"
PHASE_UPLOAD_DIR = DATA_DIR / "domain_training"
PHASE_DB_PATH = Path(os.getenv("EVA_PHASE_DB", DATA_DIR / "eva_phase_11_25.db"))

PHASE_STATE_DIR.mkdir(parents=True, exist_ok=True)
PHASE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_SIZE = int(os.getenv("EVA_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
BLOCKED_EXTENSIONS = {
    ".bat",
    ".cmd",
    ".com",
    ".dll",
    ".exe",
    ".js",
    ".msi",
    ".ps1",
    ".scr",
    ".sh",
    ".vbs",
}
DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".txt", ".csv", ".json", ".jsonl"}
EVAL_EXTENSIONS = {".csv", ".json", ".jsonl"}


def now_iso() -> str:
    return datetime.utcnow().isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def state_path(name: str) -> Path:
    safe_name = "".join(ch for ch in name if ch.isalnum() or ch in ("_", "-")).strip("_")
    return PHASE_STATE_DIR / f"{safe_name}.json"


def read_state(name: str, default: Any) -> Any:
    path = state_path(name)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_state(name: str, value: Any) -> Any:
    path = state_path(name)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    return value


def merge_dict(base: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(base)
    for key, value in (incoming or {}).items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = merge_dict(result[key], value)
        else:
            result[key] = value
    return result


def mask_secret(value: Optional[str]) -> str:
    if not value:
        return ""
    if not isinstance(value, str):
        return value
    text = str(value)
    if "*" in text and len(text) <= 16:
        return text
    if len(text) <= 8:
        return f"{text[:2]}****{text[-2:]}"
    prefix = text[:3] if text.startswith(("sk-", "gsk", "hf_", "xox", "ghp")) else text[:2]
    return f"{prefix}****{text[-4:]}"


SECRET_KEYS = ("api_key", "secret", "token", "password", "webhook_secret", "bearer_token")


def scrub_secrets(value: Any) -> Any:
    if isinstance(value, list):
        return [scrub_secrets(item) for item in value]
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if isinstance(item, str) and any(secret_key in key.lower() for secret_key in SECRET_KEYS):
                cleaned[key] = mask_secret(item)
            else:
                cleaned[key] = scrub_secrets(item)
        return cleaned
    return value


def validate_choice(value: str, allowed: Iterable[str], field_name: str) -> str:
    allowed_set = {item for item in allowed}
    if value not in allowed_set:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}: {value}")
    return value


def scoped_payload(payload: Dict[str, Any], user_id: str = "user_001", workspace_id: str = "default-org") -> Dict[str, Any]:
    next_payload = dict(payload or {})
    next_payload.setdefault("user_id", user_id)
    next_payload.setdefault("workspace_id", workspace_id)
    next_payload.setdefault("updated_at", now_iso())
    return next_payload


def connect_phase_db() -> sqlite3.Connection:
    PHASE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(PHASE_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    return dict(row) if row else None


def rows_to_dicts(rows) -> list[Dict[str, Any]]:
    return [dict(row) for row in rows]


async def read_validated_upload(
    upload: UploadFile,
    allowed_extensions: Optional[set[str]] = None,
    max_size: int = MAX_UPLOAD_SIZE,
) -> tuple[bytes, str]:
    if upload is None:
        raise HTTPException(status_code=400, detail="File is required")
    suffix = Path(upload.filename or "").suffix.lower()
    if not suffix:
        raise HTTPException(status_code=400, detail="Uploaded file must have an extension")
    if suffix in BLOCKED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="This file type is blocked for safety")
    if allowed_extensions and suffix not in allowed_extensions:
        allowed = ", ".join(sorted(allowed_extensions))
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {allowed}")
    data = await upload.read()
    if len(data) > max_size:
        raise HTTPException(status_code=413, detail="File exceeds the configured upload limit")
    return data, suffix


def decode_text(data: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(encoding)
        except Exception:
            continue
    return ""
