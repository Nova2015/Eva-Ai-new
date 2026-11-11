from typing import Any, Dict, List

try:
    from .bm25_retriever import tokenize
    from .citation_scorer import chunk_quality_score
except ImportError:
    try:
        from bm25_retriever import tokenize
    except ImportError:
        def tokenize(text: str):
            return [token.lower() for token in (text or "").split() if len(token) > 1]
    from citation_scorer import chunk_quality_score


class Reranker:
    def rerank(self, query: str, results: List[Dict[str, Any]], top_k: int = 8) -> List[Dict[str, Any]]:
        query_terms = set(tokenize(query))
        ranked = []
        for result in results:
            text_terms = set(tokenize(result.get("text", "")))
            overlap = len(query_terms & text_terms) / max(1, len(query_terms))
            vector = float(result.get("vector_score", 0) or 0)
            keyword = float(result.get("keyword_score", 0) or 0)
            quality = float(result.get("chunk_quality") or chunk_quality_score(result.get("text", ""), result.get("metadata", {})))
            channel_bonus = 0.08 if {"vector", "bm25"}.issubset(set(result.get("retrieval_channels", []))) else 0.0
            score = min(1.0, 0.42 * overlap + 0.22 * vector + 0.22 * keyword + 0.14 * quality + channel_bonus)
            ranked.append({**result, "rerank_score": round(score, 3)})
        return sorted(ranked, key=lambda item: item.get("rerank_score", 0), reverse=True)[:max(1, top_k)]
