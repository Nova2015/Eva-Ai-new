"""
multi_user_rag.py
Per-user RAG wrapper — isolates each user's uploaded documents
while falling back to the global SelfHealingRAG for shared context.
"""

import json
import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger("EVA.multi_user_rag")

# ── Per-user RAG cache ────────────────────────────────────────
_user_rags: dict = {}
USER_KB_BASE = Path(os.getenv("USER_KB_DIR", Path(__file__).resolve().parent.parent / "user_knowledge_bases"))


class UserRAG:
    """
    Thin wrapper around SelfHealingRAG scoped to a single user_id.
    Documents uploaded by this user are stored in a dedicated sub-folder
    so their context doesn't bleed into other users' queries.
    """

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.user_dir = USER_KB_BASE / self.user_id
        self.docs_dir = self.user_dir / "documents"
        self.index_dir = self.user_dir / "faiss_index"
        self.meta_file = self.user_dir / "meta.json"
        self._rag = None
        self.user_dir.mkdir(parents=True, exist_ok=True)
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self.meta = self._load_meta()
        self._init_rag()

    def _load_meta(self) -> dict:
        if not self.meta_file.exists():
            return {"docs": [], "doc_count": 0}
        try:
            return json.loads(self.meta_file.read_text(encoding="utf-8"))
        except Exception:
            return {"docs": [], "doc_count": 0}

    def _save_meta(self):
        self.meta["doc_count"] = len(self.meta.get("docs", []))
        self.meta_file.write_text(json.dumps(self.meta, indent=2), encoding="utf-8")

    def _init_rag(self):
        try:
            from rag_pipeline import SelfHealingRAG

            self._rag = SelfHealingRAG(data_dir=str(self.index_dir))
            logger.info(f"UserRAG initialised for {self.user_id} at {self.user_dir}")
        except Exception as e:
            logger.warning(f"UserRAG init failed for {self.user_id}: {e} — falling back to global RAG")
            self._rag = None

    def query(self, question: str, user_memory: str = "") -> dict:
        """
        Query this user's personal RAG index.
        Returns a dict with at least an 'answer' key and optional 'confidence'.
        """
        try:
            try:
                from rag.hybrid_retriever import answer as rag2_answer
                from settings.knowledge_base_settings import _state as kb_state

                return rag2_answer(
                    query=question,
                    user_id=self.user_id,
                    settings=kb_state(),
                    vectorstore=self.vectorstore,
                    user_memory=user_memory,
                )
            except Exception as rag2_exc:
                logger.warning(f"RAG 2.0 user query fallback for {self.user_id}: {rag2_exc}")
            if self._rag is None:
                return {"answer": "", "confidence": 0.0, "source": "none"}
            result = self._rag.query(question, user_memory=user_memory)
            return result if isinstance(result, dict) else {"answer": str(result), "confidence": 0.5}
        except Exception as e:
            logger.error(f"UserRAG query error for {self.user_id}: {e}")
            return {"answer": "", "confidence": 0.0, "error": str(e)}

    def add_document(self, file_path: str) -> bool:
        """Index a document into this user's personal RAG."""
        try:
            source = Path(file_path)
            if not source.exists():
                return False
            dest = self.docs_dir / source.name
            if source.resolve() != dest.resolve():
                shutil.copy2(source, dest)
            docs = self.meta.setdefault("docs", [])
            if dest.name not in docs:
                docs.append(dest.name)
                self._save_meta()
            if self._rag is not None and hasattr(self._rag, "reload_index"):
                try:
                    self._rag.reload_index()
                except Exception:
                    pass
            return True
        except Exception as e:
            logger.error(f"UserRAG add_document error for {self.user_id}: {e}")
            return False

    @property
    def vectorstore(self):
        return getattr(self._rag, "vectorstore", None)

    def get_stats(self) -> dict:
        self.meta = self._load_meta()
        return {
            "user_id": self.user_id,
            "docs": self.meta.get("docs", []),
            "doc_count": len(self.meta.get("docs", [])),
            "has_index": self.vectorstore is not None,
            "documents_dir": str(self.docs_dir),
            "index_dir": str(self.index_dir),
        }

    def delete_document(self, filename: str) -> dict:
        safe_name = Path(filename).name
        path = self.docs_dir / safe_name
        if path.exists():
            path.unlink()
        docs = [item for item in self.meta.get("docs", []) if item != safe_name]
        self.meta["docs"] = docs
        self._save_meta()
        return {"success": True, "deleted": safe_name, "remaining": len(docs)}

    def clear_all_documents(self) -> dict:
        if self.docs_dir.exists():
            shutil.rmtree(self.docs_dir)
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        if self.index_dir.exists():
            shutil.rmtree(self.index_dir)
        self.meta = {"docs": [], "doc_count": 0}
        self._save_meta()
        return {"success": True, "message": f"All documents cleared for {self.user_id}"}


def get_user_rag(user_id: str) -> UserRAG:
    """
    Return (and cache) a UserRAG instance for the given user_id.
    Thread-safe for single-process deployments (Render free tier).
    """
    global _user_rags
    safe_user_id = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(user_id or "anonymous"))
    if safe_user_id not in _user_rags:
        _user_rags[safe_user_id] = UserRAG(safe_user_id)
    return _user_rags[safe_user_id]


def clear_user_rag(user_id: str) -> None:
    """Remove a user's RAG from the cache (e.g. on logout)."""
    safe_user_id = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(user_id or "anonymous"))
    _user_rags.pop(safe_user_id, None)
    logger.info(f"UserRAG cache cleared for {safe_user_id}")


def get_all_user_stats() -> list:
    stats = []
    if USER_KB_BASE.exists():
        for path in USER_KB_BASE.iterdir():
            if not path.is_dir():
                continue
            try:
                stats.append(get_user_rag(path.name).get_stats())
            except Exception:
                pass
    return stats
