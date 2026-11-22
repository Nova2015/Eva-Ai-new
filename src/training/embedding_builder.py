from typing import Iterable, List


def build_embedding_records(chunks: Iterable[str], provider: str = "Local") -> List[dict]:
    records = []
    for index, chunk in enumerate(chunks):
        records.append({
            "chunk_index": index,
            "provider": provider,
            "embedding_status": "placeholder",
            "embedding_dim": 0,
            "preview": chunk[:160],
        })
    return records
