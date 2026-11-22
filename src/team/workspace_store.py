import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.getenv("EVA_TEAM_DB", ROOT_DIR / "team_workspace.db"))
ROLES = ("Owner", "Admin", "Developer", "User", "Viewer")
DEFAULT_ORG_ID = "default-org"


def now_iso():
    return datetime.utcnow().isoformat()


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _dict(row):
    return dict(row) if row else None


def normalize_role(role):
    role_map = {item.lower(): item for item in ROLES}
    return role_map.get((role or "User").strip().lower(), "User")


def init_team_db():
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS organizations (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            owner_user_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS team_members (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            role TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'invited',
            usage_count INTEGER DEFAULT 0,
            invited_at TEXT NOT NULL,
            joined_at TEXT,
            last_active_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(organization_id, email)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS team_chats (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            member_id TEXT,
            title TEXT,
            message TEXT,
            response TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS team_documents (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            title TEXT,
            file_name TEXT,
            uploaded_by TEXT,
            size_bytes INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS team_memories (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            memory_type TEXT NOT NULL,
            content TEXT NOT NULL,
            importance INTEGER DEFAULT 1,
            created_by TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS usage_logs (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            member_id TEXT,
            user_id TEXT,
            action TEXT NOT NULL,
            metadata TEXT DEFAULT '{}',
            tokens INTEGER DEFAULT 0,
            cost REAL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_team_members_org ON team_members(organization_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_org_member ON usage_logs(organization_id, member_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_team_chats_org ON team_chats(organization_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_team_documents_org ON team_documents(organization_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_team_memories_org ON team_memories(organization_id)")
    conn.commit()
    conn.close()


def ensure_default_workspace(user_id="user_001", name="EVA Owner", email="owner@eva.local"):
    init_team_db()
    now = now_iso()
    conn = _connect()
    conn.execute("""
        INSERT INTO organizations (id, name, slug, owner_user_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET updated_at = excluded.updated_at
    """, (DEFAULT_ORG_ID, "EVA Workspace", "eva-workspace", user_id, now, now))
    owner = conn.execute("""
        SELECT * FROM team_members
        WHERE organization_id = ? AND role = 'Owner'
        LIMIT 1
    """, (DEFAULT_ORG_ID,)).fetchone()
    if not owner:
        conn.execute("""
            INSERT OR IGNORE INTO team_members (
                id, organization_id, name, email, role, status, usage_count,
                invited_at, joined_at, last_active_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            uuid.uuid4().hex, DEFAULT_ORG_ID, name or "EVA Owner", email or "owner@eva.local",
            "Owner", "active", 0, now, now, now, now, now,
        ))
    conn.commit()
    organization = _dict(conn.execute("SELECT * FROM organizations WHERE id = ?", (DEFAULT_ORG_ID,)).fetchone())
    conn.close()
    return organization


def get_organization(organization_id=DEFAULT_ORG_ID, user_id="user_001"):
    ensure_default_workspace(user_id=user_id)
    conn = _connect()
    organization = _dict(conn.execute("SELECT * FROM organizations WHERE id = ?", (organization_id,)).fetchone())
    conn.close()
    return organization


def list_members(organization_id=DEFAULT_ORG_ID, user_id="user_001"):
    ensure_default_workspace(user_id=user_id)
    conn = _connect()
    rows = [dict(row) for row in conn.execute("""
        SELECT * FROM team_members
        WHERE organization_id = ?
        ORDER BY
            CASE role
                WHEN 'Owner' THEN 1
                WHEN 'Admin' THEN 2
                WHEN 'Developer' THEN 3
                WHEN 'User' THEN 4
                ELSE 5
            END,
            name COLLATE NOCASE
    """, (organization_id,)).fetchall()]
    conn.close()
    return rows


def log_usage(organization_id=DEFAULT_ORG_ID, member_id=None, user_id="", action="workspace_event", metadata=None, tokens=0, cost=0):
    init_team_db()
    now = now_iso()
    payload = json.dumps(metadata or {}, ensure_ascii=False)
    conn = _connect()
    conn.execute("""
        INSERT INTO usage_logs (id, organization_id, member_id, user_id, action, metadata, tokens, cost, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (uuid.uuid4().hex, organization_id, member_id, user_id, action, payload, int(tokens or 0), float(cost or 0), now))
    if member_id:
        conn.execute("""
            UPDATE team_members
            SET usage_count = COALESCE(usage_count, 0) + 1,
                last_active_at = ?,
                updated_at = ?
            WHERE id = ? AND organization_id = ?
        """, (now, now, member_id, organization_id))
    conn.commit()
    conn.close()


def invite_member(organization_id, name, email, role="User", invited_by="user_001"):
    ensure_default_workspace(user_id=invited_by)
    clean_email = (email or "").strip().lower()
    if not clean_email or "@" not in clean_email:
        raise ValueError("A valid email is required")
    now = now_iso()
    member_id = uuid.uuid4().hex
    clean_role = normalize_role(role)
    conn = _connect()
    conn.execute("""
        INSERT INTO team_members (
            id, organization_id, name, email, role, status, usage_count,
            invited_at, joined_at, last_active_at, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(organization_id, email) DO UPDATE SET
            name = excluded.name,
            role = excluded.role,
            status = 'invited',
            invited_at = excluded.invited_at,
            updated_at = excluded.updated_at
    """, (
        member_id, organization_id, (name or clean_email.split("@", 1)[0]).strip(),
        clean_email, clean_role, "invited", 0, now, None, None, now, now,
    ))
    conn.commit()
    member = _dict(conn.execute("""
        SELECT * FROM team_members
        WHERE organization_id = ? AND email = ?
    """, (organization_id, clean_email)).fetchone())
    conn.close()
    log_usage(organization_id, member.get("id"), invited_by, "member_invited", {"email": clean_email, "role": clean_role})
    return member


def update_member_role(organization_id, member_id, role, actor_user_id="user_001"):
    clean_role = normalize_role(role)
    now = now_iso()
    conn = _connect()
    conn.execute("""
        UPDATE team_members
        SET role = ?, updated_at = ?
        WHERE id = ? AND organization_id = ?
    """, (clean_role, now, member_id, organization_id))
    conn.commit()
    member = _dict(conn.execute("SELECT * FROM team_members WHERE id = ? AND organization_id = ?", (member_id, organization_id)).fetchone())
    conn.close()
    if member:
        log_usage(organization_id, member_id, actor_user_id, "member_role_changed", {"role": clean_role})
    return member


def remove_member(organization_id, member_id, actor_user_id="user_001"):
    conn = _connect()
    member = _dict(conn.execute("SELECT * FROM team_members WHERE id = ? AND organization_id = ?", (member_id, organization_id)).fetchone())
    if not member:
        conn.close()
        return None
    if member.get("role") == "Owner":
        conn.close()
        raise ValueError("Owner cannot be removed")
    conn.execute("DELETE FROM team_members WHERE id = ? AND organization_id = ?", (member_id, organization_id))
    conn.commit()
    conn.close()
    log_usage(organization_id, None, actor_user_id, "member_removed", {"email": member.get("email"), "role": member.get("role")})
    return member


def member_usage(organization_id, member_id):
    init_team_db()
    conn = _connect()
    member = _dict(conn.execute("SELECT * FROM team_members WHERE id = ? AND organization_id = ?", (member_id, organization_id)).fetchone())
    logs = [dict(row) for row in conn.execute("""
        SELECT * FROM usage_logs
        WHERE organization_id = ? AND member_id = ?
        ORDER BY created_at DESC
        LIMIT 50
    """, (organization_id, member_id)).fetchall()]
    total = conn.execute("""
        SELECT COUNT(*) AS events, COALESCE(SUM(tokens), 0) AS tokens, COALESCE(SUM(cost), 0) AS cost
        FROM usage_logs
        WHERE organization_id = ? AND member_id = ?
    """, (organization_id, member_id)).fetchone()
    conn.close()
    return {
        "member": member,
        "logs": logs,
        "summary": _dict(total) or {"events": 0, "tokens": 0, "cost": 0},
    }


def workspace_summary(organization_id=DEFAULT_ORG_ID, user_id="user_001"):
    organization = get_organization(organization_id, user_id=user_id)
    members = list_members(organization_id, user_id=user_id)
    conn = _connect()
    counts = {}
    for table, key in (
        ("team_chats", "shared_chats"),
        ("team_documents", "shared_documents"),
        ("team_memories", "shared_memories"),
        ("usage_logs", "usage_events"),
    ):
        row = conn.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE organization_id = ?", (organization_id,)).fetchone()
        counts[key] = row["count"] if row else 0
    role_counts = [dict(row) for row in conn.execute("""
        SELECT role, COUNT(*) AS count
        FROM team_members
        WHERE organization_id = ?
        GROUP BY role
    """, (organization_id,)).fetchall()]
    recent_usage = [dict(row) for row in conn.execute("""
        SELECT usage_logs.*, team_members.name AS member_name, team_members.email AS member_email
        FROM usage_logs
        LEFT JOIN team_members ON team_members.id = usage_logs.member_id
        WHERE usage_logs.organization_id = ?
        ORDER BY usage_logs.created_at DESC
        LIMIT 20
    """, (organization_id,)).fetchall()]
    conn.close()
    return {
        "organization": organization,
        "members": members,
        "roles": list(ROLES),
        "counts": {
            **counts,
            "members": len(members),
            "active_members": len([m for m in members if m.get("status") == "active"]),
            "invited_members": len([m for m in members if m.get("status") == "invited"]),
        },
        "role_counts": role_counts,
        "recent_usage": recent_usage,
    }
