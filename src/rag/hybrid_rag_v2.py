"""
EVA Hybrid RAG Pipeline v2
===========================
BM25 (keyword) + sentence-transformers (semantic) + Reranker + Model Router

Architecture:
  Query
    â†“ Intent Detection (ML)
    â†“ Query Rewriter + Expander
    â†“ BM25 Search  â”€â”€â”
    â†“ Vector Search â”€â”¤ Merge + Dedup
                     â†“ Reranker
                     â†“ Model Router â†’ Best LLM
                     â†“ Answer + Sources + Audit

Install:
    pip install sentence-transformers chromadb rank_bm25 groq google-generativeai
"""

import os
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

logger = logging.getLogger(__name__)


# â”€â”€ Safe imports â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
import sys
sys.modules['torchao'] = None  # Work around torchao/torch version conflict for RAG embeddings

try:
    from sentence_transformers import SentenceTransformer
    ST_AVAILABLE = True
except ImportError:
    SentenceTransformer = None
    ST_AVAILABLE = False
    logger.warning("sentence-transformers not installed. Run: pip install sentence-transformers")

try:
    import chromadb
    CHROMA_AVAILABLE = True
except ImportError:
    chromadb = None
    CHROMA_AVAILABLE = False
    logger.warning("chromadb not installed. Run: pip install chromadb")

try:
    from rank_bm25 import BM25Okapi
    BM25_AVAILABLE = True
except ImportError:
    BM25Okapi = None
    BM25_AVAILABLE = False
    logger.warning("rank_bm25 not installed. Run: pip install rank_bm25")

# â”€â”€ Internal imports â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
try:
    from .model_router import route_and_call, detect_intent, EVA_SYSTEM
    from .query_rewriter import rewrite_query, expand_query
    from .citation_scorer import chunk_quality_score, source_confidence, remove_duplicate_chunks
    from .rag_audit import write_audit
except ImportError:
    from model_router import route_and_call, detect_intent, EVA_SYSTEM
    from query_rewriter import rewrite_query, expand_query
    from citation_scorer import chunk_quality_score, source_confidence, remove_duplicate_chunks
    from rag_audit import write_audit

try:
    from .bm25_retriever import BM25Retriever, tokenize
    BM25_RETRIEVER_STATUS = "ready"
except ImportError:
    try:
        from bm25_retriever import BM25Retriever, tokenize
        BM25_RETRIEVER_STATUS = "ready"
    except ImportError:
        BM25_RETRIEVER_STATUS = "fallback"
        logger.warning("BM25 retriever unavailable; using keyword fallback")

        def tokenize(text: str) -> List[str]:
            return [token.lower() for token in (text or "").split() if len(token) > 1]

        class BM25Retriever:
            def __init__(self, chunks, *args, **kwargs):
                self.chunks = list(chunks or [])

            def search(self, query: str, top_k: int = 8):
                return []

# â”€â”€ Config â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
BASE_DIR = Path(__file__).resolve().parent
CHROMA_DIR = BASE_DIR / "data" / "chroma_db"
EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
COLLECTION_NAME = os.getenv("CHROMA_COLLECTION", "eva_knowledge")
CONFIDENCE_THRESHOLD = float(os.getenv("RAG_CONFIDENCE_THRESHOLD", "0.25"))

# â”€â”€ Lazy singletons â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_embed_model: Optional[Any] = None
_chroma_client: Optional[Any] = None
_chroma_collection: Optional[Any] = None
_vectorless_chunks: List[Dict[str, Any]] = []


def _get_embed_model():
    global _embed_model
    if _embed_model is None and ST_AVAILABLE:
        try:
            logger.info(f"Loading embedding model: {EMBED_MODEL}")
            _embed_model = SentenceTransformer(EMBED_MODEL)
            logger.info("âœ… Embedding model loaded")
        except Exception as e:
            logger.error(f"Embedding model load failed: {e}")
    return _embed_model


def _get_chroma():
    global _chroma_client, _chroma_collection
    if _chroma_client is None and CHROMA_AVAILABLE:
        try:
            CHROMA_DIR.mkdir(parents=True, exist_ok=True)
            _chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
            _chroma_collection = _chroma_client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(f"âœ… ChromaDB loaded. Collection: {COLLECTION_NAME}, docs: {_chroma_collection.count()}")
        except Exception as e:
            logger.error(f"ChromaDB init failed: {e}")
    return _chroma_client, _chroma_collection


# â”€â”€ Text chunker â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> List[str]:
    """Split text into overlapping chunks."""
    import re
    text = re.sub(r"\n{3,}", "\n\n", (text or "").strip())
    if not text:
        return []
    chunks = []
    step = max(1, chunk_size - overlap)
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end].strip()
        if len(chunk) > 50:
            chunks.append(chunk)
        if end >= len(text):
            break
        start += step
    return chunks


# â”€â”€ Document indexing â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def normalize_rag_mode(mode: Optional[str]) -> str:
    """Accept older BM25 names while exposing vectorless to the API."""
    value = (mode or "auto").strip().lower()
    aliases = {"bm25": "vectorless", "keyword": "vectorless", "keywords": "vectorless", "text": "vectorless"}
    value = aliases.get(value, value)
    return value if value in {"auto", "hybrid", "vector", "vectorless"} else "auto"


def enhance_prompt(prompt: str, context: Optional[Dict[str, Any]] = None) -> str:
    """Improve retrieval prompts internally while preserving the user's meaning."""
    original = (prompt or "").strip()
    if not original:
        return original
    try:
        context = context or {}
        intent = str(context.get("intent") or detect_intent(original) or "general")
        tokens = tokenize(original)
        key_terms = " ".join(dict.fromkeys(tokens[:18]))
        if intent == "code" or any(term in original.lower() for term in ["error", "traceback", "stack", "function", "class", "log"]):
            return (
                f"{original}\n\n"
                "Internal retrieval focus: find exact code names, errors, stack traces, file names, log lines, likely cause, fix steps, and test commands.\n"
                f"Key terms: {key_terms}"
            )
        if intent in {"document", "search"} or context.get("rag"):
            return (
                f"{original}\n\n"
                "Internal retrieval focus: preserve the semantic question, include exact names and keywords, and retrieve concise supporting document chunks.\n"
                f"Key terms: {key_terms}"
            )
        return (
            f"{original}\n\n"
            "Internal retrieval focus: clarify the request, preserve meaning, and retrieve the most relevant context before answering."
        )
    except Exception:
        return original


def _auto_mode_for_query(query: str, status: Dict[str, Any]) -> str:
    preferred = _auto_preferred_mode(query)
    vector_ready = status.get("vector_rag") == "ready"
    vectorless_ready = status.get("vectorless_rag") in {"ready", "fallback"}

    if preferred == "vector" and not vector_ready:
        return "vectorless" if vectorless_ready else "vector"
    if preferred == "vectorless" and not vectorless_ready:
        return "vector" if vector_ready else "vectorless"
    if preferred == "hybrid":
        if vector_ready and vectorless_ready:
            return "hybrid"
        if vector_ready:
            return "vector"
        if vectorless_ready:
            return "vectorless"
    return preferred


def _auto_preferred_mode(query: str) -> str:
    text = (query or "").split("\n\nInternal retrieval focus", 1)[0].lower()
    exact_terms = [
        "exact", "keyword", "grep", "log", "traceback", "stack trace", "error code",
        "function", "class", "variable", "filename", "file name", "line ", "id ",
        "uuid", "where is", "find all", "show me", "name search",
    ]
    semantic_terms = [
        "summarize", "explain", "compare", "meaning", "why", "how", "what does",
        "document", "pdf", "docx", "report", "contract", "article", "semantic",
    ]
    important_terms = ["important", "critical", "unclear", "verify", "confidence", "best answer", "comprehensive"]

    if any(term in text for term in important_terms):
        return "hybrid"
    elif any(term in text for term in exact_terms):
        return "vectorless"
    elif any(term in text for term in semantic_terms):
        return "vector"
    return "hybrid"


def _retrievers_for_mode(mode: str) -> List[str]:
    if mode == "hybrid":
        return ["vector", "vectorless"]
    if mode == "vector":
        return ["vector"]
    if mode == "vectorless":
        return ["vectorless"]
    return []


def rag_runtime_status() -> Dict[str, Any]:
    """Lightweight status for route health without requiring a successful query."""
    try:
        _, collection = _get_chroma()
    except Exception:
        collection = None
    vector_ready = ST_AVAILABLE and CHROMA_AVAILABLE and collection is not None
    return {
        "online": True,
        "vector_rag": "ready" if vector_ready else "unavailable",
        "vectorless_rag": BM25_RETRIEVER_STATUS if BM25_RETRIEVER_STATUS in {"ready", "fallback"} else "unavailable",
        "default_mode": "auto",
    }


def _chunk_user_matches(chunk: Dict[str, Any], user_id: str, workspace_id: Optional[str] = None) -> bool:
    if user_id in {"default", "anonymous"}:
        user_matches = True
    else:
        metadata = chunk.get("metadata") or {}
        user_matches = chunk.get("user_id") == user_id or metadata.get("user_id") == user_id
    if not user_matches:
        return False
    if not workspace_id:
        return True
    metadata = chunk.get("metadata") or {}
    return metadata.get("workspace_id") == workspace_id or chunk.get("workspace_id") == workspace_id


def _index_vectorless_chunks(chunks: List[str], source: str, user_id: str, metadata: Optional[Dict]) -> int:
    """Keep a safe in-memory vectorless index so BM25 still works without Chroma."""
    global _vectorless_chunks
    base_meta = metadata or {}
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _vectorless_chunks = [
        chunk for chunk in _vectorless_chunks
        if not (
            chunk.get("user_id") == user_id
            and chunk.get("source") == source
            and (chunk.get("metadata") or {}).get("workspace_id") == base_meta.get("workspace_id")
        )
    ]
    for i, chunk in enumerate(chunks):
        meta = {
            "source": source,
            "user_id": user_id,
            "chunk_index": i,
            "vectorless": True,
            **base_meta,
        }
        _vectorless_chunks.append({
            "id": f"vectorless::{user_id}::{source}::{i}::{uuid.uuid4().hex[:8]}",
            "text": chunk,
            "metadata": meta,
            "source": source,
            "user_id": user_id,
            "workspace_id": meta.get("workspace_id"),
            "created_at": created_at,
            "keyword_score": 0.0,
            "vector_score": 0.0,
            "retrieval_channels": ["vectorless"],
        })
    return len(chunks)


def _vectorless_chunks_for_user(user_id: str, workspace_id: Optional[str] = None) -> List[Dict[str, Any]]:
    return [chunk for chunk in _vectorless_chunks if _chunk_user_matches(chunk, user_id, workspace_id)]


def _chroma_chunks_for_user(user_id: str, limit: int = 2000, workspace_id: Optional[str] = None) -> List[Dict[str, Any]]:
    _, collection = _get_chroma()
    if collection is None or collection.count() == 0:
        return []
    where = {"user_id": user_id} if user_id not in {"default", "anonymous"} else None
    data = collection.get(where=where, limit=limit, include=["documents", "metadatas"])
    texts = data.get("documents") or []
    metas = data.get("metadatas") or []
    ids = data.get("ids") or []
    chunks = []
    for i, text in enumerate(texts):
        meta = metas[i] if i < len(metas) and metas[i] else {}
        if workspace_id and meta.get("workspace_id") != workspace_id:
            continue
        chunks.append({
            "id": ids[i] if i < len(ids) else f"vector::{i}",
            "text": text,
            "metadata": meta,
            "source": meta.get("source") or meta.get("filename") or "unknown",
            "user_id": meta.get("user_id", user_id),
            "workspace_id": meta.get("workspace_id"),
            "keyword_score": 0.0,
            "vector_score": 0.0,
            "retrieval_channels": ["vector-docstore"],
        })
    return chunks


def _source_type(source: str, metadata: Optional[Dict[str, Any]] = None) -> str:
    meta = metadata or {}
    ext = str(meta.get("ext") or Path(source).suffix or "").lower()
    if ext == ".pdf":
        return "pdf"
    if ext == ".docx":
        return "docx"
    if ext == ".md":
        return "md"
    if str(source).startswith(("http://", "https://")):
        return "url"
    if ext in {".py", ".js", ".ts", ".tsx", ".jsx"}:
        return "code"
    return "txt"


def list_indexed_documents(user_id: str = "default", workspace_id: Optional[str] = None) -> Dict[str, Any]:
    by_source: Dict[str, Dict[str, Any]] = {}
    chunks = remove_duplicate_chunks(
        _chroma_chunks_for_user(user_id, workspace_id=workspace_id) +
        _vectorless_chunks_for_user(user_id, workspace_id=workspace_id)
    )
    for chunk in chunks:
        meta = chunk.get("metadata") or {}
        source = chunk.get("source") or meta.get("source") or meta.get("filename") or "unknown"
        if source not in by_source:
            by_source[source] = {
                "id": source,
                "name": meta.get("filename") or Path(source).name or source,
                "source": source,
                "type": _source_type(source, meta),
                "chunks": 0,
                "category": str(meta.get("ext") or _source_type(source, meta)).lstrip("."),
                "workspace_id": meta.get("workspace_id"),
                "channels": set(),
            }
        by_source[source]["chunks"] += 1
        by_source[source]["channels"].update(chunk.get("retrieval_channels") or [])
    docs = []
    for doc in by_source.values():
        doc["channels"] = sorted(doc["channels"])
        docs.append(doc)
    return {"documents": docs, "total": len(docs), "workspace_id": workspace_id}


def rag_stats_snapshot(user_id: str = "default", workspace_id: Optional[str] = None) -> Dict[str, Any]:
    status = rag_runtime_status()
    documents = list_indexed_documents(user_id, workspace_id=workspace_id).get("documents", [])
    vector_chunks = len(_chroma_chunks_for_user(user_id, workspace_id=workspace_id))
    vectorless_chunks = len(_vectorless_chunks_for_user(user_id, workspace_id=workspace_id))
    total_chunks = sum(doc.get("chunks", 0) for doc in documents)
    collections = []
    if vector_chunks:
        collections.append({"name": COLLECTION_NAME, "mode": "vector", "chunks": vector_chunks})
    if vectorless_chunks:
        collections.append({"name": "vectorless_memory", "mode": "vectorless", "chunks": vectorless_chunks})
    return {
        **status,
        "total_documents": len(documents),
        "total_chunks": total_chunks,
        "collections": collections,
        "embed_model": EMBED_MODEL,
        "workspace_id": workspace_id,
    }


def delete_indexed_document(doc_id: str, user_id: str = "default", workspace_id: Optional[str] = None) -> Dict[str, Any]:
    global _vectorless_chunks
    before = len(_vectorless_chunks)
    _vectorless_chunks = [
        chunk for chunk in _vectorless_chunks
        if not (
            _chunk_user_matches(chunk, user_id, workspace_id)
            and (chunk.get("id") == doc_id or chunk.get("source") == doc_id)
        )
    ]
    deleted_vectorless = before - len(_vectorless_chunks)
    deleted_vector = 0
    try:
        _, collection = _get_chroma()
        if collection is not None and collection.count() > 0:
            where = {"user_id": user_id} if user_id not in {"default", "anonymous"} else None
            data = collection.get(where=where, limit=2000, include=["metadatas"])
            ids = data.get("ids") or []
            metas = data.get("metadatas") or []
            delete_ids = []
            for i, item_id in enumerate(ids):
                meta = metas[i] if i < len(metas) and metas[i] else {}
                if workspace_id and meta.get("workspace_id") != workspace_id:
                    continue
                if item_id == doc_id or meta.get("source") == doc_id or meta.get("filename") == doc_id:
                    delete_ids.append(item_id)
            if delete_ids:
                collection.delete(ids=delete_ids)
                deleted_vector = len(delete_ids)
    except Exception as e:
        logger.warning(f"Vector document delete skipped: {e}")
    return {"ok": True, "deleted": doc_id, "deleted_chunks": deleted_vectorless + deleted_vector}


def _keyword_search_chunks(query: str, chunks: List[Dict[str, Any]], top_k: int = 8) -> List[Dict[str, Any]]:
    query_terms = set(tokenize(query))
    if not query_terms:
        return []
    query_lower = query.lower().strip()
    scored = []
    for chunk in chunks:
        text = chunk.get("text", "")
        text_lower = text.lower()
        text_terms = set(tokenize(text))
        overlap = len(query_terms & text_terms)
        phrase_bonus = 0.18 if query_lower and query_lower in text_lower else 0.0
        if overlap == 0 and phrase_bonus == 0:
            continue
        score = min(1.0, overlap / max(1, len(query_terms)) + phrase_bonus)
        scored.append({
            **chunk,
            "keyword_score": round(score, 4),
            "vector_score": float(chunk.get("vector_score", 0) or 0),
            "retrieval_channels": sorted(set(chunk.get("retrieval_channels", []) + ["vectorless"])),
        })
    return sorted(scored, key=lambda item: item.get("keyword_score", 0), reverse=True)[:max(1, top_k)]


def index_document(
    text: str,
    source: str,
    user_id: str = "default",
    workspace_id: Optional[str] = None,
    metadata: Optional[Dict] = None,
    chunk_size: int = 800,
    overlap: int = 100,
) -> Dict[str, Any]:
    """
    Index a document into ChromaDB (vector) + returns chunks for BM25.
    Call this when user uploads a file or ingests a URL.
    """
    chunks = chunk_text(text, chunk_size, overlap)
    if not chunks:
        return {"ok": False, "error": "No text extracted", "chunks": 0}

    metadata = {**(metadata or {})}
    if workspace_id:
        metadata["workspace_id"] = workspace_id

    vectorless_count = _index_vectorless_chunks(chunks, source, user_id, metadata)
    _, collection = _get_chroma()
    embed = _get_embed_model() if collection is not None else None

    if embed is None or collection is None:
        logger.warning("Embedding/ChromaDB unavailable â€” document NOT vector-indexed")
        return {
            "ok": True,
            "chunks": len(chunks),
            "source": source,
            "workspace_id": workspace_id,
            "vector_indexed": False,
            "vectorless_indexed": True,
            "vectorless_chunks": vectorless_count,
            "warnings": ["Vector store unavailable; indexed with vectorless keyword retrieval only"],
        }

    try:
        embeddings = embed.encode(chunks, batch_size=8, show_progress_bar=False).tolist()
        ids = [f"{user_id}::{source}::{i}::{uuid.uuid4().hex[:8]}" for i in range(len(chunks))]
        metas = [
            {
                "source": source,
                "user_id": user_id,
                "chunk_index": i,
                **metadata,
            }
            for i in range(len(chunks))
        ]
        collection.add(documents=chunks, embeddings=embeddings, ids=ids, metadatas=metas)
        logger.info(f"âœ… Indexed {len(chunks)} chunks from '{source}' for user '{user_id}'")
        return {
            "ok": True,
            "chunks": len(chunks),
            "source": source,
            "workspace_id": workspace_id,
            "vector_indexed": True,
            "vectorless_indexed": True,
            "vectorless_chunks": vectorless_count,
            "warnings": [],
        }
    except Exception as e:
        logger.error(f"Indexing failed: {e}")
        return {
            "ok": True,
            "chunks": len(chunks),
            "source": source,
            "workspace_id": workspace_id,
            "vector_indexed": False,
            "vectorless_indexed": True,
            "vectorless_chunks": vectorless_count,
            "warnings": [f"Vector indexing failed: {e}"],
        }


# â”€â”€ Vector search â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _vector_search(query: str, user_id: str, top_k: int = 8, workspace_id: Optional[str] = None) -> List[Dict[str, Any]]:
    _, collection = _get_chroma()
    if collection is None or collection.count() == 0:
        return []
    embed = _get_embed_model()
    if embed is None:
        return []
    try:
        q_embed = embed.encode([query], show_progress_bar=False).tolist()
        requested_results = min(max(top_k * 4, top_k), collection.count())
        results = collection.query(
            query_embeddings=q_embed,
            n_results=requested_results,
            where={"user_id": user_id} if user_id != "default" else None,
            include=["documents", "metadatas", "distances"],
        )
        hits = []
        for i, doc in enumerate(results["documents"][0]):
            distance = results["distances"][0][i]
            # Cosine distance â†’ similarity score
            score = max(0.0, 1.0 - distance)
            meta = results["metadatas"][0][i] if results["metadatas"] else {}
            if workspace_id and meta.get("workspace_id") != workspace_id:
                continue
            hits.append({
                "id": results["ids"][0][i] if results.get("ids") else str(i),
                "text": doc,
                "metadata": meta,
                "source": meta.get("source", "unknown"),
                "workspace_id": meta.get("workspace_id"),
                "vector_score": round(score, 4),
                "keyword_score": 0.0,
                "retrieval_channels": ["vector"],
            })
        return hits
    except Exception as e:
        logger.error(f"Vector search failed: {e}")
        return []


# â”€â”€ BM25 search over ChromaDB docs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _bm25_search(query: str, user_id: str, top_k: int = 8, workspace_id: Optional[str] = None) -> List[Dict[str, Any]]:
    try:
        chunks = remove_duplicate_chunks(
            _chroma_chunks_for_user(user_id, workspace_id=workspace_id) +
            _vectorless_chunks_for_user(user_id, workspace_id=workspace_id)
        )
        if not chunks:
            return []

        retriever = BM25Retriever(chunks)
        results = retriever.search(query, top_k=top_k)
        if not results:
            results = _keyword_search_chunks(query, chunks, top_k=top_k)
        for r in results:
            r.setdefault("vector_score", 0.0)
            r["retrieval_channels"] = sorted(set(r.get("retrieval_channels", []) + ["vectorless"]))
        return results
    except Exception as e:
        logger.error(f"BM25 search failed: {e}")
        return _keyword_search_chunks(query, _vectorless_chunks_for_user(user_id, workspace_id=workspace_id), top_k=top_k)


# â”€â”€ Reranker â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _rerank(query: str, results: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
    """
    Multi-signal reranker:
      - Term overlap (lightweight cross-attention proxy)
      - Vector score
      - BM25 score
      - Chunk quality
      - Dual-channel bonus (appeared in both BM25 + vector)
    """
    query_terms = set(tokenize(query))
    ranked = []
    for r in results:
        text_terms = set(tokenize(r.get("text", "")))
        overlap = len(query_terms & text_terms) / max(1, len(query_terms))
        vector = float(r.get("vector_score", 0) or 0)
        keyword = float(r.get("keyword_score", 0) or 0)
        quality = float(r.get("chunk_quality") or chunk_quality_score(r.get("text", ""), r.get("metadata", {})))
        channels = set(r.get("retrieval_channels", []))
        dual_bonus = 0.08 if "vector" in channels and ("bm25" in channels or "vectorless" in channels) else 0.0
        score = min(1.0, 0.38 * overlap + 0.25 * vector + 0.22 * keyword + 0.15 * quality + dual_bonus)
        ranked.append({**r, "rerank_score": round(score, 4), "chunk_quality": quality})
    return sorted(ranked, key=lambda x: x.get("rerank_score", 0), reverse=True)[:max(1, top_k)]


# â”€â”€ Merge BM25 + vector results â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _merge(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id: Dict[str, Dict] = {}
    for r in results:
        key = r.get("id") or r.get("text", "")[:80]
        if key not in by_id:
            by_id[key] = r
        else:
            existing = by_id[key]
            existing["vector_score"]  = max(existing.get("vector_score", 0),  r.get("vector_score", 0))
            existing["keyword_score"] = max(existing.get("keyword_score", 0), r.get("keyword_score", 0))
            channels = list(set(existing.get("retrieval_channels", []) + r.get("retrieval_channels", [])))
            existing["retrieval_channels"] = sorted(channels)
    return list(by_id.values())


# â”€â”€ Main search function â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def hybrid_search(
    query: str,
    user_id: str = "default",
    workspace_id: Optional[str] = None,
    top_k: int = 5,
    mode: str = "hybrid",           # "hybrid" | "vector" | "vectorless"
    min_confidence: float = CONFIDENCE_THRESHOLD,
) -> Dict[str, Any]:
    """
    Hybrid retrieval: BM25 + Vector + Reranker.
    Returns ranked chunks with scores.
    """
    requested_mode = normalize_rag_mode(mode)
    status = rag_runtime_status()
    preferred_mode = _auto_preferred_mode(query) if requested_mode == "auto" else requested_mode
    mode = _auto_mode_for_query(query, status) if requested_mode == "auto" else requested_mode
    fallback_used = False
    warnings = []
    if requested_mode == "auto" and mode != preferred_mode:
        fallback_used = True
        warnings.append(f"Automatic mode preferred {preferred_mode}, but used {mode} because a retriever was unavailable")
    if mode in {"hybrid", "vector"} and status.get("vector_rag") != "ready":
        warnings.append("Vector RAG is unavailable; semantic/vector results were skipped")
    if mode in {"hybrid", "vectorless"} and status.get("vectorless_rag") == "fallback":
        warnings.append("BM25 module unavailable; using simple keyword fallback")

    rewritten = rewrite_query(query)
    expanded = expand_query(rewritten)
    retrievers_used = []

    def run_mode(active_mode: str) -> List[Dict[str, Any]]:
        hits: List[Dict[str, Any]] = []
        if active_mode in ("hybrid", "vectorless"):
            retrievers_used.append("vectorless")
            for q in expanded[:3]:
                hits.extend(_bm25_search(q, user_id, top_k * 2, workspace_id=workspace_id))
        if active_mode in ("hybrid", "vector"):
            retrievers_used.append("vector")
            hits.extend(_vector_search(rewritten, user_id, top_k * 2, workspace_id=workspace_id))
        return hits[:max(1, top_k)]

    combined = run_mode(mode)
    if not combined and mode == "vector" and status.get("vectorless_rag") in {"ready", "fallback"}:
        fallback_used = True
        warnings.append("Vector RAG returned no results; fallback used Vectorless RAG")
        mode = "vectorless"
        combined = run_mode(mode)
    elif not combined and mode == "vectorless" and status.get("vector_rag") == "ready":
        fallback_used = True
        warnings.append("Vectorless RAG returned no results; fallback used Vector RAG")
        mode = "vector"
        combined = run_mode(mode)

    # Merge duplicates
    combined = _merge(combined)

    # Rerank
    ranked = _rerank(rewritten, combined, top_k * 2)

    # Confidence filter
    filtered = [r for r in ranked if r.get("rerank_score", 0) >= min_confidence]
    if not filtered and ranked:
        warnings.append("No results met the confidence threshold; returning the best available context")
        filtered = ranked

    results = filtered[:top_k]
    confidence = round(sum(r.get("rerank_score", 0) for r in results) / max(1, len(results)), 4)

    return {
        "ok": True,
        "query": query,
        "rewritten_query": rewritten,
        "results": results,
        "confidence": confidence,
        "result_count": len(results),
        "mode": mode,
        "requested_mode": requested_mode,
        "mode_used": mode,
        "retrievers_used": sorted(set(retrievers_used)),
        "fallback_used": fallback_used,
        "warning": "; ".join(warnings) if warnings else None,
        "warnings": warnings,
        "vector_rag": status.get("vector_rag"),
        "vectorless_rag": status.get("vectorless_rag"),
        "workspace_id": workspace_id,
    }


# â”€â”€ Main answer function (full pipeline) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def answer(
    query: str,
    user_id: str = "default",
    workspace_id: Optional[str] = None,
    top_k: int = 5,
    mode: str = "hybrid",
    min_confidence: float = CONFIDENCE_THRESHOLD,
    memory: str = "",
    history: Optional[List[Dict]] = None,
    chat_id: Optional[str] = None,
    intent: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Full EVA RAG pipeline:
      1. Hybrid retrieval (BM25 + Vector)
      2. Reranker
      3. Intent detection
      4. Model router â†’ best LLM
      5. Answer generation
      6. Audit trail
    """
    t0 = time.time()
    enhanced_query = enhance_prompt(query, {"rag": True, "intent": intent})
    prompt_enhanced = enhanced_query.strip() != (query or "").strip()

    # 1. Retrieve
    search_result = hybrid_search(query, user_id, workspace_id, top_k, mode, min_confidence)
    results = search_result.get("results", [])

    # 2. Build context from top chunks
    context_blocks = []
    for i, r in enumerate(results[:5], 1):
        src = r.get("source") or r.get("metadata", {}).get("source", f"source_{i}")
        score = r.get("rerank_score", 0)
        context_blocks.append(f"[Source {i}: {src} | score={score:.2f}]\n{r.get('text', '')[:800]}")
    context = "\n\n".join(context_blocks)

    # 3. Detect intent (use provided or auto-detect)
    detected_intent = intent or detect_intent(query)

    # 4. Route to best LLM + generate answer
    llm_result = route_and_call(
        query=enhanced_query,
        context=context,
        memory=memory,
        history=history or [],
        intent=detected_intent,
        system=EVA_SYSTEM,
    )
    if llm_result.get("answer", "").startswith("All LLM providers failed") and context:
        llm_result = {
            **llm_result,
            "answer": (
                "I found relevant retrieved context, but no LLM provider is configured right now.\n\n"
                f"{context_blocks[0]}"
            ),
            "fallback": True,
        }

    # 5. Audit
    audit = write_audit(chat_id, {
        "user_id": user_id,
        "workspace_id": workspace_id,
        "question": query,
        "enhanced_query": enhanced_query,
        "prompt_enhanced": prompt_enhanced,
        "intent": detected_intent,
        "mode": search_result.get("mode", mode),
        "results": results,
        "confidence": search_result.get("confidence", 0),
        "provider": llm_result.get("provider"),
        "model": llm_result.get("model"),
        "warnings": search_result.get("warnings", []),
    })

    total_ms = int((time.time() - t0) * 1000)

    return {
        "answer": llm_result["answer"],
        "provider": llm_result["provider"],
        "model": llm_result["model"],
        "intent": detected_intent,
        "confidence": search_result.get("confidence", 0),
        "sources": [r.get("source") or r.get("metadata", {}).get("source", "") for r in results],
        "results": results,
        "fallback": llm_result.get("fallback", False),
        "latency_ms": total_ms,
        "audit_id": audit.get("audit_id"),
        "chat_id": audit.get("chat_id"),
        "mode": search_result.get("mode", mode),
        "mode_used": search_result.get("mode_used", search_result.get("mode", mode)),
        "requested_mode": search_result.get("requested_mode", mode),
        "retrievers_used": search_result.get("retrievers_used", []),
        "fallback_used": search_result.get("fallback_used", False),
        "warning": search_result.get("warning"),
        "warnings": search_result.get("warnings", []),
        "prompt_enhanced": prompt_enhanced,
        "vector_rag": search_result.get("vector_rag"),
        "vectorless_rag": search_result.get("vectorless_rag"),
        "rewritten_query": search_result.get("rewritten_query", query),
        "original_query": query,
        "workspace_id": workspace_id,
    }

