import hashlib
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List

try:
    from .bm25_retriever import tokenize
except ImportError:
    try:
        from bm25_retriever import tokenize
    except ImportError:
        def tokenize(text: str):
            return [token.lower() for token in (text or "").split() if len(token) > 1]


PROMPT_INJECTION_PATTERNS = (
    re.compile(r"\bignore (all )?(previous|prior|system|developer) instructions\b", re.I),
    re.compile(r"\bdisregard (all )?(previous|prior|system|developer) instructions\b", re.I),
    re.compile(r"\breveal (the )?(system prompt|developer message|hidden prompt|api key|secret)\b", re.I),
    re.compile(r"\byou are now\b", re.I),
    re.compile(r"\bact as\b", re.I),
)


def source_id(metadata: Dict[str, Any]) -> str:
    raw_source = str(metadata.get("filename") or metadata.get("source") or "unknown")
    source = Path(raw_source).name if raw_source != "unknown" else raw_source
    page = metadata.get("page")
    chunk = metadata.get("chunk") or metadata.get("chunk_id")
    suffix = []
    if page not in (None, ""):
        suffix.append(f"p{page}")
    if chunk not in (None, ""):
        suffix.append(f"c{chunk}")
    return "#".join([source] + suffix)


def content_fingerprint(text: str) -> str:
    normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
    return hashlib.sha1(normalized.encode("utf-8", errors="ignore")).hexdigest()


def sanitize_retrieved_content(text: str) -> str:
    safe_lines = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if any(pattern.search(stripped) for pattern in PROMPT_INJECTION_PATTERNS):
            continue
        safe_lines.append(line)
    return "\n".join(safe_lines).strip()


def chunk_quality_score(text: str, metadata: Dict[str, Any] | None = None) -> float:
    value = (text or "").strip()
    if not value:
        return 0.0
    metadata = metadata or {}
    length_score = min(1.0, len(value) / 900)
    token_count = len(tokenize(value))
    density = min(1.0, token_count / 120)
    unique_ratio = len(set(tokenize(value))) / max(1, token_count)
    noise_penalty = 0.2 if len(re.findall(r"[\x00-\x08\x0b-\x1f]", value)) else 0.0
    hidden_penalty = 0.4 if metadata.get("hidden") or metadata.get("private") else 0.0
    return round(max(0.0, min(1.0, 0.34 * length_score + 0.36 * density + 0.30 * unique_ratio - noise_penalty - hidden_penalty)), 3)


def citation_score(query: str, text: str, metadata: Dict[str, Any] | None = None) -> float:
    q_terms = set(tokenize(query))
    t_terms = set(tokenize(text))
    overlap = len(q_terms & t_terms) / max(1, len(q_terms))
    quality = chunk_quality_score(text, metadata)
    source_bonus = 0.08 if source_id(metadata or {}) != "unknown" else 0.0
    return round(max(0.0, min(1.0, 0.58 * overlap + 0.34 * quality + source_bonus)), 3)


def source_confidence(result: Dict[str, Any]) -> float:
    vector = float(result.get("vector_score", 0) or 0)
    keyword = float(result.get("keyword_score", 0) or 0)
    rerank = float(result.get("rerank_score", 0) or 0)
    citation = float(result.get("citation_score", 0) or 0)
    quality = float(result.get("chunk_quality", 0) or 0)
    score = 0.24 * vector + 0.22 * keyword + 0.20 * rerank + 0.22 * citation + 0.12 * quality
    return round(max(0.0, min(1.0, score)), 3)


def remove_duplicate_chunks(chunks: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    unique = []
    for chunk in chunks:
        text = chunk.get("text", "")
        fp = chunk.get("fingerprint") or content_fingerprint(text)
        if fp in seen:
            continue
        seen.add(fp)
        unique.append({**chunk, "fingerprint": fp})
    return unique
