from eva_phase_common import new_id, now_iso, read_state, write_state


def installed_state():
    return read_state("plugins_installed", {"installed": []})


def save_installed(items):
    return write_state("plugins_installed", {"installed": items, "updated_at": now_iso()})


def install_plugin(plugin):
    state = installed_state()
    items = state.get("installed", [])
    plugin_id = plugin.get("id") or new_id("plugin")
    existing = next((item for item in items if item.get("id") == plugin_id), None)
    if existing:
        existing.update({"enabled": True, "updated_at": now_iso()})
    else:
        items.append({"id": plugin_id, "name": plugin.get("name", plugin_id), "enabled": True, "installed_at": now_iso()})
    save_installed(items)
    return next(item for item in items if item.get("id") == plugin_id)
