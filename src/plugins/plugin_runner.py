from plugins.plugin_security import dangerous_endpoint


def test_tool_endpoint(endpoint: str):
    if dangerous_endpoint(endpoint):
        return {"success": False, "message": "Endpoint is blocked by plugin security policy."}
    if not endpoint:
        return {"success": False, "message": "API endpoint is required."}
    return {"success": True, "message": "Tool endpoint passed placeholder validation."}
