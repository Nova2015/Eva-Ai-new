import math
import re
from collections import Counter
from typing import Any, Dict, Iterable, List


TOKEN_RE = re.compile(r"[a-zA-Z0-9_\u0900-\u097F]+")


def tokenize(text: str) -> List[str]:
    return [token.lower() for token in TOKEN_RE.findall(text or "") if len(token) > 1]


class BM25Retriever:
    def __init__(self, chunks: Iterable[Dict[str, Any]], k1: float = 1.5, b: float = 0.75):
        self.chunks = list(chunks or [])
        self.k1 = k1
        self.b = b
        self.doc_tokens = [tokenize(chunk.get("text", "")) for chunk in self.chunks]
        self.doc_lengths = [len(tokens) for tokens in self.doc_tokens]
        self.avgdl = sum(self.doc_lengths) / len(self.doc_lengths) if self.doc_lengths else 1.0
        self.term_freqs = [Counter(tokens) for tokens in self.doc_tokens]
        self.idf = self._build_idf()

    def _build_idf(self) -> Dict[str, float]:
        doc_count = len(self.doc_tokens)
        if doc_count == 0:
            return {}
        dfs: Counter[str] = Counter()
        for tokens in self.doc_tokens:
            dfs.update(set(tokens))
        return {
            term: math.log(1 + (doc_count - df + 0.5) / (df + 0.5))
            for term, df in dfs.items()
        }

    def score(self, query: str, index: int) -> float:
        if index >= len(self.chunks):
            return 0.0
        tokens = tokenize(query)
        if not tokens:
            return 0.0
        tf = self.term_freqs[index]
        dl = self.doc_lengths[index] or 1
        score = 0.0
        for term in tokens:
            if term not in tf:
                continue
            idf = self.idf.get(term, 0.0)
            freq = tf[term]
            denom = freq + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
            score += idf * (freq * (self.k1 + 1)) / denom
        return score

    def search(self, query: str, top_k: int = 8) -> List[Dict[str, Any]]:
        scored = []
        for index, chunk in enumerate(self.chunks):
            raw_score = self.score(query, index)
            if raw_score <= 0:
                continue
            scored.append({
                **chunk,
                "bm25_score": raw_score,
                "retrieval_channels": sorted(set(chunk.get("retrieval_channels", []) + ["bm25"])),
            })
        if not scored:
            return []
        max_score = max(item["bm25_score"] for item in scored) or 1.0
        for item in scored:
            item["keyword_score"] = min(1.0, item["bm25_score"] / max_score)
        return sorted(scored, key=lambda item: item["keyword_score"], reverse=True)[:max(1, top_k)]
