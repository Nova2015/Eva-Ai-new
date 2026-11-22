"""
EVA RAG Routes v2
=================
Drop-in FastAPI router. Add to app.py:

    from rag.rag_routes_v2 import router as rag_router
    app.include_router(rag_router, prefix="/rag", tags=["RAG"])

Endpoints:
    POST /rag/query       — hybrid search + answer
    POST /rag/upload      — index uploaded file
    POST /rag/ingest-url  — index a URL
    GET  /rag/documents   — list indexed docs
    GET  /rag/stats       — collection stats
    DELETE /rag/document/{doc_id} — remove a doc
    POST /rag/chat        — multi-turn RAG chat
"""

import os
import uuid
import logging
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

try:
    from .hybrid_rag_v2 import (
        answer,
        chunk_text,
        delete_indexed_document,
        hybrid_search,
        index_document,
        _get_chroma,
        list_indexed_documents,
        normalize_rag_mode,
        rag_runtime_status,
        rag_stats_snapshot,
    )
except ImportError:
    from hybrid_rag_v2 import (
        answer,
        chunk_text,
        delete_indexed_document,
        hybrid_search,
        index_document,
        _get_chroma,
        list_indexed_documents,
        normalize_rag_mode,
        rag_runtime_status,
        rag_stats_snapshot,
    )

try:
    import upload_policy
    import job_manager as jm
except ImportError:
    from . import upload_policy
    from . import job_manager as jm

logger = logging.getLogger(__name__)
router = APIRouter()
security = HTTPBearer(auto_error=False)

UPLOAD_DIR = Path(os.getenv("EVA_UPLOAD_DIR", "/tmp/eva_uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

SUPPORTED_EXTS = {".pdf", ".txt", ".md", ".docx", ".csv", ".json", ".py", ".js", ".ts", ".html"}


def _run_upload_job(job_id: str, filename: str, tmp_file: str, size_bytes: int, user_id: str, workspace_id: Optional[str], ext: str):
    tmp_path = Path(tmp_file)
    try:
        jm.cleanup_finished_jobs()
        size_error = upload_policy.validate_upload_size(size_bytes)
        if size_error:
            raise ValueError(size_error["detail"])

        jm.update_job(job_id, status=jm.PARSING, progress=5, current_step="Extracting text")
        text = _extract_text(tmp_path, ext)
        if not text or not text.strip():
            raise ValueError("Could not extract text from file")

        jm.update_job(job_id, status=jm.CHUNKING, progress=25, current_step="Chunking text")
        chunks = chunk_text(text)

        jm.update_job(
            job_id,
            status=jm.VALIDATING,
            progress=40,
            current_step="Validating chunk count",
            chunk_count=len(chunks),
        )
        chunk_error = upload_policy.validate_chunk_count(len(chunks))
        if chunk_error:
            raise ValueError(chunk_error["detail"])

        jm.update_job(job_id, status=jm.EMBEDDING, progress=55, current_step="Creating embeddings", chunk_count=len(chunks))
        jm.update_job(job_id, status=jm.INDEXING, progress=70, current_step="Indexing document", chunk_count=len(chunks))
        result = index_document(
            text=text,
            source=filename,
            user_id=user_id,
            workspace_id=effective_workspace_id(workspace_id, user_id),
            metadata={"filename": filename, "ext": ext, "size": size_bytes},
        )
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "Indexing failed"))

        jm.update_job(
            job_id,
            status=jm.COMPLETE,
            progress=100,
            current_step="Complete",
            chunk_count=result.get("chunks", len(chunks)),
            result=result,
        )
    except Exception as exc:
        jm.update_job(job_id, status=jm.FAILED, progress=100, current_step="Failed", error=str(exc))
    finally:
        tmp_path.unlink(missing_ok=True)


# ── Auth helper (reuse existing JWT or allow anonymous) ───────────────────────
def get_user_id(creds: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> str:
    if not creds:
        return "anonymous"
    try:
        from jose import jwt as jose_jwt
        # No fallback secret. The old default accepted any token signed with
        # the string baked into source; with the key absent this now validates
        # nothing and every caller is anonymous — least privilege, not forged
        # identity. In the backend the key is required at startup, so absent
        # never happens here; this only removes the dangerous default.
        secret = (os.getenv("SECRET_KEY") or "").strip()
        if not secret:
            return "anonymous"
        payload = jose_jwt.decode(creds.credentials, secret, algorithms=["HS256"])
        return payload.get("sub") or payload.get("email") or "user"
    except Exception:
        return "anonymous"


# ── Request / Response models ─────────────────────────────────────────────────
def effective_workspace_id(workspace_id: Optional[str], user_id: Optional[str]) -> str:
    requested = (workspace_id or "").strip()
    if requested:
        return requested
    user_namespace = (user_id or "").strip()
    return user_namespace if user_namespace and user_namespace != "anonymous" else "default"


class QueryRequest(BaseModel):
    query: str
    workspace_id: Optional[str] = None
    top_k: int = 5
    mode: str = "auto"             # auto | hybrid | vector | vectorless
    min_confidence: float = 0.25
    memory: str = ""
    history: Optional[List[Dict]] = []
    chat_id: Optional[str] = None
    intent: Optional[str] = None   # override auto-detection


class ChatRequest(BaseModel):
    message: str = ""
    query: Optional[str] = None
    workspace_id: Optional[str] = None
    history: Optional[List[Dict]] = []
    chat_id: Optional[str] = None
    top_k: int = 5
    mode: str = "auto"
    memory: str = ""
    intent: Optional[str] = None


class IngestURLRequest(BaseModel):
    url: str
    workspace_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/limits")
async def rag_limits():
    """Backend-driven upload size and chunk limits for the UI."""
    return upload_policy.limits_payload()


@router.get("/status")
async def rag_status():
    """RAG route health without forcing model loading."""
    try:
        return rag_runtime_status()
    except Exception as e:
        return {
            "online": True,
            "vector_rag": "unavailable",
            "vectorless_rag": "unavailable",
            "default_mode": "auto",
            "error": str(e),
        }


@router.post("/query")
async def rag_query(req: QueryRequest, user_id: str = Depends(get_user_id)):
    """Hybrid RAG query — retrieves + routes to best LLM + returns answer."""
    if not req.query or not req.query.strip():
        raise HTTPException(status_code=400, detail="query cannot be empty")
    workspace_id = effective_workspace_id(req.workspace_id, user_id)
    try:
        result = answer(
            query=req.query.strip(),
            user_id=user_id,
            workspace_id=workspace_id,
            top_k=req.top_k,
            mode=normalize_rag_mode(req.mode),
            min_confidence=req.min_confidence,
            memory=req.memory,
            history=req.history or [],
            chat_id=req.chat_id,
            intent=req.intent,
        )
        return result
    except Exception as e:
        logger.error(f"RAG query failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat")
async def rag_chat(req: ChatRequest, user_id: str = Depends(get_user_id)):
    """Multi-turn RAG chat endpoint."""
    prompt = (req.message or req.query or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="message cannot be empty")
    workspace_id = effective_workspace_id(req.workspace_id, user_id)
    try:
        result = answer(
            query=prompt,
            user_id=user_id,
            workspace_id=workspace_id,
            top_k=req.top_k,
            mode=normalize_rag_mode(req.mode),
            memory=req.memory,
            history=req.history or [],
            chat_id=req.chat_id,
            intent=req.intent,
        )
        return {
            "answer": result["answer"],
            "response": result["answer"],
            "provider": result.get("provider"),
            "model": result.get("model"),
            "intent": result.get("intent"),
            "confidence": result.get("confidence"),
            "sources": result.get("sources", []),
            "fallback": result.get("fallback", False),
            "fallback_used": result.get("fallback_used", result.get("fallback", False)),
            "latency_ms": result.get("latency_ms"),
            "mode": result.get("mode", normalize_rag_mode(req.mode)),
            "mode_used": result.get("mode_used", result.get("mode", normalize_rag_mode(req.mode))),
            "retrievers_used": result.get("retrievers_used", []),
            "warning": result.get("warning"),
            "warnings": result.get("warnings", []),
            "prompt_enhanced": result.get("prompt_enhanced", False),
            "vector_rag": result.get("vector_rag"),
            "vectorless_rag": result.get("vectorless_rag"),
            "workspace_id": workspace_id,
        }
    except Exception as e:
        logger.error(f"RAG chat failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload")
async def rag_upload(
    file: UploadFile = File(...),
    workspace_id: Optional[str] = Form(None),
    user_id: str = Depends(get_user_id),
):
    """Upload and index a document into the vector store."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename")

    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}. Allowed: {', '.join(SUPPORTED_EXTS)}")

    tmp_path = UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"
    size_bytes = 0
    try:
        with tmp_path.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size_bytes += len(chunk)
                out.write(chunk)
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Failed to stage upload: {exc}")

    namespace = effective_workspace_id(workspace_id, user_id)
    job_id = uuid.uuid4().hex[:12]
    jm.create_job(job_id, filename=file.filename)
    thread = threading.Thread(
        target=_run_upload_job,
        args=(job_id, file.filename, str(tmp_path), size_bytes, user_id, namespace, ext),
        daemon=True,
    )
    thread.start()
    return {
        "ok": True,
        "job_id": job_id,
        "status": "QUEUED",
        "filename": file.filename,
        "chunks_created": 0,
        "workspace_id": namespace,
        "async_jobs": True,
        "message": "Upload accepted. Processing in the background.",
    }


@router.post("/ingest-url")
async def rag_ingest_url(req: IngestURLRequest, user_id: str = Depends(get_user_id)):
    """Fetch a URL and index its text content."""
    url = req.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")
    workspace_id = effective_workspace_id(req.workspace_id, user_id)
    try:
        import httpx
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "EVA-RAG/2.0"})
            resp.raise_for_status()
            raw = resp.text

        text = _strip_html(raw)
        if not text or len(text.strip()) < 100:
            raise HTTPException(status_code=422, detail="URL returned insufficient text content")

        result = index_document(
            text=text,
            source=url,
            user_id=user_id,
            workspace_id=workspace_id,
            metadata={"url": url, "type": "web", **(req.metadata or {})},
        )

        if not result.get("ok"):
            raise HTTPException(status_code=500, detail=result.get("error", "Indexing failed"))

        return {
            "ok": True,
            "url": url,
            "workspace_id": workspace_id,
            "chunks_created": result["chunks"],
            "vector_indexed": result.get("vector_indexed", False),
            "vectorless_indexed": result.get("vectorless_indexed", False),
            "warnings": result.get("warnings", []),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"URL ingest failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs/{job_id}")
async def rag_job_status(job_id: str):
    job = jm.get_job(job_id)
    if job.get("status") == "NOT_FOUND":
        raise HTTPException(status_code=404, detail=job["error"])
    return job


@router.get("/documents")
async def rag_documents(workspace_id: Optional[str] = None, user_id: str = Depends(get_user_id)):
    """List all indexed documents for this user."""
    try:
        return list_indexed_documents(user_id, workspace_id=effective_workspace_id(workspace_id, user_id))
    except Exception as e:
        logger.error(f"Documents list failed: {e}")
        return {"documents": [], "error": str(e)}


@router.get("/stats")
async def rag_stats(workspace_id: Optional[str] = None, user_id: str = Depends(get_user_id)):
    """Collection statistics."""
    try:
        stats = rag_stats_snapshot(user_id, workspace_id=effective_workspace_id(workspace_id, user_id))
        return {
            **stats,
            "total_documents": stats.get("total_documents", stats.get("document_count", 0)),
            "document_count": stats.get("document_count", stats.get("total_documents", 0)),
            "total_chunks": stats.get("total_chunks", stats.get("chunk_count", 0)),
            "chunk_count": stats.get("chunk_count", stats.get("total_chunks", 0)),
        }
    except Exception as e:
        return {"total_documents": 0, "total_chunks": 0, "error": str(e)}


@router.delete("/document/{doc_id}")
async def rag_delete_document(doc_id: str, workspace_id: Optional[str] = None, user_id: str = Depends(get_user_id)):
    """Delete a specific document chunk by ID."""
    try:
        return delete_indexed_document(doc_id, user_id, workspace_id=effective_workspace_id(workspace_id, user_id))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Text extraction helpers ───────────────────────────────────────────────────

def _extract_text(path: Path, ext: str) -> str:
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as e:
            logger.error(f"PDF extraction failed: {e}")
            return ""
    if ext == ".docx":
        try:
            from docx import Document
            doc = Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception as e:
            logger.error(f"DOCX extraction failed: {e}")
            return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        logger.error(f"Text read failed: {e}")
        return ""


def _strip_html(html: str) -> str:
    import re
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-zA-Z]+;", " ", text)
    text = re.sub(r"\s{3,}", "\n\n", text)
    return text.strip()


def _guess_type(source: str) -> str:
    src = source.lower()
    if src.endswith(".pdf"):      return "pdf"
    if src.endswith(".docx"):     return "docx"
    if src.endswith(".md"):       return "md"
    if src.startswith("http"):    return "url"
    if any(src.endswith(e) for e in [".py", ".js", ".ts"]): return "code"
    return "txt"
