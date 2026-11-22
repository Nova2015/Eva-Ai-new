import json
import os
import re
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai_studio.studio_store import create_agent as studio_create_agent
from ai_studio.studio_store import init_ai_studio_db


ROOT_DIR = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.getenv("EVA_AI_STUDIO_DB", ROOT_DIR / "ai_studio.db"))
DEFAULT_ORG_ID = "default-org"
SCHEMA_VERSION = "2026_06_03_cloud_platform_v1"
PUBLICATION_STATUSES = {"pending", "approved", "rejected", "hidden"}
VISIBILITIES = {"public", "private"}


def now_iso():
    return datetime.utcnow().isoformat()


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _row(row):
    if not row:
        return None
    item = dict(row)
    for key in ("tags", "metadata"):
        if key in item:
            item[key] = _json(item.get(key), [] if key == "tags" else {})
    for key in ("allow_cloning", "is_featured"):
        if key in item:
            item[key] = bool(item.get(key))
    return item


def _rows(rows):
    return [_row(row) for row in rows]


def _json(value, fallback=None):
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


def _dumps(value):
    return json.dumps(value or {}, ensure_ascii=False)


def _ensure_column(conn, table, column, definition):
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "eva-agent").lower()).strip("-")
    return slug[:72] or "eva-agent"


def _unique_slug(conn, title, current_id=""):
    base = _slugify(title)
    slug = base
    index = 2
    while True:
        row = conn.execute(
            "SELECT id FROM agent_publications WHERE slug = ? AND id != ?",
            (slug, current_id or ""),
        ).fetchone()
        if not row:
            return slug
        slug = f"{base}-{index}"
        index += 1


def _normalize_visibility(value):
    clean = (value or "private").strip().lower()
    return clean if clean in VISIBILITIES else "private"


def _normalize_status(value):
    clean = (value or "pending").strip().lower()
    return clean if clean in PUBLICATION_STATUSES else "pending"


def init_cloud_platform_db():
    init_ai_studio_db()
    conn = _connect()
    _ensure_column(conn, "agents", "organization_id", "TEXT DEFAULT 'default-org'")
    _ensure_column(conn, "agents", "cloned_from_agent_id", "TEXT DEFAULT ''")
    _ensure_column(conn, "agents", "published_at", "TEXT")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_publications (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            organization_id TEXT DEFAULT 'default-org',
            slug TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            category TEXT DEFAULT 'General',
            tags TEXT DEFAULT '[]',
            visibility TEXT DEFAULT 'private',
            status TEXT DEFAULT 'pending',
            moderation_status TEXT DEFAULT 'pending',
            moderation_reason TEXT DEFAULT '',
            allow_cloning INTEGER DEFAULT 1,
            is_featured INTEGER DEFAULT 0,
            total_uses INTEGER DEFAULT 0,
            total_clones INTEGER DEFAULT 0,
            rating_count INTEGER DEFAULT 0,
            review_count INTEGER DEFAULT 0,
            average_rating REAL DEFAULT 0,
            published_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(agent_id, owner_id, organization_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_reviews (
            id TEXT PRIMARY KEY,
            publication_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            rating INTEGER NOT NULL,
            review TEXT DEFAULT '',
            status TEXT DEFAULT 'visible',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(publication_id, user_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS published_agent_usage (
            id TEXT PRIMARY KEY,
            publication_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            user_id TEXT DEFAULT 'anonymous',
            organization_id TEXT DEFAULT 'default-org',
            action TEXT NOT NULL,
            tokens INTEGER DEFAULT 0,
            metadata TEXT DEFAULT '{}',
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_clones (
            id TEXT PRIMARY KEY,
            publication_id TEXT NOT NULL,
            source_agent_id TEXT NOT NULL,
            cloned_agent_id TEXT NOT NULL,
            cloned_by TEXT NOT NULL,
            organization_id TEXT DEFAULT 'default-org',
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS marketplace_moderation_actions (
            id TEXT PRIMARY KEY,
            publication_id TEXT NOT NULL,
            moderator_id TEXT NOT NULL,
            action TEXT NOT NULL,
            status_before TEXT DEFAULT '',
            status_after TEXT DEFAULT '',
            reason TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_publications_slug ON agent_publications(slug)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_publications_market ON agent_publications(visibility, status, updated_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_publications_owner ON agent_publications(owner_id, updated_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_publications_org ON agent_publications(organization_id, updated_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_reviews_pub ON agent_reviews(publication_id, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_published_agent_usage_pub ON published_agent_usage(publication_id, created_at)")
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        (SCHEMA_VERSION, now_iso()),
    )
    conn.commit()
    conn.close()


def _agent_fields():
    return """
        a.name AS agent_name,
        a.description AS agent_description,
        a.system_prompt AS system_prompt,
        a.model AS model,
        a.knowledge_base AS knowledge_base,
        a.avatar AS avatar,
        a.visibility AS agent_visibility,
        a.status AS agent_status,
        (
            SELECT GROUP_CONCAT(tool_name, ',')
            FROM agent_tools
            WHERE agent_id = a.id AND enabled = 1
        ) AS tools_csv
    """


def _publication_select():
    return f"""
        SELECT p.*, {_agent_fields()}
        FROM agent_publications p
        LEFT JOIN agents a ON a.id = p.agent_id
    """


def _hydrate_publication(item):
    if not item:
        return None
    item["tags"] = item.get("tags") if isinstance(item.get("tags"), list) else _json(item.get("tags"), [])
    item["knowledge_base"] = _json(item.get("knowledge_base"), [])
    item["allow_cloning"] = bool(item.get("allow_cloning"))
    item["is_featured"] = bool(item.get("is_featured"))
    item["share_url"] = f"/agent/{item.get('slug')}"
    item["agent"] = {
        "id": item.get("agent_id"),
        "name": item.get("agent_name") or item.get("title"),
        "description": item.get("agent_description") or item.get("description"),
        "system_prompt": item.get("system_prompt") or "",
        "model": item.get("model") or "openai/gpt-oss-120b",
        "knowledge_base": item.get("knowledge_base") or [],
        "tools": [tool for tool in str(item.get("tools_csv") or "").split(",") if tool],
        "avatar": item.get("avatar") or "AI",
        "visibility": item.get("agent_visibility") or "private",
        "status": item.get("agent_status") or "active",
    }
    return item


def _can_view_publication(pub, user_id="", organization_id=DEFAULT_ORG_ID, include_pending=False):
    if not pub:
        return False
    if include_pending:
        return True
    if pub.get("visibility") == "public" and pub.get("status") == "approved":
        return True
    if user_id and pub.get("owner_id") == user_id:
        return True
    if organization_id and pub.get("organization_id") == organization_id and pub.get("visibility") == "private":
        return True
    return False


def get_agent_for_publish(agent_id, user_id):
    init_cloud_platform_db()
    conn = _connect()
    row = conn.execute("SELECT * FROM agents WHERE id = ? AND owner_id = ?", (agent_id, user_id)).fetchone()
    if not row:
        row = conn.execute("SELECT * FROM agents WHERE id = ? AND owner_id = 'user_001'", (agent_id,)).fetchone()
    agent = _row(row)
    if agent:
        agent["knowledge_base"] = _json(agent.get("knowledge_base"), [])
    conn.close()
    return agent


def publish_agent(
    agent_id,
    user_id="user_001",
    organization_id=DEFAULT_ORG_ID,
    visibility="private",
    title="",
    description="",
    category="General",
    tags=None,
    allow_cloning=True,
):
    init_cloud_platform_db()
    user_id = user_id or "user_001"
    organization_id = organization_id or DEFAULT_ORG_ID
    agent = get_agent_for_publish(agent_id, user_id)
    if not agent:
        raise ValueError("Agent not found or not owned by user")
    now = now_iso()
    visibility = _normalize_visibility(visibility)
    status = "pending" if visibility == "public" else "approved"
    moderation_status = "pending" if visibility == "public" else "approved"
    title = (title or agent.get("name") or "EVA Agent").strip()
    description = description or agent.get("description") or ""
    tags = tags or []
    conn = _connect()
    existing = conn.execute("""
        SELECT * FROM agent_publications
        WHERE agent_id = ? AND owner_id = ? AND organization_id = ?
    """, (agent_id, user_id, organization_id)).fetchone()
    if existing:
        publication_id = existing["id"]
        slug = _unique_slug(conn, title, current_id=publication_id)
        status = existing["status"] if existing["visibility"] == visibility and existing["status"] != "rejected" else status
        moderation_status = existing["moderation_status"] if existing["visibility"] == visibility and existing["status"] != "rejected" else moderation_status
        conn.execute("""
            UPDATE agent_publications
            SET slug = ?, title = ?, description = ?, category = ?, tags = ?,
                visibility = ?, status = ?, moderation_status = ?,
                allow_cloning = ?, updated_at = ?
            WHERE id = ?
        """, (
            slug,
            title,
            description,
            category or "General",
            json.dumps(tags, ensure_ascii=False),
            visibility,
            status,
            moderation_status,
            1 if allow_cloning else 0,
            now,
            publication_id,
        ))
    else:
        publication_id = uuid.uuid4().hex
        slug = _unique_slug(conn, title)
        conn.execute("""
            INSERT INTO agent_publications (
                id, agent_id, owner_id, organization_id, slug, title, description,
                category, tags, visibility, status, moderation_status,
                allow_cloning, published_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            publication_id,
            agent_id,
            user_id,
            organization_id,
            slug,
            title,
            description,
            category or "General",
            json.dumps(tags, ensure_ascii=False),
            visibility,
            status,
            moderation_status,
            1 if allow_cloning else 0,
            now,
            now,
            now,
        ))
    agent_visibility = "public" if visibility == "public" and status == "approved" else "private"
    conn.execute("""
        UPDATE agents
        SET organization_id = ?, visibility = ?, published_at = ?, updated_at = ?
        WHERE id = ?
    """, (organization_id, agent_visibility, now, now, agent_id))
    conn.commit()
    row = conn.execute(f"{_publication_select()} WHERE p.id = ?", (publication_id,)).fetchone()
    conn.close()
    return _hydrate_publication(_row(row))


def list_marketplace_agents(
    user_id="user_001",
    organization_id=DEFAULT_ORG_ID,
    query="",
    category="",
    visibility="",
    status="approved",
    limit=100,
):
    init_cloud_platform_db()
    user_id = user_id or "user_001"
    organization_id = organization_id or DEFAULT_ORG_ID
    clauses = []
    params = []
    status = (status or "approved").strip().lower()
    if status == "all":
        clauses.append("(p.status = 'approved' OR p.owner_id = ? OR p.organization_id = ?)")
        params.extend([user_id, organization_id])
    else:
        clauses.append("(p.status = ? OR p.owner_id = ? OR p.organization_id = ?)")
        params.extend([_normalize_status(status), user_id, organization_id])
    clauses.append("(p.visibility = 'public' OR p.owner_id = ? OR p.organization_id = ?)")
    params.extend([user_id, organization_id])
    if visibility:
        clauses.append("p.visibility = ?")
        params.append(_normalize_visibility(visibility))
    if category:
        clauses.append("LOWER(p.category) = LOWER(?)")
        params.append(category)
    if query:
        clauses.append("(LOWER(p.title) LIKE LOWER(?) OR LOWER(p.description) LIKE LOWER(?) OR LOWER(p.category) LIKE LOWER(?))")
        needle = f"%{query.strip()}%"
        params.extend([needle, needle, needle])
    params.append(max(1, min(int(limit or 100), 200)))
    conn = _connect()
    rows = conn.execute(f"""
        {_publication_select()}
        WHERE {' AND '.join(clauses)}
        ORDER BY p.is_featured DESC, p.average_rating DESC, p.total_uses DESC, p.updated_at DESC
        LIMIT ?
    """, params).fetchall()
    items = [_hydrate_publication(_row(row)) for row in rows]
    conn.close()
    return items


def list_my_publications(user_id="user_001", organization_id=DEFAULT_ORG_ID):
    init_cloud_platform_db()
    conn = _connect()
    rows = conn.execute(f"""
        {_publication_select()}
        WHERE p.owner_id = ? OR p.organization_id = ?
        ORDER BY p.updated_at DESC
    """, (user_id or "user_001", organization_id or DEFAULT_ORG_ID)).fetchall()
    items = [_hydrate_publication(_row(row)) for row in rows]
    conn.close()
    return items


def get_publication(identifier, user_id="user_001", organization_id=DEFAULT_ORG_ID, include_pending=False):
    init_cloud_platform_db()
    conn = _connect()
    row = conn.execute(f"""
        {_publication_select()}
        WHERE p.id = ? OR p.slug = ?
        LIMIT 1
    """, (identifier, identifier)).fetchone()
    item = _hydrate_publication(_row(row))
    conn.close()
    if not _can_view_publication(item, user_id=user_id, organization_id=organization_id, include_pending=include_pending):
        return None
    return item


def update_publication(publication_id, user_id="user_001", **changes):
    init_cloud_platform_db()
    current = get_publication(publication_id, user_id=user_id, include_pending=True)
    if not current or current.get("owner_id") != user_id:
        return None
    allowed = {}
    for key in ("title", "description", "category", "visibility", "allow_cloning"):
        if key in changes and changes[key] is not None:
            allowed[key] = changes[key]
    if "tags" in changes and changes["tags"] is not None:
        allowed["tags"] = json.dumps(changes["tags"], ensure_ascii=False)
    if not allowed:
        return current
    now = now_iso()
    conn = _connect()
    if "title" in allowed:
        allowed["slug"] = _unique_slug(conn, allowed["title"], current_id=publication_id)
    if "visibility" in allowed:
        allowed["visibility"] = _normalize_visibility(allowed["visibility"])
        if allowed["visibility"] == "public" and current.get("status") != "approved":
            allowed["status"] = "pending"
            allowed["moderation_status"] = "pending"
    if "allow_cloning" in allowed:
        allowed["allow_cloning"] = 1 if allowed["allow_cloning"] else 0
    allowed["updated_at"] = now
    assignments = ", ".join([f"{key} = ?" for key in allowed])
    params = list(allowed.values()) + [publication_id]
    conn.execute(f"UPDATE agent_publications SET {assignments} WHERE id = ?", params)
    conn.commit()
    row = conn.execute(f"{_publication_select()} WHERE p.id = ?", (publication_id,)).fetchone()
    conn.close()
    return _hydrate_publication(_row(row))


def record_publication_usage(publication_id, user_id="anonymous", organization_id=DEFAULT_ORG_ID, action="view", tokens=0, metadata=None):
    init_cloud_platform_db()
    pub = get_publication(publication_id, user_id=user_id, organization_id=organization_id, include_pending=True)
    if not pub:
        return None
    now = now_iso()
    conn = _connect()
    conn.execute("""
        INSERT INTO published_agent_usage (
            id, publication_id, agent_id, user_id, organization_id, action, tokens, metadata, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        uuid.uuid4().hex,
        pub["id"],
        pub["agent_id"],
        user_id or "anonymous",
        organization_id or DEFAULT_ORG_ID,
        action or "view",
        int(tokens or 0),
        _dumps(metadata),
        now,
    ))
    if action in ("view", "chat", "clone", "install", "use"):
        conn.execute("""
            UPDATE agent_publications
            SET total_uses = COALESCE(total_uses, 0) + 1,
                updated_at = ?
            WHERE id = ?
        """, (now, pub["id"]))
    conn.commit()
    row = conn.execute(f"{_publication_select()} WHERE p.id = ?", (pub["id"],)).fetchone()
    conn.close()
    return _hydrate_publication(_row(row))


def clone_publication(publication_id, user_id="user_001", organization_id=DEFAULT_ORG_ID, name=""):
    init_cloud_platform_db()
    pub = get_publication(publication_id, user_id=user_id, organization_id=organization_id)
    if not pub:
        raise ValueError("Published agent not found")
    if not pub.get("allow_cloning"):
        raise ValueError("Cloning is disabled for this agent")
    source = pub.get("agent") or {}
    clone_name = (name or f"{source.get('name') or pub.get('title')} Copy").strip()
    cloned = studio_create_agent(
        user_id=user_id or "user_001",
        organization_id=organization_id or DEFAULT_ORG_ID,
        name=clone_name,
        description=source.get("description") or pub.get("description") or "",
        system_prompt=source.get("system_prompt") or "You are a helpful AI agent.",
        model=source.get("model") or "openai/gpt-oss-120b",
        knowledge_base=source.get("knowledge_base") or [],
        tools=source.get("tools") or [],
        avatar=source.get("avatar") or "AI",
        visibility="private",
    )
    now = now_iso()
    conn = _connect()
    conn.execute(
        "UPDATE agents SET cloned_from_agent_id = ?, organization_id = ?, updated_at = ? WHERE id = ?",
        (pub["agent_id"], organization_id or DEFAULT_ORG_ID, now, cloned["id"]),
    )
    conn.execute("""
        INSERT INTO agent_clones (
            id, publication_id, source_agent_id, cloned_agent_id, cloned_by, organization_id, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        uuid.uuid4().hex,
        pub["id"],
        pub["agent_id"],
        cloned["id"],
        user_id or "user_001",
        organization_id or DEFAULT_ORG_ID,
        now,
    ))
    conn.execute("""
        UPDATE agent_publications
        SET total_clones = COALESCE(total_clones, 0) + 1,
            total_uses = COALESCE(total_uses, 0) + 1,
            updated_at = ?
        WHERE id = ?
    """, (now, pub["id"]))
    conn.commit()
    conn.close()
    record_publication_usage(pub["id"], user_id=user_id, organization_id=organization_id, action="clone", metadata={"cloned_agent_id": cloned["id"]})
    return cloned


def list_reviews(publication_id, include_hidden=False):
    init_cloud_platform_db()
    conn = _connect()
    where = "publication_id = ?" if include_hidden else "publication_id = ? AND status = 'visible'"
    rows = conn.execute(f"""
        SELECT * FROM agent_reviews
        WHERE {where}
        ORDER BY updated_at DESC
        LIMIT 100
    """, (publication_id,)).fetchall()
    reviews = _rows(rows)
    conn.close()
    return reviews


def _recompute_review_stats(conn, publication_id):
    stats = conn.execute("""
        SELECT
            COUNT(*) AS review_count,
            COALESCE(SUM(CASE WHEN status = 'visible' THEN 1 ELSE 0 END), 0) AS rating_count,
            COALESCE(AVG(CASE WHEN status = 'visible' THEN rating END), 0) AS average_rating
        FROM agent_reviews
        WHERE publication_id = ?
    """, (publication_id,)).fetchone()
    conn.execute("""
        UPDATE agent_publications
        SET review_count = ?, rating_count = ?, average_rating = ?, updated_at = ?
        WHERE id = ?
    """, (
        int(stats["review_count"] or 0),
        int(stats["rating_count"] or 0),
        round(float(stats["average_rating"] or 0), 2),
        now_iso(),
        publication_id,
    ))


def add_review(publication_id, user_id="user_001", rating=5, review=""):
    init_cloud_platform_db()
    pub = get_publication(publication_id, user_id=user_id)
    if not pub:
        raise ValueError("Published agent not found")
    clean_rating = max(1, min(int(rating or 5), 5))
    now = now_iso()
    conn = _connect()
    conn.execute("""
        INSERT INTO agent_reviews (id, publication_id, user_id, rating, review, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'visible', ?, ?)
        ON CONFLICT(publication_id, user_id) DO UPDATE SET
            rating = excluded.rating,
            review = excluded.review,
            status = 'visible',
            updated_at = excluded.updated_at
    """, (
        uuid.uuid4().hex,
        pub["id"],
        user_id or "anonymous",
        clean_rating,
        review or "",
        now,
        now,
    ))
    _recompute_review_stats(conn, pub["id"])
    conn.commit()
    row = conn.execute(
        "SELECT * FROM agent_reviews WHERE publication_id = ? AND user_id = ?",
        (pub["id"], user_id or "anonymous"),
    ).fetchone()
    conn.close()
    record_publication_usage(pub["id"], user_id=user_id, action="review", metadata={"rating": clean_rating})
    return _row(row)


def list_moderation_queue(status="pending", organization_id=""):
    init_cloud_platform_db()
    clauses = []
    params = []
    if status and status != "all":
        clauses.append("p.status = ?")
        params.append(_normalize_status(status))
    if organization_id:
        clauses.append("p.organization_id = ?")
        params.append(organization_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = _connect()
    rows = conn.execute(f"""
        {_publication_select()}
        {where}
        ORDER BY p.updated_at DESC
        LIMIT 200
    """, params).fetchall()
    items = [_hydrate_publication(_row(row)) for row in rows]
    conn.close()
    return items


def moderate_publication(publication_id, moderator_id="admin", action="approve", reason="", is_featured=None):
    init_cloud_platform_db()
    current = get_publication(publication_id, include_pending=True)
    if not current:
        return None
    action = (action or "approve").strip().lower()
    status_after = {
        "approve": "approved",
        "approved": "approved",
        "reject": "rejected",
        "rejected": "rejected",
        "hide": "hidden",
        "hidden": "hidden",
        "restore": "approved",
    }.get(action, "approved")
    now = now_iso()
    conn = _connect()
    featured_sql = ""
    params = [status_after, status_after, reason or "", now]
    if is_featured is not None:
        featured_sql = ", is_featured = ?"
        params.append(1 if is_featured else 0)
    params.append(publication_id)
    conn.execute(f"""
        UPDATE agent_publications
        SET status = ?, moderation_status = ?, moderation_reason = ?, updated_at = ?
            {featured_sql}
        WHERE id = ?
    """, params)
    agent_visibility = "public" if current.get("visibility") == "public" and status_after == "approved" else "private"
    conn.execute(
        "UPDATE agents SET visibility = ?, updated_at = ? WHERE id = ?",
        (agent_visibility, now, current["agent_id"]),
    )
    conn.execute("""
        INSERT INTO marketplace_moderation_actions (
            id, publication_id, moderator_id, action, status_before, status_after, reason, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        uuid.uuid4().hex,
        publication_id,
        moderator_id or "admin",
        action,
        current.get("status") or "",
        status_after,
        reason or "",
        now,
    ))
    conn.commit()
    row = conn.execute(f"{_publication_select()} WHERE p.id = ?", (publication_id,)).fetchone()
    conn.close()
    return _hydrate_publication(_row(row))


def marketplace_summary(user_id="user_001", organization_id=DEFAULT_ORG_ID):
    init_cloud_platform_db()
    conn = _connect()
    summary = _row(conn.execute("""
        SELECT
            COUNT(*) AS total_published,
            COALESCE(SUM(CASE WHEN visibility = 'public' AND status = 'approved' THEN 1 ELSE 0 END), 0) AS public_agents,
            COALESCE(SUM(CASE WHEN visibility = 'private' THEN 1 ELSE 0 END), 0) AS private_agents,
            COALESCE(SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END), 0) AS pending_review,
            COALESCE(SUM(total_uses), 0) AS total_uses,
            COALESCE(SUM(total_clones), 0) AS total_clones
        FROM agent_publications
        WHERE owner_id = ? OR organization_id = ? OR (visibility = 'public' AND status = 'approved')
    """, (user_id or "user_001", organization_id or DEFAULT_ORG_ID)).fetchone())
    categories = _rows(conn.execute("""
        SELECT category, COUNT(*) AS count
        FROM agent_publications
        WHERE visibility = 'public' AND status = 'approved'
        GROUP BY category
        ORDER BY count DESC
        LIMIT 12
    """).fetchall())
    popular = _rows(conn.execute(f"""
        {_publication_select()}
        WHERE p.visibility = 'public' AND p.status = 'approved'
        ORDER BY p.total_uses DESC, p.average_rating DESC
        LIMIT 6
    """).fetchall())
    conn.close()
    return {
        "summary": summary or {},
        "categories": categories,
        "popular": [_hydrate_publication(item) for item in popular],
    }
