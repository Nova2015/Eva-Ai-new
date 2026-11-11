from typing import Any, Dict

from fastapi import APIRouter

from eva_phase_common import merge_dict, now_iso, read_state, write_state


router = APIRouter(tags=["settings"])

DEFAULT_SETTINGS = {
    "default_system_prompt": "You are EVA AI. Be helpful, concise, and source-aware when knowledge base context is used.",
    "chat_memory": True,
    "auto_title_chats": True,
    "streaming": True,
    "voice_reply": False,
    "file_upload": True,
    "code_copy_button": True,
    "markdown_rendering": True,
    "export_options": {"pdf": True, "docx": True, "txt": True, "json": True},
    "updated_at": now_iso(),
}


@router.get("/settings/chat")
def get_chat_settings():
    return {"ok": True, "settings": merge_dict(DEFAULT_SETTINGS, read_state("chat_settings", {}))}


@router.post("/settings/chat")
def save_chat_settings(payload: Dict[str, Any]):
    settings = merge_dict(DEFAULT_SETTINGS, read_state("chat_settings", {}))
    settings = merge_dict(settings, payload.get("settings", payload))
    settings["updated_at"] = now_iso()
    write_state("chat_settings", settings)
    return {"ok": True, "settings": settings}


@router.delete("/settings/chat/history")
def clear_chat_history():
    write_state("chat_history_clear_request", {"requested_at": now_iso(), "status": "queued"})
    return {"ok": True, "message": "Chat history clear request queued for the current workspace."}
