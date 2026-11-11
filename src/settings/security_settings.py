from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from eva_phase_common import merge_dict, now_iso, read_state, scrub_secrets, write_state


router = APIRouter(tags=["settings"])

DEFAULT_SETTINGS = {
    "two_factor": False,
    "login_alerts": True,
    "api_key_visibility_protection": True,
    "active_sessions": [
        {"id": "session_local", "device": "Local browser", "location": "Current workspace", "last_active": now_iso(), "current": True}
    ],
    "activity_log": [
        {"event": "settings_viewed", "actor": "user_001", "created_at": now_iso(), "severity": "info"}
    ],
    "updated_at": now_iso(),
}


def _state():
    return merge_dict(DEFAULT_SETTINGS, read_state("security_settings", {}))


def _log(event: str, severity: str = "info"):
    settings = _state()
    settings.setdefault("activity_log", []).insert(0, {"event": event, "actor": "user_001", "created_at": now_iso(), "severity": severity})
    settings["activity_log"] = settings["activity_log"][:100]
    settings["updated_at"] = now_iso()
    write_state("security_settings", settings)
    return settings


@router.get("/settings/security")
def get_security_settings():
    return {"ok": True, "settings": scrub_secrets(_state())}


@router.post("/settings/security")
def save_security_settings(payload: Dict[str, Any]):
    settings = merge_dict(_state(), payload.get("settings", payload))
    settings["updated_at"] = now_iso()
    write_state("security_settings", settings)
    _log("security_settings_saved")
    return {"ok": True, "settings": scrub_secrets(_state())}


@router.post("/settings/security/change-password")
def change_password(payload: Dict[str, Any]):
    if not payload.get("current_password") or not payload.get("new_password"):
        raise HTTPException(status_code=400, detail="Current and new password are required")
    _log("password_change_requested", "warning")
    return {"ok": True, "message": "Password change validation placeholder completed. No password was logged."}


@router.post("/settings/security/logout-all")
def logout_all_devices():
    settings = _state()
    settings["active_sessions"] = [{"id": "session_local", "device": "Current browser", "last_active": now_iso(), "current": True}]
    settings["updated_at"] = now_iso()
    write_state("security_settings", settings)
    _log("logout_all_devices_requested", "warning")
    return {"ok": True, "settings": scrub_secrets(_state())}


@router.get("/settings/security/activity")
def security_activity():
    return {"ok": True, "activity": _state().get("activity_log", [])}


@router.post("/settings/security/export-data")
def export_security_data():
    _log("security_data_export_requested", "warning")
    return {"ok": True, "export": scrub_secrets(_state()), "generated_at": now_iso()}


@router.delete("/settings/security/account")
def delete_account(payload: Dict[str, Any] | None = None):
    if (payload or {}).get("confirmation") != "DELETE":
        raise HTTPException(status_code=400, detail="Account delete requires confirmation text DELETE")
    _log("account_delete_requested", "critical")
    return {"ok": True, "message": "Account deletion request recorded for admin review."}
