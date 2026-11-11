from .memory_ranker import rank_items
from .memory_store import list_memories, recent_chats


def retrieve_memory_items(
    user_id: str,
    query: str,
    limit: int = 8,
) -> list[dict]:
    memories = list_memories(
        user_id,
        limit=200,
    )

    chats = []

    for chat in recent_chats(user_id, limit=30):
        chats.append({
            "id": f"chat-{chat['id']}",
            "user_id": user_id,
            "memory_type": "short_term",
            "memory_tier": "episodic",
            "validation_status": "unvalidated",
            "provenance": "chat_history",
            "confidence": 0.5,
            "content": (
                f"User: {chat['message']}\n"
                f"EVA: {chat['response']}"
            ),
            "importance": 2,
            "created_at": chat["created_at"],
        })

    return rank_items(
        query,
        memories + chats,
        limit=limit,
    )


def retrieve_memory(
    user_id: str,
    query: str,
    limit: int = 8,
) -> str:
    items = retrieve_memory_items(
        user_id,
        query,
        limit=limit,
    )

    if not items:
        return ""

    lines = []

    for item in items:
        memory_type = item.get(
            "memory_type",
            "memory",
        )
        memory_tier = item.get(
            "memory_tier",
            "episodic",
        )
        validation = item.get(
            "validation_status",
            "unvalidated",
        )
        content = (
            item.get("content") or ""
        ).strip()

        if content:
            lines.append(
                f"- [{memory_type}|{memory_tier}|{validation}] "
                f"{content[:700]}"
            )

    return "\n".join(lines)