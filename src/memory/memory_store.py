import os
import re
import sqlite3
from pathlib import Path
from datetime import datetime


DB_PATH = Path(os.getenv("EVA_MEMORY_DB", Path(__file__).resolve().parents[2] / "memory.db"))

MEMORY_TIERS = frozenset({"episodic", "semantic"})
VALIDATION_STATUSES = frozenset({
    "unvalidated",
    "user_confirmed",
    "system_verified",
    "superseded",
})

_VALIDATION_RANK = {
    "unvalidated": 0,
    "user_confirmed": 1,
    "system_verified": 2,
    "superseded": -1,
}

SENSITIVE_MEMORY_PATTERN = re.compile(
    r"(password|passcode|api[_\s-]?key|secret|private\s+key|access\s+token|bearer\s+|bank\s+account|credit\s+card|ssn|cvv)",
    re.IGNORECASE,
)


def _utc_now() -> str:
    return datetime.utcnow().isoformat()


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_memory_lifecycle_columns(conn):
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(memories)").fetchall()
    }
    additions = {
        "memory_tier": "TEXT NOT NULL DEFAULT 'episodic'",
        "confidence": "REAL NOT NULL DEFAULT 0.5",
        "provenance": "TEXT NOT NULL DEFAULT 'chat_auto'",
        "validation_status": "TEXT NOT NULL DEFAULT 'unvalidated'",
        "superseded_by": "INTEGER",
        "updated_at": "TEXT",
    }
    for name, definition in additions.items():
        if name not in columns:
            conn.execute(
                f"ALTER TABLE memories ADD COLUMN {name} {definition}"
            )


def _normalise_tier(memory_tier: str) -> str | None:
    tier = (memory_tier or "episodic").strip().lower()
    return tier if tier in MEMORY_TIERS else None


def _normalise_validation_status(status: str) -> str | None:
    value = (status or "unvalidated").strip().lower()
    return value if value in VALIDATION_STATUSES else None


def _normalise_confidence(confidence) -> float:
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        value = 0.5
    return max(0.0, min(value, 1.0))


def _normalise_importance(importance) -> int:
    try:
        value = int(importance or 1)
    except (TypeError, ValueError):
        value = 1
    return max(1, min(value, 5))


def _lifecycle_values(memory_tier, confidence, provenance, validation_status):
    tier = _normalise_tier(memory_tier)
    status = _normalise_validation_status(validation_status)

    if tier is None or status is None:
        return None

    # Semantic memory must have an explicit validation state.
    if tier == "semantic" and status not in {"user_confirmed", "system_verified"}:
        return None

    return (
        tier,
        _normalise_confidence(confidence),
        str(provenance or "chat_auto").strip()[:120] or "chat_auto",
        status,
    )


def init_memory_db():
    conn = _connect()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT UNIQUE,
            role TEXT DEFAULT 'user',
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            title TEXT,
            message TEXT NOT NULL,
            response TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            memory_type TEXT NOT NULL,
            content TEXT NOT NULL,
            importance INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            memory_tier TEXT NOT NULL DEFAULT 'episodic',
            confidence REAL NOT NULL DEFAULT 0.5,
            provenance TEXT NOT NULL DEFAULT 'chat_auto',
            validation_status TEXT NOT NULL DEFAULT 'unvalidated',
            superseded_by INTEGER,
            updated_at TEXT
        )
    """)

    _ensure_memory_lifecycle_columns(conn)

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chats_user_created ON chats(user_id, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memories_user_type ON memories(user_id, memory_type)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memories_user_created ON memories(user_id, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memories_user_tier "
        "ON memories(user_id, memory_tier, validation_status)"
    )

    conn.commit()
    conn.close()


def upsert_user(user_id: str, name: str = "", email: str = "", role: str = "user"):
    init_memory_db()
    value = email or user_id

    conn = _connect()
    conn.execute("""
        INSERT INTO users (name, email, role, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(email) DO UPDATE SET
            name = COALESCE(NULLIF(excluded.name, ''), users.name),
            role = COALESCE(NULLIF(excluded.role, ''), users.role)
    """, (name or user_id, value, role or "user", _utc_now()))

    conn.commit()
    conn.close()


def save_chat(user_id: str, message: str, response: str, title: str = "Chat"):
    init_memory_db()

    conn = _connect()
    conn.execute("""
        INSERT INTO chats (user_id, title, message, response, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, title, message, response, _utc_now()))

    conn.commit()
    conn.close()


def save_memory(
    user_id: str,
    content: str,
    memory_type: str = "long_term",
    importance: int = 1,
    memory_tier: str = "episodic",
    confidence: float = 0.5,
    provenance: str = "chat_auto",
    validation_status: str = "unvalidated",
    superseded_by: int | None = None,
):
    init_memory_db()

    text = (content or "").strip()
    if not text or SENSITIVE_MEMORY_PATTERN.search(text):
        return None

    lifecycle = _lifecycle_values(
        memory_tier,
        confidence,
        provenance,
        validation_status,
    )
    if lifecycle is None:
        return None

    conn = _connect()

    existing_memory = conn.execute("""
        SELECT id, validation_status, memory_tier, confidence
        FROM memories
        WHERE user_id = ? AND memory_type = ? AND content = ?
    """, (user_id, memory_type, text)).fetchone()

    if existing_memory:
        new_tier, new_confidence, new_provenance, new_status = lifecycle
        old_status = existing_memory["validation_status"] or "unvalidated"

        if (
            _VALIDATION_RANK[new_status] > _VALIDATION_RANK.get(old_status, 0)
            or new_confidence > float(existing_memory["confidence"] or 0.0)
        ):
            conn.execute("""
                UPDATE memories
                SET memory_tier = ?,
                    confidence = ?,
                    provenance = ?,
                    validation_status = ?,
                    superseded_by = ?,
                    updated_at = ?
                WHERE id = ? AND user_id = ?
            """, (
                new_tier,
                new_confidence,
                new_provenance,
                new_status,
                superseded_by,
                _utc_now(),
                existing_memory["id"],
                user_id,
            ))
            conn.commit()

        conn.close()
        return existing_memory["id"]

    cur = conn.execute("""
        INSERT INTO memories (
            user_id,
            memory_type,
            content,
            importance,
            created_at,
            memory_tier,
            confidence,
            provenance,
            validation_status,
            superseded_by,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        memory_type,
        text,
        _normalise_importance(importance),
        _utc_now(),
        lifecycle[0],
        lifecycle[1],
        lifecycle[2],
        lifecycle[3],
        superseded_by,
        None,
    ))

    conn.commit()
    memory_id = cur.lastrowid
    conn.close()
    return memory_id


def validate_memory(
    user_id: str,
    memory_id: int,
    validation_status: str = "user_confirmed",
    confidence: float = 1.0,
) -> bool:
    status = _normalise_validation_status(validation_status)

    if status not in {"user_confirmed", "system_verified"}:
        return False

    init_memory_db()

    conn = _connect()
    cur = conn.execute("""
        UPDATE memories
        SET memory_tier = 'semantic',
            validation_status = ?,
            confidence = ?,
            updated_at = ?
        WHERE id = ?
          AND user_id = ?
          AND validation_status != 'superseded'
    """, (
        status,
        _normalise_confidence(confidence),
        _utc_now(),
        memory_id,
        user_id,
    ))

    conn.commit()
    updated = cur.rowcount > 0
    conn.close()
    return updated


def supersede_memory(
    user_id: str,
    memory_id: int,
    replacement_memory_id: int,
) -> bool:
    if int(memory_id) == int(replacement_memory_id):
        return False

    init_memory_db()

    conn = _connect()

    try:
        replacement = conn.execute("""
            SELECT memory_tier, validation_status
            FROM memories
            WHERE id = ?
              AND user_id = ?
        """, (
            replacement_memory_id,
            user_id,
        )).fetchone()

        # A validated semantic memory may only be replaced by another
        # validated semantic memory. Unvalidated episodic information
        # must never overwrite established knowledge.
        if not replacement:
            return False

        if replacement["memory_tier"] != "semantic":
            return False

        if replacement["validation_status"] not in {
            "user_confirmed",
            "system_verified",
        }:
            return False

        cur = conn.execute("""
            UPDATE memories
            SET validation_status = 'superseded',
                superseded_by = ?,
                updated_at = ?
            WHERE id = ?
              AND user_id = ?
              AND validation_status != 'superseded'
        """, (
            replacement_memory_id,
            _utc_now(),
            memory_id,
            user_id,
        ))

        conn.commit()
        return cur.rowcount > 0

    finally:
        conn.close()

def update_memory(
    user_id: str,
    memory_id: int,
    content: str = None,
    memory_type: str = None,
    importance: int = None,
    memory_tier: str = None,
    confidence: float = None,
    provenance: str = None,
    validation_status: str = None,
    superseded_by: int = None,
) -> bool:
    init_memory_db()

    fields = []
    params = []

    if content is not None:
        text = content.strip()
        if not text or SENSITIVE_MEMORY_PATTERN.search(text):
            return False
        fields.append("content = ?")
        params.append(text)

    if memory_type:
        fields.append("memory_type = ?")
        params.append(memory_type)

    if importance is not None:
        fields.append("importance = ?")
        params.append(_normalise_importance(importance))

    if memory_tier is not None:
        tier = _normalise_tier(memory_tier)
        if tier is None:
            return False
        fields.append("memory_tier = ?")
        params.append(tier)

    if confidence is not None:
        fields.append("confidence = ?")
        params.append(_normalise_confidence(confidence))

    if provenance is not None:
        value = str(provenance).strip()[:120]
        fields.append("provenance = ?")
        params.append(value or "chat_auto")

    if validation_status is not None:
        status = _normalise_validation_status(validation_status)
        if status is None:
            return False
        fields.append("validation_status = ?")
        params.append(status)

    if superseded_by is not None:
        fields.append("superseded_by = ?")
        params.append(superseded_by)

    if not fields:
        return False

    conn = _connect()

    try:
        row = conn.execute("""
            SELECT memory_tier, validation_status
            FROM memories
            WHERE id = ? AND user_id = ?
        """, (memory_id, user_id)).fetchone()

        if not row:
            return False

        resulting_tier = (
            _normalise_tier(memory_tier)
            if memory_tier is not None
            else (row["memory_tier"] or "episodic")
        )

        resulting_status = (
            _normalise_validation_status(validation_status)
            if validation_status is not None
            else (row["validation_status"] or "unvalidated")
        )

        if resulting_tier is None or resulting_status is None:
            return False

        if resulting_tier == "semantic" and resulting_status not in {
            "user_confirmed",
            "system_verified",
        }:
            return False

        fields.append("updated_at = ?")
        params.append(_utc_now())
        params.extend([memory_id, user_id])

        cur = conn.execute(
            f"UPDATE memories SET {', '.join(fields)} "
            "WHERE id = ? AND user_id = ?",
            params,
        )

        conn.commit()
        return cur.rowcount > 0

    finally:
        conn.close()


def list_memories(
    user_id: str,
    query: str = "",
    memory_type: str = "",
    limit: int = 100,
):
    init_memory_db()

    clauses = ["user_id = ?"]
    params = [user_id]

    if memory_type:
        clauses.append("memory_type = ?")
        params.append(memory_type)

    if query:
        clauses.append("content LIKE ?")
        params.append(f"%{query}%")

    sql = f"""
        SELECT
            id,
            user_id,
            memory_type,
            content,
            importance,
            created_at,
            memory_tier,
            confidence,
            provenance,
            validation_status,
            superseded_by,
            updated_at
        FROM memories
        WHERE {' AND '.join(clauses)}
        ORDER BY importance DESC, created_at DESC
        LIMIT ?
    """

    params.append(max(1, min(int(limit or 100), 1000)))

    conn = _connect()
    rows = [
        dict(row)
        for row in conn.execute(sql, params).fetchall()
    ]
    conn.close()
    return rows


def recent_chats(user_id: str, limit: int = 10):
    init_memory_db()

    conn = _connect()
    rows = [
        dict(row)
        for row in conn.execute("""
            SELECT id, user_id, title, message, response, created_at
            FROM chats
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
        """, (
            user_id,
            max(1, min(int(limit or 10), 1000)),
        )).fetchall()
    ]
    conn.close()
    return rows


def delete_memory(user_id: str, memory_id: int) -> bool:
    init_memory_db()

    conn = _connect()
    cur = conn.execute(
        "DELETE FROM memories WHERE id = ? AND user_id = ?",
        (memory_id, user_id),
    )
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


def forget_all_memories(user_id: str) -> dict:
    init_memory_db()

    conn = _connect()
    memory_cur = conn.execute(
        "DELETE FROM memories WHERE user_id = ?",
        (user_id,),
    )
    chat_cur = conn.execute(
        "DELETE FROM chats WHERE user_id = ?",
        (user_id,),
    )

    conn.commit()

    result = {
        "memories_deleted": memory_cur.rowcount,
        "chats_deleted": chat_cur.rowcount,
    }

    conn.close()
    return result


def export_memories(user_id: str) -> dict:
    return {
        "user_id": user_id,
        "memories": list_memories(user_id, limit=1000),
        "recent_chats": recent_chats(user_id, limit=100),
        "exported_at": _utc_now(),
    }