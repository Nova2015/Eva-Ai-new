from eva_phase_common import new_id, now_iso, read_state, write_state
from plugins.plugin_security import validate_auth_type


def custom_tools():
    return read_state("plugins_custom_tools", {"tools": []})


def save_custom_tool(payload):
    validate_auth_type(payload.get("auth_type", "None"))
    state = custom_tools()
    tools = state.get("tools", [])
    tool_id = payload.get("id") or new_id("tool")
    item = {
        "id": tool_id,
        "name": payload.get("name", "Custom tool"),
        "description": payload.get("description", ""),
        "api_endpoint": payload.get("api_endpoint", ""),
        "auth_type": payload.get("auth_type", "None"),
        "enabled": bool(payload.get("enabled", True)),
        "updated_at": now_iso(),
    }
    tools = [tool for tool in tools if tool.get("id") != tool_id]
    tools.insert(0, item)
    write_state("plugins_custom_tools", {"tools": tools, "updated_at": now_iso()})
    return item
