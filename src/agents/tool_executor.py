def allowed_tool_summary(tools):
    return [{"name": tool, "status": "available"} for tool in (tools or [])]
