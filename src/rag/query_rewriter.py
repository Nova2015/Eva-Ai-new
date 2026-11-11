import re
from typing import List

try:
    from .bm25_retriever import tokenize
except ImportError:
    try:
        from bm25_retriever import tokenize
    except ImportError:
        def tokenize(text: str):
            return [token.lower() for token in (text or "").split() if len(token) > 1]


QUESTION_PREFIXES = (
    "can you",
    "could you",
    "please",
    "tell me",
    "explain",
    "what is",
    "what are",
    "how do i",
    "how to",
)

SYNONYMS = {
    "price": ["cost", "pricing", "fee"],
    "cost": ["price", "pricing", "fee"],
    "error": ["issue", "failure", "exception"],
    "bug": ["issue", "defect", "failure"],
    "invoice": ["bill", "billing", "payment"],
    "security": ["policy", "risk", "compliance"],
    "rag": ["retrieval", "knowledge base", "documents"],
    "document": ["file", "source", "knowledge"],
    "summary": ["overview", "key points", "highlights"],
}


def rewrite_query(query: str) -> str:
    text = re.sub(r"\s+", " ", (query or "").strip())
    lowered = text.lower()
    for prefix in QUESTION_PREFIXES:
        if lowered.startswith(prefix + " "):
            text = text[len(prefix):].strip(" ?")
            break
    return text or (query or "").strip()


def keyword_query(query: str) -> str:
    tokens = tokenize(query)
    stop = {
        "what", "when", "where", "which", "with", "from", "that", "this", "these",
        "those", "about", "please", "show", "give", "tell", "does", "have",
    }
    return " ".join(token for token in tokens if token not in stop) or query


def expand_query(query: str, max_expansions: int = 4) -> List[str]:
    base = rewrite_query(query)
    candidates = [query, base, keyword_query(base)]
    tokens = tokenize(base)
    expansions = []
    for token in tokens:
        for synonym in SYNONYMS.get(token, []):
            expansions.append(f"{base} {synonym}")
    for item in expansions:
        if item not in candidates:
            candidates.append(item)
        if len(candidates) >= max_expansions:
            break
    return [item for item in candidates if item][:max_expansions]
