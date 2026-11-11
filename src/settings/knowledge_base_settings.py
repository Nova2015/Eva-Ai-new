from typing import Any, Dict

from fastapi import APIRouter

from eva_phase_common import merge_dict, now_iso, read_state, validate_choice, write_state


router = APIRouter(tags=["settings"])

EMBEDDING_PROVIDERS = ("OpenAI", "HuggingFace", "Local")
VECTOR_DBS = ("FAISS", "Chroma", "Pinecone", "Qdrant")
RETRIEVAL_MODES = ("Vectorless", "Vector", "Hybrid")

DEFAULT_SETTINGS = {
    "embedding_provider": "OpenAI",
    "vector_db": "FAISS",
    "chunk_size": 900,
    "chunk_overlap": 120,
    "retrieval_mode": "Hybrid",
    "retrieval_top_k": 5,
    "reranker": True,
    "citations": True,
    "citation_strict_mode": False,
    "minimum_confidence_threshold": 0.2,
    "auto_reindex": True,
    "last_index_rebuild": "",
    "updated_at": now_iso(),
}


def _state():
    return merge_dict(DEFAULT_SETTINGS, read_state("knowledge_base_settings", {}))


@router.get("/settings/knowledge-base")
def get_knowledge_base_settings():
    return {"ok": True, "settings": _state()}


@router.post("/settings/knowledge-base")
def save_knowledge_base_settings(payload: Dict[str, Any]):
    settings = merge_dict(_state(), payload.get("settings", payload))
    validate_choice(settings.get("embedding_provider"), EMBEDDING_PROVIDERS, "embedding provider")
    validate_choice(settings.get("vector_db"), VECTOR_DBS, "vector DB")
    validate_choice(settings.get("retrieval_mode", "Hybrid"), RETRIEVAL_MODES, "retrieval mode")
    settings["chunk_size"] = max(128, int(settings.get("chunk_size", 900)))
    settings["chunk_overlap"] = max(0, min(int(settings.get("chunk_overlap", 120)), settings["chunk_size"] - 1))
    settings["retrieval_top_k"] = max(1, min(int(settings.get("retrieval_top_k", 5)), 50))
    settings["minimum_confidence_threshold"] = max(0.0, min(float(settings.get("minimum_confidence_threshold", 0.2)), 1.0))
    settings["reranker"] = bool(settings.get("reranker", True))
    settings["citations"] = bool(settings.get("citations", True))
    settings["citation_strict_mode"] = bool(settings.get("citation_strict_mode", False))
    settings["auto_reindex"] = bool(settings.get("auto_reindex", True))
    settings["updated_at"] = now_iso()
    write_state("knowledge_base_settings", settings)
    return {"ok": True, "settings": settings}


@router.post("/settings/knowledge-base/rebuild-index")
def rebuild_knowledge_base_index():
    settings = _state()
    settings["last_index_rebuild"] = now_iso()
    settings["updated_at"] = now_iso()
    write_state("knowledge_base_settings", settings)
    return {"ok": True, "message": "Knowledge base rebuild queued.", "settings": settings}


@router.delete("/settings/knowledge-base/indexed-docs")
def delete_indexed_docs():
    write_state("knowledge_base_index_delete", {"requested_at": now_iso(), "status": "queued"})
    return {"ok": True, "message": "Indexed document delete request queued for the active workspace."}
