def active_alerts(metrics: dict, costs: dict):
    alerts = []
    if costs.get("status") == "over_budget":
        alerts.append({"severity": "warning", "message": "Estimated cost is over budget"})
    if metrics.get("uptime_status") != "nominal":
        alerts.append({"severity": "critical", "message": "Uptime status needs attention"})
    return alerts
