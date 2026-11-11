from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from eva_phase_common import (
    DOCUMENT_EXTENSIONS,
    PHASE_UPLOAD_DIR,
    connect_phase_db,
    new_id,
    now_iso,
    read_validated_upload,
    row_to_dict,
    rows_to_dicts,
)
from training.chunker import chunk_text
from training.data_cleaner import clean_text
from training.data_collector import collect_upload_text, collect_url_text
from training.embedding_builder import build_embedding_records
from training.feedback_collector import record_feedback
from training.fine_tune_exporter import examples_to_jsonl


router = APIRouter(tags=["training"])

DOMAINS = ("General", "Mechanical Design", "Automotive", "Coding", "Business", "Custom")
TRAINING_METHODS = ("RAG only", "Fine-tuning dataset", "Both")


def init_domain_training_db():
    conn = connect_phase_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS domain_datasets (
            id TEXT PRIMARY KEY,
            user_id TEXT DEFAULT 'user_001',
            workspace_id TEXT DEFAULT 'default-org',
            name TEXT NOT NULL,
            domain TEXT NOT NULL,
            training_method TEXT NOT NULL,
            source_type TEXT DEFAULT 'upload',
            source_uri TEXT DEFAULT '',
            status TEXT NOT NULL,
            document_count INTEGER DEFAULT 0,
            chunk_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS domain_documents (
            id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_type TEXT NOT NULL,
            size_bytes INTEGER DEFAULT 0,
            content TEXT DEFAULT '',
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS domain_chunks (
            id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            chunk_index INTEGER DEFAULT 0,
            content TEXT NOT NULL,
            embedding_status TEXT DEFAULT 'placeholder',
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fine_tune_examples (
            id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL,
            prompt TEXT NOT NULL,
            completion TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def _dataset(dataset_id: str):
    init_domain_training_db()
    conn = connect_phase_db()
    row = row_to_dict(conn.execute("SELECT * FROM domain_datasets WHERE id = ?", (dataset_id,)).fetchone())
    conn.close()
    return row


@router.post("/training/domain/upload")
async def upload_domain_dataset(
    file: UploadFile = File(...),
    domain: str = Form("General"),
    training_method: str = Form("RAG only"),
    user_id: str = Form("user_001"),
    workspace_id: str = Form("default-org"),
):
    if domain not in DOMAINS:
        raise HTTPException(status_code=400, detail="Invalid domain")
    if training_method not in TRAINING_METHODS:
        raise HTTPException(status_code=400, detail="Invalid training method")
    data, suffix = await read_validated_upload(file, DOCUMENT_EXTENSIONS)
    dataset_id = new_id("dataset")
    document_id = new_id("doc")
    safe_name = Path(file.filename or f"dataset{suffix}").name
    text = clean_text(collect_upload_text(data, suffix))
    target = PHASE_UPLOAD_DIR / f"{dataset_id}_{safe_name}"
    target.write_bytes(data)
    now = now_iso()
    init_domain_training_db()
    conn = connect_phase_db()
    conn.execute("""
        INSERT INTO domain_datasets (
            id, user_id, workspace_id, name, domain, training_method, source_type, source_uri,
            status, document_count, chunk_count, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 'upload', ?, 'Uploaded', 1, 0, ?, ?)
    """, (dataset_id, user_id, workspace_id, safe_name, domain, training_method, str(target), now, now))
    conn.execute("""
        INSERT INTO domain_documents (
            id, dataset_id, file_name, file_type, size_bytes, content, status, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 'Uploaded', ?)
    """, (document_id, dataset_id, safe_name, suffix, len(data), text, now))
    conn.commit()
    row = row_to_dict(conn.execute("SELECT * FROM domain_datasets WHERE id = ?", (dataset_id,)).fetchone())
    conn.close()
    return {"ok": True, "dataset": row}


@router.post("/training/domain/url")
def add_domain_url(payload: Dict[str, Any]):
    domain = payload.get("domain", "General")
    training_method = payload.get("training_method", "RAG only")
    if domain not in DOMAINS:
        raise HTTPException(status_code=400, detail="Invalid domain")
    if training_method not in TRAINING_METHODS:
        raise HTTPException(status_code=400, detail="Invalid training method")
    url = (payload.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Website URL must start with http:// or https://")
    init_domain_training_db()
    dataset_id = new_id("dataset")
    document_id = new_id("doc")
    text = clean_text(collect_url_text(url))
    now = now_iso()
    conn = connect_phase_db()
    conn.execute("""
        INSERT INTO domain_datasets (
            id, user_id, workspace_id, name, domain, training_method, source_type, source_uri,
            status, document_count, chunk_count, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 'website', ?, 'Uploaded', 1, 0, ?, ?)
    """, (dataset_id, payload.get("user_id", "user_001"), payload.get("workspace_id", "default-org"), url, domain, training_method, url, now, now))
    conn.execute("""
        INSERT INTO domain_documents (
            id, dataset_id, file_name, file_type, size_bytes, content, status, created_at
        )
        VALUES (?, ?, ?, '.url', ?, ?, 'Uploaded', ?)
    """, (document_id, dataset_id, url, len(text.encode("utf-8")), text, now))
    conn.commit()
    row = row_to_dict(conn.execute("SELECT * FROM domain_datasets WHERE id = ?", (dataset_id,)).fetchone())
    conn.close()
    return {"ok": True, "dataset": row}


@router.get("/training/domain/datasets")
def list_domain_datasets(workspace_id: str = "default-org"):
    init_domain_training_db()
    conn = connect_phase_db()
    datasets = rows_to_dicts(conn.execute("""
        SELECT * FROM domain_datasets
        WHERE workspace_id = ?
        ORDER BY created_at DESC
    """, (workspace_id,)).fetchall())
    for dataset in datasets:
        dataset["documents"] = rows_to_dicts(conn.execute("""
            SELECT id, file_name, file_type, size_bytes, status, created_at
            FROM domain_documents
            WHERE dataset_id = ?
            ORDER BY created_at DESC
        """, (dataset["id"],)).fetchall())
    conn.close()
    return {"ok": True, "datasets": datasets, "domains": list(DOMAINS), "training_methods": list(TRAINING_METHODS)}


@router.post("/training/domain/process")
def process_domain_dataset(payload: Dict[str, Any]):
    dataset_id = payload.get("dataset_id")
    dataset = _dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    chunk_size = int(payload.get("chunk_size") or 900)
    chunk_overlap = int(payload.get("chunk_overlap") or 120)
    conn = connect_phase_db()
    now = now_iso()
    conn.execute("UPDATE domain_datasets SET status = 'Processing', updated_at = ? WHERE id = ?", (now, dataset_id))
    conn.execute("DELETE FROM domain_chunks WHERE dataset_id = ?", (dataset_id,))
    docs = rows_to_dicts(conn.execute("SELECT * FROM domain_documents WHERE dataset_id = ?", (dataset_id,)).fetchall())
    chunk_count = 0
    for doc in docs:
        chunks = chunk_text(doc.get("content", ""), chunk_size, chunk_overlap)
        records = build_embedding_records(chunks)
        for record in records:
            conn.execute("""
                INSERT INTO domain_chunks (id, dataset_id, document_id, chunk_index, content, embedding_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (new_id("chunk"), dataset_id, doc["id"], record["chunk_index"], chunks[record["chunk_index"]], record["embedding_status"], now))
            chunk_count += 1
        if dataset.get("training_method") in ("Fine-tuning dataset", "Both") and chunks:
            conn.execute("""
                INSERT INTO fine_tune_examples (id, dataset_id, prompt, completion, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (new_id("ft"), dataset_id, f"Summarize domain knowledge from {doc['file_name']}", chunks[0][:1000], now))
    conn.execute("""
        UPDATE domain_datasets
        SET status = 'Indexed', chunk_count = ?, updated_at = ?
        WHERE id = ?
    """, (chunk_count, now, dataset_id))
    conn.commit()
    row = row_to_dict(conn.execute("SELECT * FROM domain_datasets WHERE id = ?", (dataset_id,)).fetchone())
    conn.close()
    return {"ok": True, "dataset": row}


@router.post("/training/domain/rebuild-index")
def rebuild_domain_index(payload: Optional[Dict[str, Any]] = None):
    init_domain_training_db()
    conn = connect_phase_db()
    now = now_iso()
    conn.execute("UPDATE domain_datasets SET status = 'Processing', updated_at = ?", (now,))
    conn.execute("UPDATE domain_datasets SET status = 'Indexed', updated_at = ?", (now_iso(),))
    conn.commit()
    count = conn.execute("SELECT COUNT(*) AS count FROM domain_datasets").fetchone()["count"]
    conn.close()
    return {"ok": True, "message": "Domain index rebuild placeholder completed.", "datasets": count}


@router.get("/training/domain/export-jsonl")
def export_domain_jsonl(dataset_id: Optional[str] = None):
    init_domain_training_db()
    conn = connect_phase_db()
    if dataset_id:
        rows = rows_to_dicts(conn.execute("SELECT * FROM fine_tune_examples WHERE dataset_id = ?", (dataset_id,)).fetchall())
    else:
        rows = rows_to_dicts(conn.execute("SELECT * FROM fine_tune_examples ORDER BY created_at DESC").fetchall())
    conn.close()
    content = examples_to_jsonl(rows)
    return StreamingResponse(iter([content]), media_type="application/jsonl", headers={"Content-Disposition": "attachment; filename=eva-domain-training.jsonl"})


@router.delete("/training/domain/dataset/{dataset_id}")
def delete_domain_dataset(dataset_id: str):
    dataset = _dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    conn = connect_phase_db()
    for table in ("domain_chunks", "domain_documents", "fine_tune_examples"):
        conn.execute(f"DELETE FROM {table} WHERE dataset_id = ?", (dataset_id,))
    conn.execute("DELETE FROM domain_datasets WHERE id = ?", (dataset_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "deleted": dataset_id}


@router.post("/training/feedback")
def training_feedback(payload: Dict[str, Any]):
    item = record_feedback(payload)
    return {"ok": True, "feedback": item}
