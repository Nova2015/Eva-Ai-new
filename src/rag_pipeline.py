"""
Self-Healing Hybrid RAG Pipeline
Vector Search (FAISS) + Keyword Search (BM25) + Memory + Groq LLM
"""

import os
import logging
from typing import Optional
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Safe optional imports ─────────────────────────────────
# Try community embeddings first (lighter), then huggingface
try:
    from langchain_community.embeddings import HuggingFaceEmbeddings
    HF_AVAILABLE = True
except ImportError:
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
        HF_AVAILABLE = True
    except ImportError:
        HuggingFaceEmbeddings = None
        HF_AVAILABLE = False
        logger.warning("HuggingFaceEmbeddings not available")

try:
    from langchain_community.vectorstores import FAISS
    FAISS_AVAILABLE = True
except ImportError:
    FAISS = None
    FAISS_AVAILABLE = False
    logger.warning("langchain_community not installed")

try:
    from langchain_groq import ChatGroq
    GROQ_AVAILABLE = True
except ImportError:
    ChatGroq = None
    GROQ_AVAILABLE = False
    logger.warning("langchain_groq not installed")

try:
    from rank_bm25 import BM25Okapi
    BM25_AVAILABLE = True
except ImportError:
    BM25Okapi = None
    BM25_AVAILABLE = False
    logger.warning("rank_bm25 not installed")

FAISS_INDEX_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "faiss_index")
# Use smallest possible model to stay under 512MB RAM on Render free tier
EMBEDDINGS_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Global lazy embedding instance — only created when first needed
_embeddings_instance = None

def get_embeddings():
    global _embeddings_instance
    if _embeddings_instance is None and HF_AVAILABLE:
        try:
            _embeddings_instance = HuggingFaceEmbeddings(
                model_name=EMBEDDINGS_MODEL,
                model_kwargs={"device": "cpu"},
                encode_kwargs={"normalize_embeddings": True, "batch_size": 8},
            )
        except Exception as e:
            logger.error(f"Embeddings init failed: {e}")
    return _embeddings_instance

SYSTEM_PROMPT = """You are EVA (Embedded Virtual Assistant), a helpful AI assistant powered by RAG + Groq LLaMA.
- You DO have conversation memory and context within a session
- Greet the user warmly ONLY on their very first message
- For all subsequent messages, respond directly without re-introducing yourself
- Never say you lack memory or cannot retain conversations
- Be concise, friendly and helpful

Context: {context}
Memory: {memory}
Question: {question}
Answer:"""


class SelfHealingRAG:
    def __init__(self, data_dir: str = None):
        self.data_dir = data_dir
        self._llm = None
        self._embeddings = None  # lazy
        self.vectorstore = None
        self.bm25 = None
        self.all_docs = []
        self.confidence_threshold = 0.3
        # Don't load index at init time — load on first query to save RAM
        logger.info("SelfHealingRAG created (index loads on first use)")

    def _ensure_index(self):
        """Load index on first use, not at startup."""
        if self.vectorstore is not None:
            return  # already loaded
        if self._embeddings is None:
            self._embeddings = get_embeddings()
        if self._embeddings is None:
            return
        self._load_index()

    @property
    def llm(self):
        if self._llm is None and GROQ_AVAILABLE and ChatGroq:
            try:
                self._llm = ChatGroq(
                    api_key=os.getenv("GROQ_API_KEY"),
                    model="openai/gpt-oss-120b"
                )
            except Exception as e:
                logger.error(f"ChatGroq init failed: {e}")
        return self._llm

    def _load_index(self):
        """Load FAISS index and build BM25 index."""
        if not FAISS_AVAILABLE or not self._embeddings:
            logger.warning("FAISS or embeddings not available — skipping index load")
            return

        index_path = self.data_dir or FAISS_INDEX_PATH
        if os.path.exists(index_path):
            try:
                self.vectorstore = FAISS.load_local(
                    index_path, self._embeddings,
                    allow_dangerous_deserialization=True
                )
                self.all_docs = list(self.vectorstore.docstore._dict.values())
                if BM25_AVAILABLE and self.all_docs:
                    tokenized = [d.page_content.lower().split() for d in self.all_docs]
                    self.bm25 = BM25Okapi(tokenized)
                logger.info(f"✅ Hybrid index loaded. {len(self.all_docs)} chunks.")
            except Exception as e:
                logger.warning(f"⚠️ Failed to load index: {e}")
                self.vectorstore = None
                self.bm25 = None
        else:
            logger.info("ℹ️ No FAISS index found. Upload a PDF to create one.")

    def reload_index(self):
        """Hot-reload index after new documents added."""
        self.vectorstore = None
        self.bm25 = None
        self.all_docs = []
        if self._embeddings is None:
            self._embeddings = get_embeddings()
        self._load_index()

    def _hybrid_retrieve(self, query: str, k: int = 4):
        """
        Hybrid retrieval: Vector Search + BM25 Keyword Search
        Combines both results and ranks by score.
        """
        results = []
        scores = []
        seen_contents = set()

        # 1. Vector Search (semantic)
        if self.vectorstore:
            try:
                vector_results = self.vectorstore.similarity_search_with_relevance_scores(query, k=k)
                for doc, score in vector_results:
                    if doc.page_content not in seen_contents:
                        results.append(doc)
                        scores.append(score)
                        seen_contents.add(doc.page_content)
                logger.info(f"Vector search: {len(vector_results)} results")
            except Exception as e:
                logger.error(f"Vector search error: {e}")

        # 2. BM25 Keyword Search
        if self.bm25 and self.all_docs:
            try:
                tokenized_query = query.lower().split()
                bm25_scores = self.bm25.get_scores(tokenized_query)
                top_indices = sorted(
                    range(len(bm25_scores)),
                    key=lambda i: bm25_scores[i],
                    reverse=True
                )[:k]

                for idx in top_indices:
                    doc = self.all_docs[idx]
                    bm25_score = min(bm25_scores[idx] / 10.0, 1.0)
                    if doc.page_content not in seen_contents and bm25_score > 0.01:
                        results.append(doc)
                        scores.append(bm25_score)
                        seen_contents.add(doc.page_content)
                logger.info(f"BM25 search: added {len(top_indices)} keyword results")
            except Exception as e:
                logger.error(f"BM25 search error: {e}")

        # Sort combined results by score
        if results:
            paired = sorted(zip(scores, results), key=lambda x: x[0], reverse=True)
            scores_sorted, results_sorted = zip(*paired)
            return list(results_sorted)[:k], list(scores_sorted)[:k]

        return [], []

    def _self_heal(self, query: str, docs: list, scores: list):
        """
        Self-healing strategy:
        1. Check average confidence score
        2. If low → broaden query and retry
        3. If still low → fallback to general knowledge
        """
        avg_score = sum(scores) / len(scores) if scores else 0

        if avg_score >= self.confidence_threshold:
            return docs, False  # Good enough

        logger.info(f"🔧 Self-healing triggered. Avg score: {avg_score:.2f}")

        # Broaden query
        broad_query = self._broaden_query(query)
        new_docs, new_scores = self._hybrid_retrieve(broad_query, k=6)
        new_avg = sum(new_scores) / len(new_scores) if new_scores else 0

        if new_avg >= self.confidence_threshold:
            logger.info(f"✅ Healed with broad query. New avg: {new_avg:.2f}")
            return new_docs, False

        logger.info("⚠️ Using general knowledge fallback.")
        return [], True

    def _broaden_query(self, query: str) -> str:
        """Remove stop words and keep key terms."""
        stopwords = {
            "what", "is", "are", "the", "a", "an", "how", "why",
            "when", "where", "who", "does", "do", "can", "tell",
            "me", "about", "explain", "please", "give", "show"
        }
        words = query.lower().split()
        key_terms = [w for w in words if w not in stopwords]
        return " ".join(key_terms) if key_terms else query

    def _call_llm(self, prompt: str) -> str:
        """Call Groq LLM."""
        try:
            if not self.llm:
                return "LLM not available — please set GROQ_API_KEY in environment."
            response = self.llm.invoke(prompt)
            return response.content.strip()
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return "I'm sorry, I couldn't generate a response right now. Please try again."

    def query(self, question: str, user_memory: str = "") -> dict:
        """Main RAG query with hybrid retrieval + self-healing."""
        self._ensure_index()  # lazy load on first query only
        # Hybrid retrieval
        docs, scores = self._hybrid_retrieve(question)
        healed = False
        fallback = False

        if docs:
            docs, fallback = self._self_heal(question, docs, scores)
            healed = fallback

        # Build context
        if docs and not fallback:
            context = "\n\n".join([d.page_content for d in docs[:3]])
            confidence = sum(scores[:3]) / 3 if scores else 0
        else:
            context = "No specific document context available. Use your general knowledge."
            confidence = 0.0

        # Build prompt
        prompt = SYSTEM_PROMPT.format(
            context=context[:1500],
            memory=user_memory[:500] if user_memory else "No prior memory.",
            question=question
        )

        answer = self._call_llm(prompt)
        sources = [f"Page {d.metadata.get('page', '?')}" for d in docs] if docs else []

        return {
            "answer": answer,
            "sources": sources,
            "confidence": round(confidence, 3),
            "healed": healed,
            "fallback_mode": fallback
        }


