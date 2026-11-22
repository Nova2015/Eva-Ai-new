import json
import os
import shutil
import sqlite3
import uuid
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

try:
    import psutil
except Exception:
    psutil = None


ROOT_DIR = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.getenv("EVA_ANALYTICS_DB", ROOT_DIR / "analytics.db"))
DATA_DIR = ROOT_DIR / "data"
GENERATED_DIR = ROOT_DIR / "generated"


def now_iso():
    return datetime.utcnow().isoformat()


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _rows(rows):
    return [dict(row) for row in rows]


def _parse_metadata(value):
    try:
        if not value:
            return {}
        if isinstance(value, dict):
            return value
        return json.loads(value)
    except Exception:
        return {}


def init_analytics_db():
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS analytics_events (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            feature TEXT NOT NULL,
            action TEXT NOT NULL,
            model TEXT DEFAULT '',
            tokens INTEGER DEFAULT 0,
            cost REAL DEFAULT 0,
            status TEXT DEFAULT 'success',
            duration_ms INTEGER DEFAULT 0,
            metadata TEXT DEFAULT '{}',
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS error_logs (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            page TEXT DEFAULT '',
            error TEXT NOT NULL,
            stack_trace TEXT DEFAULT '',
            metadata TEXT DEFAULT '{}',
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_analytics_created ON analytics_events(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_analytics_user ON analytics_events(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_analytics_feature ON analytics_events(feature, action)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_errors_created ON error_logs(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_errors_page ON error_logs(page)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_errors_user ON error_logs(user_id)")
    conn.commit()
    conn.close()


def estimate_tokens(*parts):
    text = " ".join(str(part or "") for part in parts)
    return max(1, len(text.split()) * 2) if text.strip() else 0


def log_event(
    user_id="anonymous",
    feature="system",
    action="event",
    model="",
    tokens=0,
    cost=0,
    status="success",
    duration_ms=0,
    metadata=None,
):
    init_analytics_db()
    conn = _connect()
    conn.execute("""
        INSERT INTO analytics_events (
            id, user_id, feature, action, model, tokens, cost,
            status, duration_ms, metadata, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        uuid.uuid4().hex,
        str(user_id or "anonymous"),
        str(feature or "system"),
        str(action or "event"),
        str(model or ""),
        int(tokens or 0),
        float(cost or 0),
        str(status or "success"),
        int(duration_ms or 0),
        json.dumps(metadata or {}, ensure_ascii=False),
        now_iso(),
    ))
    conn.commit()
    conn.close()


def log_error(
    user_id="anonymous",
    page="",
    error="Unknown error",
    stack_trace="",
    metadata=None,
):
    init_analytics_db()
    conn = _connect()
    conn.execute("""
        INSERT INTO error_logs (
            id, user_id, page, error, stack_trace, metadata, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        uuid.uuid4().hex,
        str(user_id or "anonymous"),
        str(page or ""),
        str(error or "Unknown error")[:2000],
        str(stack_trace or "")[:8000],
        json.dumps(metadata or {}, ensure_ascii=False),
        now_iso(),
    ))
    conn.commit()
    conn.close()


def _count_table(db_path, table):
    path = Path(db_path)
    if not path.exists():
        return 0
    try:
        conn = sqlite3.connect(path)
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        conn.close()
        return int(row[0] or 0)
    except Exception:
        return 0


def _data_documents():
    if not DATA_DIR.exists():
        return []
    docs = []
    for path in DATA_DIR.iterdir():
        if path.is_file() and not path.name.endswith(".indexed"):
            stat = path.stat()
            docs.append({
                "name": path.name,
                "extension": path.suffix.lower().lstrip(".") or "no extension",
                "size": stat.st_size,
                "updated_at": datetime.utcfromtimestamp(stat.st_mtime).isoformat(),
            })
    return sorted(docs, key=lambda item: item["size"], reverse=True)


def _document_types(docs):
    counts = Counter(doc.get("extension") or "no extension" for doc in docs)
    return [
        {"type": name, "count": count}
        for name, count in counts.most_common(10)
    ]


def _generated_size():
    if not GENERATED_DIR.exists():
        return 0
    total = 0
    for path in GENERATED_DIR.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return total


def _group_by_day(conn, days=14):
    start = (datetime.utcnow() - timedelta(days=days - 1)).date().isoformat()
    raw = {
        row["day"]: dict(row)
        for row in conn.execute("""
            SELECT substr(created_at, 1, 10) AS day,
                   COUNT(*) AS events,
                   COALESCE(SUM(tokens), 0) AS tokens,
                   COALESCE(SUM(cost), 0) AS cost
            FROM analytics_events
            WHERE substr(created_at, 1, 10) >= ?
            GROUP BY substr(created_at, 1, 10)
            ORDER BY day ASC
        """, (start,)).fetchall()
    }
    days_out = []
    for index in range(days):
        day = (datetime.utcnow().date() - timedelta(days=days - 1 - index)).isoformat()
        item = raw.get(day) or {"day": day, "events": 0, "tokens": 0, "cost": 0}
        days_out.append(item)
    return days_out


def _status_from_percent(percent, warn=75, critical=90):
    if percent is None:
        return "unavailable"
    if percent >= critical:
        return "critical"
    if percent >= warn:
        return "warning"
    return "online"


def analytics_health(rag_ready=False):
    init_analytics_db()
    checked_at = now_iso()
    database_status = "online"
    database_error = ""
    try:
        conn = _connect()
        conn.execute("SELECT 1").fetchone()
        conn.close()
    except Exception as exc:
        database_status = "offline"
        database_error = str(exc)

    disk = shutil.disk_usage(ROOT_DIR)
    disk_percent = round(((disk.total - disk.free) / disk.total) * 100, 1) if disk.total else 0
    memory_percent = None
    memory_used = None
    memory_total = None
    process_memory = None
    cpu_percent = None

    if psutil is not None:
        try:
            cpu_percent = round(float(psutil.cpu_percent(interval=0.1)), 1)
            memory = psutil.virtual_memory()
            memory_percent = round(float(memory.percent), 1)
            memory_used = int(memory.used)
            memory_total = int(memory.total)
            process_memory = int(psutil.Process(os.getpid()).memory_info().rss)
        except Exception:
            cpu_percent = None
            memory_percent = None

    return {
        "backend": "online",
        "database": database_status,
        "database_error": database_error,
        "rag": bool(rag_ready),
        "checked_at": checked_at,
        "analytics_db": str(DB_PATH),
        "analytics_db_size": DB_PATH.stat().st_size if DB_PATH.exists() else 0,
        "cpu_usage": {
            "percent": cpu_percent,
            "status": _status_from_percent(cpu_percent),
        },
        "memory_usage": {
            "percent": memory_percent,
            "used_bytes": memory_used,
            "total_bytes": memory_total,
            "process_bytes": process_memory,
            "status": _status_from_percent(memory_percent),
        },
        "disk_usage": {
            "percent": disk_percent,
            "used_bytes": int(disk.total - disk.free),
            "free_bytes": int(disk.free),
            "total_bytes": int(disk.total),
            "status": _status_from_percent(disk_percent),
        },
        "paths": {
            "data_dir": str(DATA_DIR),
            "generated_dir": str(GENERATED_DIR),
            "root_dir": str(ROOT_DIR),
        },
    }


def _run_metrics():
    runs_db = Path(os.getenv("EVA_RUNS_DB", ROOT_DIR / "runs.db"))
    if not runs_db.exists():
        return {
            "total_runs": 0,
            "running_runs": 0,
            "completed_runs": 0,
            "failed_runs": 0,
            "cancelled_runs": 0,
            "avg_duration_ms": 0,
            "success_rate": 0,
            "failure_rate": 0,
        }
    try:
        conn = sqlite3.connect(runs_db)
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute("""
            SELECT
                COUNT(*) AS total_runs,
                COALESCE(SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END), 0) AS running_runs,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END), 0) AS completed_runs,
                COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0) AS failed_runs,
                COALESCE(SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END), 0) AS cancelled_runs,
                COALESCE(AVG(CASE WHEN status IN ('completed','failed','cancelled') THEN duration_ms END), 0) AS avg_duration_ms
            FROM runs
        """).fetchone())
        conn.close()
        total = int(row.get("total_runs") or 0)
        completed = int(row.get("completed_runs") or 0)
        failed = int(row.get("failed_runs") or 0)
        row["success_rate"] = round((completed / total) * 100, 1) if total else 0
        row["failure_rate"] = round((failed / total) * 100, 1) if total else 0
        row["avg_duration_ms"] = round(float(row.get("avg_duration_ms") or 0), 1)
        return row
    except Exception:
        return {
            "total_runs": 0,
            "running_runs": 0,
            "completed_runs": 0,
            "failed_runs": 0,
            "cancelled_runs": 0,
            "avg_duration_ms": 0,
            "success_rate": 0,
            "failure_rate": 0,
        }


def analytics_dashboard(rag_ready=False):
    init_analytics_db()
    conn = _connect()
    docs = _data_documents()
    total_events = conn.execute("SELECT COUNT(*) AS count FROM analytics_events").fetchone()["count"]
    total_users = conn.execute("SELECT COUNT(DISTINCT user_id) AS count FROM analytics_events").fetchone()["count"]
    active_start = (datetime.utcnow() - timedelta(days=7)).isoformat()
    active_users = conn.execute("""
        SELECT COUNT(DISTINCT user_id) AS count
        FROM analytics_events
        WHERE created_at >= ?
    """, (active_start,)).fetchone()["count"]
    totals = conn.execute("""
        SELECT COALESCE(SUM(tokens), 0) AS tokens,
               COALESCE(SUM(cost), 0) AS cost,
               COALESCE(AVG(duration_ms), 0) AS avg_duration_ms
        FROM analytics_events
    """).fetchone()
    total_chats = conn.execute("""
        SELECT COUNT(*) AS count
        FROM analytics_events
        WHERE feature = 'chat' AND action IN ('message', 'vision_message')
    """).fetchone()["count"]
    code_reviews_run = conn.execute("""
        SELECT COUNT(*) AS count
        FROM analytics_events
        WHERE feature = 'code'
    """).fetchone()["count"]
    vision_requests = conn.execute("""
        SELECT COUNT(*) AS count
        FROM analytics_events
        WHERE feature = 'vision' OR (feature = 'chat' AND action = 'vision_message')
    """).fetchone()["count"]
    security_scans = conn.execute("""
        SELECT COUNT(*) AS count
        FROM analytics_events
        WHERE feature = 'security'
    """).fetchone()["count"]
    agent_tasks = conn.execute("""
        SELECT COUNT(*) AS count
        FROM analytics_events
        WHERE feature = 'agents' AND action = 'task_created'
    """).fetchone()["count"]
    api_failures = conn.execute("""
        SELECT COUNT(*) AS count
        FROM analytics_events
        WHERE status != 'success'
    """).fetchone()["count"]
    total_errors = conn.execute("SELECT COUNT(*) AS count FROM error_logs").fetchone()["count"]
    feature_usage = _rows(conn.execute("""
        SELECT feature, COUNT(*) AS events, COALESCE(SUM(tokens), 0) AS tokens
        FROM analytics_events
        GROUP BY feature
        ORDER BY events DESC
        LIMIT 10
    """).fetchall())
    model_usage = _rows(conn.execute("""
        SELECT COALESCE(NULLIF(model, ''), 'unknown') AS model,
               COUNT(*) AS calls,
               COALESCE(SUM(tokens), 0) AS tokens,
               COALESCE(SUM(cost), 0) AS cost
        FROM analytics_events
        GROUP BY COALESCE(NULLIF(model, ''), 'unknown')
        ORDER BY calls DESC
        LIMIT 8
    """).fetchall())
    top_users = _rows(conn.execute("""
        SELECT user_id, COUNT(*) AS events, COALESCE(SUM(tokens), 0) AS tokens
        FROM analytics_events
        GROUP BY user_id
        ORDER BY events DESC
        LIMIT 8
    """).fetchall())
    users = _rows(conn.execute("""
        SELECT user_id,
               COUNT(*) AS events,
               COALESCE(SUM(tokens), 0) AS tokens,
               COALESCE(SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END), 0) AS failures,
               MAX(created_at) AS last_seen
        FROM analytics_events
        GROUP BY user_id
        ORDER BY events DESC
        LIMIT 25
    """).fetchall())
    recent_chats = _rows(conn.execute("""
        SELECT user_id, action, model, tokens, duration_ms, status, created_at
        FROM analytics_events
        WHERE feature = 'chat'
        ORDER BY created_at DESC
        LIMIT 25
    """).fetchall())
    recent_failures = _rows(conn.execute("""
        SELECT user_id, feature, action, status, metadata, created_at
        FROM analytics_events
        WHERE status != 'success'
        ORDER BY created_at DESC
        LIMIT 10
    """).fetchall())
    recent_errors = _rows(conn.execute("""
        SELECT id, user_id, page, error, stack_trace, metadata, created_at
        FROM error_logs
        ORDER BY created_at DESC
        LIMIT 25
    """).fetchall())
    errors_by_page = _rows(conn.execute("""
        SELECT COALESCE(NULLIF(page, ''), 'unknown') AS page, COUNT(*) AS count
        FROM error_logs
        GROUP BY COALESCE(NULLIF(page, ''), 'unknown')
        ORDER BY count DESC
        LIMIT 10
    """).fetchall())
    agent_rows = _rows(conn.execute("""
        SELECT action, metadata, status, created_at
        FROM analytics_events
        WHERE feature = 'agents'
        ORDER BY created_at DESC
        LIMIT 200
    """).fetchall())
    chat_topic_rows = _rows(conn.execute("""
        SELECT action, metadata
        FROM analytics_events
        WHERE feature = 'chat'
        ORDER BY created_at DESC
        LIMIT 200
    """).fetchall())
    daily_usage = _group_by_day(conn, days=14)
    conn.close()

    agent_counter = Counter()
    for row in agent_rows:
        meta = _parse_metadata(row.get("metadata"))
        agent_counter[meta.get("agent_type") or meta.get("agent") or row.get("action") or "agent"] += 1
    agent_usage = [{"agent": name, "events": count} for name, count in agent_counter.most_common(10)]

    topic_counter = Counter()
    for row in chat_topic_rows:
        meta = _parse_metadata(row.get("metadata"))
        topic = meta.get("topic") or meta.get("intent")
        if not topic:
            topic = "Vision requests" if row.get("action") == "vision_message" else "Chat questions"
        topic_counter[topic] += 1
    topic_usage = [{"topic": name, "count": count} for name, count in topic_counter.most_common(10)]

    document_types = _document_types(docs)
    memory_db = ROOT_DIR / "memory.db"
    agent_db = ROOT_DIR / "agent_os.db"
    team_db = ROOT_DIR / "team_workspace.db"
    most_active_user = top_users[0]["user_id"] if top_users else "No data yet"
    most_used_agent = agent_usage[0]["agent"] if agent_usage else "No data yet"
    most_asked_topic = topic_usage[0]["topic"] if topic_usage else "No data yet"
    most_uploaded_file_type = document_types[0]["type"] if document_types else "No data yet"
    run_metrics = _run_metrics()

    return {
        "summary": {
            "total_users": total_users,
            "active_users": active_users,
            "total_chats": total_chats,
            "documents_indexed": len(docs),
            "documents_uploaded": len(docs),
            "code_reviews_run": code_reviews_run,
            "vision_requests": vision_requests,
            "security_scans": security_scans,
            "tokens_used": int(totals["tokens"] or 0),
            "agent_tasks": max(agent_tasks, _count_table(agent_db, "agent_tasks")),
            "api_costs": round(float(totals["cost"] or 0), 4),
            "api_failures": api_failures,
            "total_errors": total_errors,
            "avg_duration_ms": round(float(totals["avg_duration_ms"] or 0), 1),
            "team_members": _count_table(team_db, "team_members"),
            "memory_rows": _count_table(memory_db, "memories"),
            "generated_storage_bytes": _generated_size(),
            "total_events": total_events,
            "run_count": int(run_metrics.get("total_runs") or 0),
            "run_avg_duration_ms": run_metrics.get("avg_duration_ms", 0),
            "run_success_rate": run_metrics.get("success_rate", 0),
            "run_failure_rate": run_metrics.get("failure_rate", 0),
        },
        "daily_usage": daily_usage,
        "model_usage": model_usage,
        "top_users": top_users,
        "users": users,
        "recent_chats": recent_chats,
        "top_documents": docs[:12],
        "document_types": document_types,
        "agent_usage": agent_usage,
        "topic_usage": topic_usage,
        "feature_usage": feature_usage,
        "recent_failures": recent_failures,
        "recent_errors": recent_errors,
        "errors_by_page": errors_by_page,
        "run_metrics": run_metrics,
        "usage_insights": {
            "most_used_agent": most_used_agent,
            "most_asked_topic": most_asked_topic,
            "most_uploaded_file_type": most_uploaded_file_type,
            "most_active_user": most_active_user,
        },
        "health": {
            "analytics_db": str(DB_PATH),
            "data_dir": str(DATA_DIR),
            "generated_dir": str(GENERATED_DIR),
        },
        "system_health": analytics_health(rag_ready=rag_ready),
    }
