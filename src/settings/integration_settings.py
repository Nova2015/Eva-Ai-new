from copy import deepcopy
from typing import Any, Dict

from fastapi import APIRouter

from eva_phase_common import mask_secret, merge_dict, now_iso, read_state, scrub_secrets, validate_choice, write_state


router = APIRouter(tags=["settings"])

INTEGRATIONS = (
    "Google Drive",
    "Gmail",
    "Google Calendar",
    "GitHub",
    "Hugging Face",
    "Cloudinary",
    "Notion",
    "Slack",
    "Zapier/Webhooks",
)

DEFAULT_SETTINGS = {
    "integrations": {
        name: {
            "connected": False,
            "status": "not_connected",
            "api_key": "",
            "oauth_placeholder": "OAuth connection pending",
            "webhook_url": "",
            "webhook_secret": "",
        }
        for name in INTEGRATIONS
    },
    "webhook_endpoint": "/integrations/webhook/eva",
    "updated_at": now_iso(),
}


def _raw():
    return merge_dict(deepcopy(DEFAULT_SETTINGS), read_state("integration_settings", {}))


def _public(settings):
    return scrub_secrets(settings)


@router.get("/settings/integrations")
def get_integrations_settings():
    return {"ok": True, "settings": _public(_raw()), "integrations": list(INTEGRATIONS)}


@router.post("/settings/integrations")
def save_integrations_settings(payload: Dict[str, Any]):
    current = _raw()
    incoming = payload.get("settings", payload)
    for name, config in incoming.get("integrations", {}).items():
        validate_choice(name, INTEGRATIONS, "integration")
        old = current["integrations"][name]
        for secret_key in ("api_key", "webhook_secret"):
            value = str(config.get(secret_key, ""))
            if not value or "*" in value:
                config[secret_key] = old.get(secret_key, "")
    saved = merge_dict(current, incoming)
    saved["updated_at"] = now_iso()
    write_state("integration_settings", saved)
    return {"ok": True, "settings": _public(saved)}


@router.post("/settings/integrations/test")
def test_integration(payload: Dict[str, Any]):
    name = payload.get("integration")
    validate_choice(name, INTEGRATIONS, "integration")
    settings = _raw()
    item = settings["integrations"].get(name, {})
    success = bool(item.get("connected") or item.get("api_key") or item.get("webhook_url"))
    item["status"] = "connected" if success else "needs_configuration"
    settings["integrations"][name] = item
    settings["updated_at"] = now_iso()
    write_state("integration_settings", settings)
    return {"ok": True, "integration": name, "success": success, "status": item["status"]}


@router.post("/settings/integrations/disconnect")
def disconnect_integration(payload: Dict[str, Any]):
    name = payload.get("integration")
    validate_choice(name, INTEGRATIONS, "integration")
    settings = _raw()
    item = settings["integrations"][name]
    item.update({"connected": False, "status": "disconnected", "api_key": "", "webhook_secret": ""})
    settings["integrations"][name] = item
    settings["updated_at"] = now_iso()
    write_state("integration_settings", settings)
    return {"ok": True, "integration": name, "settings": _public(settings)}
