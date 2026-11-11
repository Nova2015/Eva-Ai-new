import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


ROOT_DIR = Path(__file__).resolve().parent
AUDIT_DIR = Path(os.getenv("EVA_RAG_AUDIT_DIR", "/tmp/eva_rag_audit"))


def now_iso() -> str:
    return datetime.utcnow().isoformat()


def safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value or "").strip("_")[:120] or "default"


def write_audit(chat_id: Optional[str], payload: Dict[str, Any]) -> Dict[str, Any]:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    audit_id = f"rag_{uuid.uuid4().hex[:12]}"
    resolved_chat_id = safe_name(chat_id or payload.get("chat_id") or audit_id)
    user_id = safe_name(payload.get("user_id", "anonymous"))
    workspace_id = safe_name(payload.get("workspace_id", "default"))
    record = {
        "ok": True,
        "audit_id": audit_id,
        "chat_id": resolved_chat_id,
        "created_at": now_iso(),
        **payload,
    }
    user_dir = AUDIT_DIR / user_id / workspace_id
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / f"{resolved_chat_id}.json").write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    (user_dir / "latest.json").write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return record


def read_audit(chat_id: str, user_id: str, workspace_id: str = "default") -> Dict[str, Any]:
    path = AUDIT_DIR / safe_name(user_id) / safe_name(workspace_id) / f"{safe_name(chat_id)}.json"
    if not path.exists():
        return {"ok": False, "error": "Audit not found"}
    return json.loads(path.read_text(encoding="utf-8"))


def read_latest_debug(user_id: str, workspace_id: str = "default") -> Dict[str, Any]:
    path = AUDIT_DIR / safe_name(user_id) / safe_name(workspace_id) / "latest.json"
    if not path.exists():
        return {"ok": True, "debug": None, "message": "No RAG debug trace yet."}
    record = json.loads(path.read_text(encoding="utf-8"))
    return {"ok": True, "debug": record.get("debug", {}), "audit": record}