from .memory_retriever import retrieve_memory, retrieve_memory_items
from .memory_store import (
    delete_memory,
    export_memories,
    forget_all_memories,
    init_memory_db,
    list_memories,
    save_chat,
    save_memory as store_memory,
    supersede_memory,
    update_memory,
    upsert_user,
    validate_memory,
)


PROJECT_TERMS = (
    "project", "eva", "rag", "fastapi", "render", "github",
    "deployment", "code assistant"
)
PREFERENCE_TERMS = (
    "prefer", "like", "style", "always", "never", "use",
    "don't", "do not"
)
GOAL_TERMS = (
    "goal", "next", "plan", "build", "upgrade", "want", "need"
)
SKILL_TERMS = (
    "skill", "engineer", "developer", "designer", "ml",
    "ai", "python", "react"
)


def infer_memory_type(content: str) -> str:
    text = (content or "").lower()

    if any(term in text for term in PROJECT_TERMS):
        return "project"
    if any(term in text for term in PREFERENCE_TERMS):
        return "preference"
    if any(term in text for term in GOAL_TERMS):
        return "goal"
    if any(term in text for term in SKILL_TERMS):
        return "skill"

    return "long_term"


def save_memory(
    user_id,
    content,
    importance=1,
    memory_type=None,
    memory_tier="episodic",
    confidence=0.5,
    provenance="chat_auto",
    validation_status="unvalidated",
    superseded_by=None,
):
    return store_memory(
        user_id=user_id,
        content=content,
        memory_type=memory_type or infer_memory_type(content),
        importance=importance,
        memory_tier=memory_tier,
        confidence=confidence,
        provenance=provenance,
        validation_status=validation_status,
        superseded_by=superseded_by,
    )


class MemoryV2Manager:
    def __init__(self):
        init_memory_db()

    def save_memory(
        self,
        user_id,
        content,
        importance=1,
        memory_type=None,
        memory_tier="episodic",
        confidence=0.5,
        provenance="chat_auto",
        validation_status="unvalidated",
        superseded_by=None,
    ):
        return save_memory(
            user_id,
            content,
            importance=importance,
            memory_type=memory_type,
            memory_tier=memory_tier,
            confidence=confidence,
            provenance=provenance,
            validation_status=validation_status,
            superseded_by=superseded_by,
        )

    def retrieve_memory(self, user_id, query, limit=8):
        return retrieve_memory(user_id, query, limit=limit)

    def retrieve_items(self, user_id, query, limit=8):
        return retrieve_memory_items(user_id, query, limit=limit)

    def save_chat(self, user_id, message, response, title="Chat"):
        return save_chat(user_id, message, response, title=title)

    def list_memories(self, user_id, query="", memory_type="", limit=100):
        return list_memories(
            user_id,
            query=query,
            memory_type=memory_type,
            limit=limit,
        )

    def delete_memory(self, user_id, memory_id):
        return delete_memory(user_id, memory_id)

    def update_memory(
        self,
        user_id,
        memory_id,
        content=None,
        memory_type=None,
        importance=None,
        memory_tier=None,
        confidence=None,
        provenance=None,
        validation_status=None,
        superseded_by=None,
    ):
        return update_memory(
            user_id,
            memory_id,
            content=content,
            memory_type=memory_type,
            importance=importance,
            memory_tier=memory_tier,
            confidence=confidence,
            provenance=provenance,
            validation_status=validation_status,
            superseded_by=superseded_by,
        )

    def validate_memory(
        self,
        user_id,
        memory_id,
        validation_status="user_confirmed",
        confidence=1.0,
    ):
        return validate_memory(
            user_id,
            memory_id,
            validation_status=validation_status,
            confidence=confidence,
        )

    def supersede_memory(self, user_id, memory_id, replacement_memory_id):
        return supersede_memory(
            user_id,
            memory_id,
            replacement_memory_id,
        )

    def forget_all(self, user_id):
        return forget_all_memories(user_id)

    def export_memories(self, user_id):
        return export_memories(user_id)

    def upsert_user(self, user_id, name="", email="", role="user"):
        return upsert_user(
            user_id,
            name=name,
            email=email,
            role=role,
        )