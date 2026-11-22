import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.getenv("EVA_AGENT_DB", ROOT_DIR / "agent_os.db"))


AGENT_TYPES = {
    "repo": {"name": "Repo Agent", "status": "ready"},
    "deployment": {"name": "Deployment Agent", "status": "warning"},
    "security": {"name": "Security Agent", "status": "ready"},
    "memory": {"name": "Memory Agent", "status": "ready"},
    "report": {"name": "Report Agent", "status": "ready"},
}


def now_iso():
    return datetime.utcnow().isoformat()


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_agent_db():
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_tasks (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            agent_type TEXT NOT NULL,
            title TEXT NOT NULL,
            instruction TEXT NOT NULL,
            payload TEXT DEFAULT '{}',
            priority INTEGER DEFAULT 3,
            status TEXT NOT NULL,
            result TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            scheduled_for TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_history (
            id TEXT PRIMARY KEY,
            task_id TEXT,
            user_id TEXT NOT NULL,
            agent_type TEXT NOT NULL,
            event TEXT NOT NULL,
            details TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_schedules (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            agent_type TEXT NOT NULL,
            cron_label TEXT NOT NULL,
            instruction TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            last_run TEXT,
            next_run TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_tasks_user_status ON agent_tasks(user_id, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_history_user_created ON agent_history(user_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_schedules_user_enabled ON agent_schedules(user_id, enabled)")
    conn.commit()
    conn.close()


def _row_to_dict(row):
    if not row:
        return None
    return dict(row)


def create_task(user_id, agent_type, title, instruction, payload="{}", priority=3, scheduled_for=None):
    init_agent_db()
    task_id = uuid.uuid4().hex
    created = now_iso()
    title = title or AGENT_TYPES.get(agent_type, {}).get("name", "Agent Task")
    conn = _connect()
    conn.execute("""
        INSERT INTO agent_tasks (
            id, user_id, agent_type, title, instruction, payload, priority,
            status, result, created_at, updated_at, scheduled_for
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        task_id, user_id, agent_type, title, instruction, payload,
        max(1, min(int(priority or 3), 5)), "running", "", created, created, scheduled_for,
    ))
    conn.commit()
    row = conn.execute("SELECT * FROM agent_tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    add_history(task_id, user_id, agent_type, "created", f"Task created: {title}")
    return _row_to_dict(row)


def update_task(task_id, status=None, result=None):
    init_agent_db()
    updates = ["updated_at = ?"]
    params = [now_iso()]
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if result is not None:
        updates.append("result = ?")
        params.append(result)
    params.append(task_id)
    conn = _connect()
    conn.execute(f"UPDATE agent_tasks SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    row = conn.execute("SELECT * FROM agent_tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return _row_to_dict(row)


def add_history(task_id, user_id, agent_type, event, details=""):
    init_agent_db()
    history_id = uuid.uuid4().hex
    conn = _connect()
    conn.execute("""
        INSERT INTO agent_history (id, task_id, user_id, agent_type, event, details, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (history_id, task_id, user_id, agent_type, event, details, now_iso()))
    conn.commit()
    row = conn.execute("SELECT * FROM agent_history WHERE id = ?", (history_id,)).fetchone()
    conn.close()
    return _row_to_dict(row)


def list_tasks(user_id="user_001", status="", limit=100):
    init_agent_db()
    clauses = ["user_id = ?"]
    params = [user_id]
    if status:
        clauses.append("status = ?")
        params.append(status)
    params.append(limit)
    conn = _connect()
    rows = [dict(row) for row in conn.execute(f"""
        SELECT * FROM agent_tasks
        WHERE {' AND '.join(clauses)}
        ORDER BY created_at DESC
        LIMIT ?
    """, params).fetchall()]
    conn.close()
    return rows


def list_history(user_id="user_001", limit=100):
    init_agent_db()
    conn = _connect()
    rows = [dict(row) for row in conn.execute("""
        SELECT * FROM agent_history
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ?
    """, (user_id, limit)).fetchall()]
    conn.close()
    return rows


def list_schedules(user_id="user_001"):
    init_agent_db()
    conn = _connect()
    rows = [dict(row) for row in conn.execute("""
        SELECT * FROM agent_schedules
        WHERE user_id = ?
        ORDER BY created_at ASC
    """, (user_id,)).fetchall()]
    conn.close()
    return rows


def create_schedule(user_id, name, agent_type, cron_label, instruction, enabled=True, next_run=""):
    init_agent_db()
    schedule_id = uuid.uuid4().hex
    conn = _connect()
    conn.execute("""
        INSERT INTO agent_schedules (
            id, user_id, name, agent_type, cron_label, instruction,
            enabled, last_run, next_run, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        schedule_id, user_id, name, agent_type, cron_label, instruction,
        1 if enabled else 0, "", next_run, now_iso(),
    ))
    conn.commit()
    row = conn.execute("SELECT * FROM agent_schedules WHERE id = ?", (schedule_id,)).fetchone()
    conn.close()
    add_history(schedule_id, user_id, agent_type, "scheduled", f"{name} - {cron_label}")
    return _row_to_dict(row)


def dashboard_snapshot(user_id="user_001"):
    init_agent_db()
    tasks = list_tasks(user_id, limit=30)
    schedules = list_schedules(user_id)
    counts = {
        "running": len([task for task in tasks if task["status"] == "running"]),
        "completed": len([task for task in tasks if task["status"] == "completed"]),
        "failed": len([task for task in tasks if task["status"] == "failed"]),
        "scheduled": len([schedule for schedule in schedules if schedule["enabled"]]),
    }
    agents = []
    for agent_type, meta in AGENT_TYPES.items():
        recent = next((task for task in tasks if task["agent_type"] == agent_type), None)
        status = meta["status"]
        if recent and recent["status"] == "failed":
            status = "warning"
        elif recent and recent["status"] == "running":
            status = "running"
        agents.append({
            "id": agent_type,
            "name": meta["name"],
            "status": status,
            "last_task": recent["title"] if recent else "",
        })
    return {
        "agents": agents,
        "counts": counts,
        "running_agents": len([agent for agent in agents if agent["status"] in ("ready", "running")]),
        "recent_tasks": tasks[:8],
        "schedules": schedules,
    }
