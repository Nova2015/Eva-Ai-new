from copy import deepcopy
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from eva_phase_common import mask_secret, merge_dict, now_iso, read_state, scrub_secrets, validate_choice, write_state


router = APIRouter(tags=["settings"])

PROVIDERS = {
    "OpenAI": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"],
    "Gemini": ["gemini-3.5-flash", "gemini-1.5-pro", "gemini-2.5-flash"],
    "Claude": ["claude-3-5-sonnet", "claude-3-5-haiku", "claude-3-opus"],
    "Groq": ["openai/gpt-oss-120b", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
    "Local Model": ["llama.cpp", "ollama:llama3", "local-custom"],
}

DEFAULT_SETTINGS = {
    "default_model": "Groq:openai/gpt-oss-120b",
    "providers": {
        provider: {
            "enabled": provider in ("Groq", "Local Model"),
            "api_key": "",
            "model": models[0],
            "temperature": 0.3,
            "max_tokens": 2048,
            "status": "not_configured",
        }
        for provider, models in PROVIDERS.items()
    },
    "updated_at": now_iso(),
}


def _raw() -> Dict[str, Any]:
    return merge_dict(deepcopy(DEFAULT_SETTINGS), read_state("model_settings", {}))


def _public(settings: Dict[str, Any]) -> Dict[str, Any]:
    payload = deepcopy(settings)
    for provider, config in payload.get("providers", {}).items():
        config["available_models"] = PROVIDERS.get(provider, [])
        config["api_key"] = mask_secret(config.get("api_key", ""))
        config["has_api_key"] = bool(settings.get("providers", {}).get(provider, {}).get("api_key"))
    return scrub_secrets(payload)


@router.get("/settings/models")
def get_model_settings():
    return {"ok": True, "settings": _public(_raw()), "providers": list(PROVIDERS.keys())}


@router.post("/settings/models")
def save_model_settings(payload: Dict[str, Any]):
    current = _raw()
    incoming = payload.get("settings", payload)
    providers = incoming.get("providers", {})
    for provider, config in providers.items():
        validate_choice(provider, PROVIDERS.keys(), "provider")
        model = config.get("model")
        if model:
            validate_choice(model, PROVIDERS[provider], "model")
        old_key = current["providers"][provider].get("api_key", "")
        new_key = str(config.get("api_key", ""))
        if not new_key or "*" in new_key:
            config["api_key"] = old_key
        config["temperature"] = max(0, min(2, float(config.get("temperature", current["providers"][provider]["temperature"]))))
        config["max_tokens"] = max(1, int(config.get("max_tokens", current["providers"][provider]["max_tokens"])))
    default_model = incoming.get("default_model")
    if default_model:
        provider, _, model = default_model.partition(":")
        validate_choice(provider, PROVIDERS.keys(), "default model provider")
        validate_choice(model, PROVIDERS[provider], "default model")
    saved = merge_dict(current, incoming)
    saved["updated_at"] = now_iso()
    write_state("model_settings", saved)
    return {"ok": True, "settings": _public(saved)}


@router.post("/settings/models/test")
def test_model_connection(payload: Dict[str, Any]):
    provider = payload.get("provider")
    validate_choice(provider, PROVIDERS.keys(), "provider")
    settings = _raw()
    provider_state = settings["providers"].get(provider, {})
    if provider == "Local Model":
        success = bool(provider_state.get("enabled"))
        message = "Local model route is enabled. Runtime availability is checked when a request is sent."
    else:
        success = bool(provider_state.get("enabled") and provider_state.get("api_key"))
        message = "Provider key is saved and masked." if success else "Enable the provider and save an API key before live use."
    provider_state["status"] = "ready" if success else "needs_configuration"
    settings["providers"][provider] = provider_state
    settings["updated_at"] = now_iso()
    write_state("model_settings", settings)
    return {
        "ok": True,
        "provider": provider,
        "success": success,
        "message": message,
        "api_key": mask_secret(provider_state.get("api_key")),
    }
