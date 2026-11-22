"""
multi_user_rag.py
=================
Per-user knowledge base manager for EVA.
Each user gets their own FAISS index and document folder.
"""

import os
import json
import shutil
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Base directory for all user knowledge bases
USER_KB_BASE = Path(os.getenv("USER_KB_DIR", "./user_knowledge_bases"))
USER_KB_BASE.mkdir(parents=True, exist_ok=True)

# Cache of user RAG managers
_user_rag_cache: dict = {}


class UserRAGManager:
    """Manages a personal RAG knowledge base for one user."""

    def __init__(self, user_id: str):
        self.user_id   = user_id
        self.user_dir  = USER_KB_BASE / user_id
        self.docs_dir  = self.user_dir / "documents"
        self.index_dir = self.user_dir / "faiss_index"
        self.meta_file = self.user_dir / "meta.json"
        self.user_dir.mkdir(parents=True, exist_ok=True)
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self.vectorstore = None
        self._load_meta()
        self._load_index()

    def _load_meta(self):
        if self.meta_file.exists():
            try:
                self.meta = json.loads(self.meta_file.read_text())
            except Exception:
                self.meta = {"docs": [], "doc_count": 0}
        else:
            self.meta = {"docs": [], "doc_count": 0}

    def _save_meta(self):
        self.meta_file.write_text(json.dumps(self.meta, indent=2))

    def _load_index(self):
        try:
            if self.index_dir.exists():
                from langchain_community.vectorstores import FAISS
                from langchain_huggingface import HuggingFaceEmbeddings
                embeddings = HuggingFaceEmbeddings(
                    model_name="sentence-transformers/all-MiniLM-L6-v2"
                )
                self.vectorstore = FAISS.load_local(
                    str(self.index_dir),
                    embeddings,
                    allow_dangerous_deserialization=True
                )
                logger.info(f"Loaded personal index for {self.user_id}")
        except Exception as e:
            logger.warning(f"Could not load index for {self.user_id}: {e}")
            self.vectorstore = None

    def add_document(self, file_path: str) -> dict:
        """Add a document to this user's personal knowledge base."""
        try:
            from langchain_community.document_loaders import (
                PyPDFLoader, TextLoader, UnstructuredWordDocumentLoader
            )
            from langchain.text_splitter import RecursiveCharacterTextSplitter
            from langchain_community.vectorstores import FAISS
            from langchain_huggingface import HuggingFaceEmbeddings

            fpath = Path(file_path)
            if not fpath.exists():
                return {"success": False, "error": f"File not found: {file_path}"}

            # Copy to user's docs folder
            dest = self.docs_dir / fpath.name
            shutil.copy2(fpath, dest)

            # Load document
            suffix = fpath.suffix.lower()
            if suffix == ".pdf":
                loader = PyPDFLoader(str(dest))
            elif suffix in [".docx", ".doc"]:
                loader = UnstructuredWordDocumentLoader(str(dest))
            else:
                loader = TextLoader(str(dest), encoding="utf-8")

            docs = loader.load()

            # Split into chunks
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=500, chunk_overlap=50
            )
            chunks = splitter.split_documents(docs)

            if not chunks:
                return {"success": False, "error": "No text extracted from document"}

            # Create or update FAISS index
            embeddings = HuggingFaceEmbeddings(
                model_name="sentence-transformers/all-MiniLM-L6-v2"
            )

            if self.vectorstore is None:
                self.vectorstore = FAISS.from_documents(chunks, embeddings)
            else:
                self.vectorstore.add_documents(chunks)

            # Save index
            self.index_dir.mkdir(parents=True, exist_ok=True)
            self.vectorstore.save_local(str(self.index_dir))

            # Update meta
            if fpath.name not in self.meta["docs"]:
                self.meta["docs"].append(fpath.name)
                self.meta["doc_count"] = len(self.meta["docs"])
                self._save_meta()

            logger.info(f"Added {fpath.name} to {self.user_id}'s KB ({len(chunks)} chunks)")
            return {
                "success":  True,
                "filename": fpath.name,
                "chunks":   len(chunks),
                "total_docs": self.meta["doc_count"]
            }

        except Exception as e:
            logger.error(f"Error adding doc for {self.user_id}: {e}")
            return {"success": False, "error": str(e)}

    def query(self, question: str, user_memory: str = "", k: int = 4) -> dict:
        """Query this user's personal knowledge base."""
        if self.vectorstore is None:
            return {
                "answer":      "",
                "sources":     [],
                "confidence":  0.0,
                "healed":      False,
                "fallback_mode": True
            }

        try:
            docs = self.vectorstore.similarity_search_with_score(question, k=k)
            if not docs:
                return {"answer": "", "sources": [], "confidence": 0.0, "healed": False, "fallback_mode": True}

            context = "\n\n".join([d.page_content for d, _ in docs])
            scores  = [float(s) for _, s in docs]
            confidence = max(0.0, min(1.0, 1.0 - (sum(scores) / len(scores)) / 2))

            from groq import Groq
            client = Groq(api_key=os.getenv("GROQ_API_KEY", ""))

            prompt = f"""You are EVA, a helpful AI assistant.
Use the following document context to answer the user's question.
If the context doesn't contain the answer, say so clearly.

Context from user's documents:
{context}

{f'User memory: {user_memory}' if user_memory else ''}

Question: {question}

Answer:"""

            response = client.chat.completions.create(
                model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
                temperature=0.7,
            )
            answer = response.choices[0].message.content

            sources = list(set([
                d.metadata.get("source", "Unknown")
                for d, _ in docs
            ]))

            return {
                "answer":      answer,
                "sources":     sources,
                "confidence":  confidence,
                "healed":      False,
                "fallback_mode": False
            }

        except Exception as e:
            logger.error(f"Query error for {self.user_id}: {e}")
            return {"answer": "", "sources": [], "confidence": 0.0, "healed": False, "fallback_mode": True}

    def delete_document(self, filename: str) -> dict:
        """Delete a document from this user's KB."""
        try:
            doc_path = self.docs_dir / filename
            if doc_path.exists():
                doc_path.unlink()

            if filename in self.meta["docs"]:
                self.meta["docs"].remove(filename)
                self.meta["doc_count"] = len(self.meta["docs"])
                self._save_meta()

            # Rebuild index without deleted doc
            if self.meta["docs"]:
                self.vectorstore = None
                if self.index_dir.exists():
                    shutil.rmtree(self.index_dir)
                for doc in self.meta["docs"]:
                    self.add_document(str(self.docs_dir / doc))
            else:
                self.vectorstore = None
                if self.index_dir.exists():
                    shutil.rmtree(self.index_dir)

            return {"success": True, "deleted": filename, "remaining": self.meta["doc_count"]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def clear_all_documents(self) -> dict:
        """Clear all documents from this user's KB."""
        try:
            if self.docs_dir.exists():
                shutil.rmtree(self.docs_dir)
                self.docs_dir.mkdir(parents=True)
            if self.index_dir.exists():
                shutil.rmtree(self.index_dir)
            self.vectorstore = None
            self.meta = {"docs": [], "doc_count": 0}
            self._save_meta()
            return {"success": True, "message": f"All documents cleared for {self.user_id}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_stats(self) -> dict:
        """Get stats for this user's KB."""
        return {
            "user_id":   self.user_id,
            "docs":      self.meta.get("docs", []),
            "doc_count": self.meta.get("doc_count", 0),
            "has_index": self.vectorstore is not None,
            "index_dir": str(self.index_dir),
            "plan":      "free",
            "max_docs":  20,
        }


def get_user_rag(user_id: str) -> UserRAGManager:
    """Get or create a RAG manager for a user."""
    # Sanitize user_id for filesystem
    safe_id = "".join(c if c.isalnum() or c in "-_." else "_" for c in user_id)
    if safe_id not in _user_rag_cache:
        _user_rag_cache[safe_id] = UserRAGManager(safe_id)
    return _user_rag_cache[safe_id]


def get_all_user_stats() -> list:
    """Get stats for all users (admin only)."""
    stats = []
    if USER_KB_BASE.exists():
        for user_dir in USER_KB_BASE.iterdir():
            if user_dir.is_dir():
                try:
                    mgr = get_user_rag(user_dir.name)
                    stats.append(mgr.get_stats())
                except Exception:
                    pass
    return stats
