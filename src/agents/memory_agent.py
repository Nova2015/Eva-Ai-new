from collections import Counter


def _load_memory_store():
    try:
        from memory.memory_store import list_memories, recent_chats
        return list_memories, recent_chats
    except Exception:
        return None, None


def run_memory_task(user_id="user_001", instruction="", payload=None):
    list_memories, recent_chats = _load_memory_store()
    if not list_memories:
        return {
            "status": "warning",
            "summary": "Memory Agent could not load Memory V2 storage.",
            "duplicates": [],
            "project_summary": "",
        }

    memories = list_memories(user_id, limit=500)
    chats = recent_chats(user_id, limit=25)
    normalized = Counter((m.get("content") or "").strip().lower() for m in memories)
    duplicates = [
        {"content": content, "count": count}
        for content, count in normalized.items()
        if content and count > 1
    ]
    project_items = [m["content"] for m in memories if m.get("memory_type") == "project"]
    project_summary = "\n".join(f"- {item}" for item in project_items[:8])

    return {
        "status": "completed",
        "summary": f"Memory Agent reviewed {len(memories)} memories and {len(chats)} recent chats.",
        "duplicates": duplicates[:20],
        "project_summary": project_summary or "No project memories saved yet.",
        "recommendations": [
            "Merge duplicate memories with the same meaning.",
            "Promote recurring project facts to project memories.",
            "Keep short-term chat rows separate from long-term user preferences.",
        ],
    }
