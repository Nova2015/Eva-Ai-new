import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


ROOT_DIR = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.getenv("EVA_RUNS_DB", ROOT_DIR / "runs.db"))
SCHEMA_VERSION = "2026_06_03_run_engine_v1"


def now_iso():
    return datetime.utcnow().isoformat()


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _dumps(value: Optional[Dict[str, Any]]):
    return json.dumps(value or {}, ensure_ascii=False)


def _loads(value, fallback=None):
    if fallback is None:
        fallback = {}
    try:
        if value is None:
            return fallback
        if isinstance(value, (dict, list)):
            return value
        return json.loads(value)
    except Exception:
        return fallback


def _row(row):
    if not row:
        return None
    item = dict(row)
    for key in ("payload", "result", "metadata", "data"):
        if key in item:
            item[key] = _loads(item.get(key), {})
    return item


def _rows(rows):
    return [_row(row) for row in rows]


def init_run_db():
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            organization_id TEXT DEFAULT 'default-org',
            source TEXT NOT NULL,
            run_type TEXT NOT NULL,
            title TEXT NOT NULL,
            instruction TEXT DEFAULT '',
            payload TEXT DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'queued',
            priority INTEGER DEFAULT 3,
            progress INTEGER DEFAULT 0,
            duration_ms INTEGER DEFAULT 0,
            error TEXT DEFAULT '',
            result TEXT DEFAULT '{}',
            metadata TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            cancelled_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS run_events (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            status TEXT NOT NULL,
            message TEXT NOT NULL,
            data TEXT DEFAULT '{}',
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_user_created ON runs(user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_status_created ON runs(status, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_source_type ON runs(source, run_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_run_events_run_created ON run_events(run_id, created_at)")
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        (SCHEMA_VERSION, now_iso()),
    )
    conn.commit()
    conn.close()


def create_run(
    user_id: str,
    source: str,
    run_type: str,
    title: str,
    organization_id: str = "default-org",
    instruction: str = "",
    payload: Optional[Dict[str, Any]] = None,
    priority: int = 3,
    metadata: Optional[Dict[str, Any]] = None,
):
    init_run_db()
    run_id = uuid.uuid4().hex
    created = now_iso()
    conn = _connect()
    conn.execute("""
        INSERT INTO runs (
            id, user_id, organization_id, source, run_type, title, instruction,
            payload, status, priority, progress, duration_ms, error, result,
            metadata, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, 0, 0, '', '{}', ?, ?, ?)
    """, (
        run_id,
        user_id or "anonymous",
        organization_id or "default-org",
        source or "manual",
        run_type or "workflow",
        title or "EVA Run",
        instruction or "",
        _dumps(payload),
        max(1, min(int(priority or 3), 5)),
        _dumps(metadata),
        created,
        created,
    ))
    conn.commit()
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    return _row(row)


def get_run(run_id: str):
    init_run_db()
    conn = _connect()
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    return _row(row)


def list_runs(
    user_id: str = "",
    organization_id: str = "",
    status: str = "",
    source: str = "",
    run_type: str = "",
    limit: int = 100,
):
    init_run_db()
    clauses = []
    params = []
    if user_id:
        clauses.append("user_id = ?")
        params.append(user_id)
    if organization_id:
        clauses.append("organization_id = ?")
        params.append(organization_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if source:
        clauses.append("source = ?")
        params.append(source)
    if run_type:
        clauses.append("run_type = ?")
        params.append(run_type)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(1, min(int(limit or 100), 500)))
    conn = _connect()
    rows = conn.execute(f"""
        SELECT * FROM runs
        {where}
        ORDER BY created_at DESC
        LIMIT ?
    """, params).fetchall()
    conn.close()
    return _rows(rows)


def add_event(run_id: str, event_type: str, status: str, message: str, data: Optional[Dict[str, Any]] = None):
    init_run_db()
    event_id = uuid.uuid4().hex
    created = now_iso()
    conn = _connect()
    conn.execute("""
        INSERT INTO run_events (id, run_id, event_type, status, message, data, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        event_id,
        run_id,
        event_type or "event",
        status or "running",
        message or "",
        _dumps(data),
        created,
    ))
    conn.commit()
    row = conn.execute("SELECT * FROM run_events WHERE id = ?", (event_id,)).fetchone()
    conn.close()
    return _row(row)


def list_events(run_id: str):
    init_run_db()
    conn = _connect()
    rows = conn.execute("""
        SELECT * FROM run_events
        WHERE run_id = ?
        ORDER BY created_at ASC
    """, (run_id,)).fetchall()
    conn.close()
    return _rows(rows)


def update_run(
    run_id: str,
    status: Optional[str] = None,
    progress: Optional[int] = None,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    started_at: Optional[str] = None,
    completed_at: Optional[str] = None,
    cancelled_at: Optional[str] = None,
):
    init_run_db()
    current = get_run(run_id)
    if not current:
        return None
    updates = ["updated_at = ?"]
    params = [now_iso()]
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if progress is not None:
        updates.append("progress = ?")
        params.append(max(0, min(int(progress), 100)))
    if result is not None:
        updates.append("result = ?")
        params.append(_dumps(result))
    if error is not None:
        updates.append("error = ?")
        params.append(str(error or "")[:4000])
    if started_at is not None:
        updates.append("started_at = COALESCE(started_at, ?)")
        params.append(started_at)
    if completed_at is not None:
        updates.append("completed_at = ?")
        params.append(completed_at)
    if cancelled_at is not None:
        updates.append("cancelled_at = ?")
        params.append(cancelled_at)

    finished_at = completed_at or cancelled_at
    if finished_at:
        start_value = current.get("started_at") or current.get("created_at") or finished_at
        try:
            start_dt = datetime.fromisoformat(start_value)
            end_dt = datetime.fromisoformat(finished_at)
            duration_ms = int((end_dt - start_dt).total_seconds() * 1000)
            updates.append("duration_ms = ?")
            params.append(max(duration_ms, 0))
        except Exception:
            pass

    params.append(run_id)
    conn = _connect()
    conn.execute(f"UPDATE runs SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    return _row(row)


def dashboard_metrics(user_id: str = ""):
    init_run_db()
    clauses = []
    params = []
    if user_id:
        clauses.append("user_id = ?")
        params.append(user_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = _connect()
    summary = _row(conn.execute(f"""
        SELECT
            COUNT(*) AS total_runs,
            COALESCE(SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END), 0) AS running_runs,
            COALESCE(SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END), 0) AS completed_runs,
            COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0) AS failed_runs,
            COALESCE(SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END), 0) AS cancelled_runs,
            COALESCE(AVG(CASE WHEN status IN ('completed','failed','cancelled') THEN duration_ms END), 0) AS avg_duration_ms
        FROM runs
        {where}
    """, params).fetchone())
    by_type = _rows(conn.execute(f"""
        SELECT run_type, COUNT(*) AS runs
        FROM runs
        {where}
        GROUP BY run_type
        ORDER BY runs DESC
        LIMIT 10
    """, params).fetchall())
    conn.close()
    total = int(summary.get("total_runs") or 0)
    completed = int(summary.get("completed_runs") or 0)
    failed = int(summary.get("failed_runs") or 0)
    summary["success_rate"] = round((completed / total) * 100, 1) if total else 0
    summary["failure_rate"] = round((failed / total) * 100, 1) if total else 0
    summary["avg_duration_ms"] = round(float(summary.get("avg_duration_ms") or 0), 1)
    return {"summary": summary, "by_type": by_type}
