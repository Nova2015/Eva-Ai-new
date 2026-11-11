from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from eva_phase_common import merge_dict, now_iso, read_state, validate_choice, write_state


router = APIRouter(tags=["settings"])

THEMES = ("Light", "Dark", "System")
ACCENTS = ("Blue", "Purple", "Green", "Orange", "Pink")
FONT_SIZES = ("Small", "Medium", "Large")
BUBBLE_STYLES = ("Modern", "Compact", "Glass")
SIDEBAR_STYLES = ("Expanded", "Compact", "Icon only")
DENSITIES = ("Comfortable", "Compact")

DEFAULT_SETTINGS = {
    "theme": "Dark",
    "accent_color": "Blue",
    "font_size": "Medium",
    "chat_bubble_style": "Modern",
    "sidebar_style": "Expanded",
    "message_density": "Comfortable",
    "updated_at": now_iso(),
}


def _validate(settings: Dict[str, Any]) -> Dict[str, Any]:
    validate_choice(settings.get("theme", "Dark"), THEMES, "theme")
    validate_choice(settings.get("accent_color", "Blue"), ACCENTS, "accent color")
    validate_choice(settings.get("font_size", "Medium"), FONT_SIZES, "font size")
    validate_choice(settings.get("chat_bubble_style", "Modern"), BUBBLE_STYLES, "chat bubble style")
    validate_choice(settings.get("sidebar_style", "Expanded"), SIDEBAR_STYLES, "sidebar style")
    validate_choice(settings.get("message_density", "Comfortable"), DENSITIES, "message density")
    return settings


@router.get("/settings/appearance")
def get_appearance_settings():
    return {"ok": True, "settings": merge_dict(DEFAULT_SETTINGS, read_state("appearance_settings", {}))}


@router.post("/settings/appearance")
def save_appearance_settings(payload: Dict[str, Any]):
    settings = merge_dict(DEFAULT_SETTINGS, read_state("appearance_settings", {}))
    settings = merge_dict(settings, payload.get("settings", payload))
    settings["updated_at"] = now_iso()
    _validate(settings)
    write_state("appearance_settings", settings)
    return {"ok": True, "settings": settings}


@router.post("/settings/appearance/reset")
def reset_appearance_settings():
    settings = dict(DEFAULT_SETTINGS)
    settings["updated_at"] = now_iso()
    write_state("appearance_settings", settings)
    return {"ok": True, "settings": settings}
