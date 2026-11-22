from importlib import import_module


ROUTER_MODULES = [
    "settings.model_settings",
    "settings.chat_settings",
    "settings.appearance_settings",
    "settings.knowledge_base_settings",
    "settings.integration_settings",
    "settings.security_settings",
    "training.domain_training",
    "evaluation.domain_evaluator",
    "monitoring.health",
    "plugins.marketplace",
    "agents.agent_manager",
    "team.workspace",
    "billing.subscriptions",
]


PHASE_ROUTERS = []
PHASE_ROUTE_ERRORS = []

for module_name in ROUTER_MODULES:
    try:
        module = import_module(module_name)
        router = getattr(module, "router", None)
        if router is not None:
            PHASE_ROUTERS.append(router)
    except Exception as exc:
        PHASE_ROUTE_ERRORS.append({"module": module_name, "error": str(exc)})
