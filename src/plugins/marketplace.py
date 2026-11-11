from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from eva_phase_common import now_iso, read_state, write_state
from plugins.installed_plugins import install_plugin, installed_state, save_installed
from plugins.plugin_runner import test_tool_endpoint
from plugins.tool_builder import custom_tools, save_custom_tool


router = APIRouter(tags=["plugins"])

MARKETPLACE = [
    {"id": "github-actions", "name": "GitHub Actions", "category": "Developer", "description": "Trigger repository workflows."},
    {"id": "notion-sync", "name": "Notion Sync", "category": "Knowledge", "description": "Sync Notion pages into EVA."},
    {"id": "slack-briefing", "name": "Slack Briefing", "category": "Team", "description": "Send run summaries to Slack."},
    {"id": "webhook-runner", "name": "Webhook Runner", "category": "Automation", "description": "Call approved webhook endpoints."},
]


@router.get("/plugins/marketplace")
def plugin_marketplace():
    installed_ids = {item.get("id") for item in installed_state().get("installed", [])}
    return {"ok": True, "plugins": [{**item, "installed": item["id"] in installed_ids} for item in MARKETPLACE]}


@router.get("/plugins/installed")
def installed_plugins():
    return {"ok": True, "installed": installed_state().get("installed", []), "custom_tools": custom_tools().get("tools", [])}


@router.post("/plugins/install")
def install_plugin_route(payload: Dict[str, Any]):
    plugin_id = payload.get("plugin_id") or payload.get("id")
    plugin = next((item for item in MARKETPLACE if item["id"] == plugin_id), None)
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return {"ok": True, "plugin": install_plugin(plugin)}


@router.post("/plugins/uninstall")
def uninstall_plugin(payload: Dict[str, Any]):
    plugin_id = payload.get("plugin_id") or payload.get("id")
    items = [item for item in installed_state().get("installed", []) if item.get("id") != plugin_id]
    save_installed(items)
    return {"ok": True, "plugin_id": plugin_id}


@router.post("/plugins/toggle")
def toggle_plugin(payload: Dict[str, Any]):
    plugin_id = payload.get("plugin_id") or payload.get("id")
    enabled = bool(payload.get("enabled"))
    items = installed_state().get("installed", [])
    matched = False
    for item in items:
        if item.get("id") == plugin_id:
            item["enabled"] = enabled
            item["updated_at"] = now_iso()
            matched = True
    if not matched:
        raise HTTPException(status_code=404, detail="Installed plugin not found")
    save_installed(items)
    return {"ok": True, "plugin_id": plugin_id, "enabled": enabled}


@router.post("/plugins/tools/custom")
def save_custom_tool_route(payload: Dict[str, Any]):
    return {"ok": True, "tool": save_custom_tool(payload)}


@router.post("/plugins/tools/test")
def test_custom_tool(payload: Dict[str, Any]):
    endpoint = payload.get("api_endpoint") or payload.get("endpoint") or ""
    return {"ok": True, **test_tool_endpoint(endpoint)}
