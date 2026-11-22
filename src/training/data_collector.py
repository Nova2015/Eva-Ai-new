from eva_phase_common import decode_text


def collect_upload_text(data: bytes, suffix: str) -> str:
    if suffix in {".txt", ".csv", ".json", ".jsonl"}:
        return decode_text(data)
    return f"Binary document placeholder for {suffix}. Text extraction can be connected to the existing RAG parser."


def collect_url_text(url: str) -> str:
    url = (url or "").strip()
    return f"Website ingestion placeholder for {url}."
