import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.getenv("EVA_AI_STUDIO_DB", ROOT_DIR / "ai_studio.db"))
DEFAULT_ORG_ID = "default-org"


TOOL_CATALOG = [
    {"id": "code_assistant", "name": "Code Assistant", "description": "Review files, suggest patches, and explain code."},
    {"id": "rag", "name": "RAG Search", "description": "Use uploaded documents and knowledge collections."},
    {"id": "vision", "name": "Vision Analysis", "description": "Analyze screenshots, UI, images, and visible text."},
    {"id": "security", "name": "Security Scanner", "description": "Check threats, privacy issues, and security posture."},
    {"id": "memory", "name": "Memory", "description": "Use user and project memories for context."},
    {"id": "web_research", "name": "Web Research", "description": "Research current public information when enabled."},
]


TEMPLATES = [
    {
        "id": "customer_support",
        "name": "Customer Support Agent",
        "description": "Answer customer questions with a calm, helpful support tone.",
        "system_prompt": "You are a customer support agent. Be concise, empathetic, and solution-focused. Ask for missing account details only when needed.",
        "model": "openai/gpt-oss-120b",
        "tools": ["rag", "memory"],
        "knowledge_base": ["Company FAQ", "Support SOP"],
        "avatar": "CS",
    },
    {
        "id": "code_review",
        "name": "Code Review Agent",
        "description": "Review projects, find bugs, and suggest safe patches.",
        "system_prompt": "You are a senior code review agent. Lead with bugs, risks, and missing tests. Provide exact, practical patch guidance.",
        "model": "qwen3-coder",
        "tools": ["code_assistant", "security"],
        "knowledge_base": ["Project source files"],
        "avatar": "CR",
    },
    {
        "id": "research",
        "name": "Research Agent",
        "description": "Summarize topics, compare sources, and produce structured research notes.",
        "system_prompt": "You are a research agent. Separate facts from assumptions, cite source names when available, and organize findings clearly.",
        "model": "openai/gpt-oss-120b",
        "tools": ["web_research", "rag"],
        "knowledge_base": ["Research documents"],
        "avatar": "RA",
    },
    {
        "id": "resume",
        "name": "Resume Agent",
        "description": "Improve resumes, summaries, and job application material.",
        "system_prompt": "You are a resume coach. Improve clarity, impact, and ATS-friendly wording while preserving truthfulness.",
        "model": "openai/gpt-oss-120b",
        "tools": ["rag"],
        "knowledge_base": ["Resume", "Job descriptions"],
        "avatar": "RS",
    },
    {
        "id": "interview_coach",
        "name": "Interview Coach",
        "description": "Run mock interviews and explain strong answers.",
        "system_prompt": "You are an interview coach. Ask realistic questions, give direct feedback, and help the user improve step by step.",
        "model": "openai/gpt-oss-120b",
        "tools": ["memory"],
        "knowledge_base": ["Role notes"],
        "avatar": "IC",
    },
    {
        "id": "security_analyst",
        "name": "Security Analyst",
        "description": "Analyze security issues, logs, and risk signals.",
        "system_prompt": "You are a security analyst. Identify threats, severity, likely impact, and practical remediation steps.",
        "model": "openai/gpt-oss-120b",
        "tools": ["security", "code_assistant"],
        "knowledge_base": ["Security logs", "Policies"],
        "avatar": "SA",
    },
    {
        "id": "rag_assistant",
        "name": "RAG Assistant",
        "description": "Answer questions from uploaded documents and knowledge collections.",
        "system_prompt": "You are a RAG assistant. Use provided knowledge first, state uncertainty, and avoid inventing document facts.",
        "model": "openai/gpt-oss-120b",
        "tools": ["rag", "memory"],
        "knowledge_base": ["Knowledge collection"],
        "avatar": "RA",
    },
]


def now_iso():
    return datetime.utcnow().isoformat()


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _rows(rows):
    return [dict(row) for row in rows]


def _json(value, fallback=None):
    if fallback is None:
        fallback = []
    try:
        if value is None:
            return fallback
        if isinstance(value, (list, dict)):
            return value
        return json.loads(value)
    except Exception:
        return fallback


def _ensure_column(conn, table, column, definition):
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_ai_studio_db():
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            organization_id TEXT DEFAULT 'default-org',
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            system_prompt TEXT NOT NULL,
            model TEXT DEFAULT 'openai/gpt-oss-120b',
            knowledge_base TEXT DEFAULT '[]',
            avatar TEXT DEFAULT 'AI',
            visibility TEXT DEFAULT 'private',
            status TEXT DEFAULT 'active',
            cloned_from_agent_id TEXT DEFAULT '',
            published_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    _ensure_column(conn, "agents", "organization_id", "TEXT DEFAULT 'default-org'")
    _ensure_column(conn, "agents", "cloned_from_agent_id", "TEXT DEFAULT ''")
    _ensure_column(conn, "agents", "published_at", "TEXT")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_tools (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_knowledge (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            source_name TEXT NOT NULL,
            source_type TEXT DEFAULT 'collection',
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_usage (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            message TEXT DEFAULT '',
            response TEXT DEFAULT '',
            tokens INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_owner ON agents(owner_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_org ON agents(organization_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_tools_agent ON agent_tools(agent_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_knowledge_agent ON agent_knowledge(agent_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_usage_agent ON agent_usage(agent_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_usage_user ON agent_usage(user_id)")
    conn.commit()
    conn.close()


def _agent_from_row(conn, row):
    agent = dict(row)
    agent["knowledge_base"] = _json(agent.get("knowledge_base"), [])
    agent["tools"] = [
        item["tool_name"]
        for item in _rows(conn.execute(
            "SELECT tool_name FROM agent_tools WHERE agent_id = ? AND enabled = 1 ORDER BY created_at ASC",
            (agent["id"],),
        ).fetchall())
    ]
    agent["knowledge_sources"] = _rows(conn.execute(
        "SELECT source_name, source_type, created_at FROM agent_knowledge WHERE agent_id = ? ORDER BY created_at ASC",
        (agent["id"],),
    ).fetchall())
    return agent


def list_agents(user_id="user_001"):
    init_ai_studio_db()
    conn = _connect()
    rows = conn.execute("""
        SELECT * FROM agents
        WHERE owner_id = ? OR visibility = 'public'
        ORDER BY updated_at DESC
    """, (user_id,)).fetchall()
    agents = [_agent_from_row(conn, row) for row in rows]
    conn.close()
    return agents


def get_agent(agent_id, user_id="user_001"):
    init_ai_studio_db()
    conn = _connect()
    row = conn.execute("""
        SELECT * FROM agents
        WHERE id = ? AND (owner_id = ? OR visibility = 'public')
        LIMIT 1
    """, (agent_id, user_id)).fetchone()
    if not row:
        conn.close()
        return None
    agent = _agent_from_row(conn, row)
    conn.close()
    return agent


def create_agent(
    user_id="user_001",
    organization_id=DEFAULT_ORG_ID,
    name="New Agent",
    description="",
    system_prompt="You are a helpful AI agent.",
    model="openai/gpt-oss-120b",
    knowledge_base=None,
    tools=None,
    avatar="AI",
    visibility="private",
):
    init_ai_studio_db()
    agent_id = uuid.uuid4().hex
    created_at = now_iso()
    knowledge_base = knowledge_base or []
    tools = tools or []
    conn = _connect()
    conn.execute("""
        INSERT INTO agents (
            id, owner_id, organization_id, name, description, system_prompt, model,
            knowledge_base, avatar, visibility, status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
    """, (
        agent_id,
        user_id,
        organization_id or DEFAULT_ORG_ID,
        name,
        description,
        system_prompt,
        model,
        json.dumps(knowledge_base, ensure_ascii=False),
        avatar or "AI",
        visibility or "private",
        created_at,
        created_at,
    ))
    for tool in tools:
        conn.execute("""
            INSERT INTO agent_tools (id, agent_id, tool_name, enabled, created_at)
            VALUES (?, ?, ?, 1, ?)
        """, (uuid.uuid4().hex, agent_id, str(tool), created_at))
    for source in knowledge_base:
        conn.execute("""
            INSERT INTO agent_knowledge (id, agent_id, source_name, source_type, created_at)
            VALUES (?, ?, ?, 'collection', ?)
        """, (uuid.uuid4().hex, agent_id, str(source), created_at))
    conn.commit()
    row = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
    agent = _agent_from_row(conn, row)
    conn.close()
    return agent


def delete_agent(agent_id, user_id="user_001"):
    init_ai_studio_db()
    conn = _connect()
    row = conn.execute("SELECT id FROM agents WHERE id = ? AND owner_id = ?", (agent_id, user_id)).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute("DELETE FROM agent_usage WHERE agent_id = ?", (agent_id,))
    conn.execute("DELETE FROM agent_tools WHERE agent_id = ?", (agent_id,))
    conn.execute("DELETE FROM agent_knowledge WHERE agent_id = ?", (agent_id,))
    conn.execute("DELETE FROM agents WHERE id = ? AND owner_id = ?", (agent_id, user_id))
    conn.commit()
    conn.close()
    return True


def record_agent_usage(agent_id, user_id, message="", response="", tokens=0):
    init_ai_studio_db()
    conn = _connect()
    conn.execute("""
        INSERT INTO agent_usage (id, agent_id, user_id, message, response, tokens, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        uuid.uuid4().hex,
        agent_id,
        user_id or "anonymous",
        message or "",
        response or "",
        int(tokens or 0),
        now_iso(),
    ))
    conn.commit()
    conn.close()


def agent_templates():
    return TEMPLATES


def tool_catalog():
    return TOOL_CATALOG


def studio_analytics(user_id="user_001"):
    init_ai_studio_db()
    conn = _connect()
    totals = conn.execute("""
        SELECT
          (SELECT COUNT(*) FROM agents WHERE owner_id = ?) AS total_agents,
          (SELECT COUNT(*) FROM agent_usage WHERE user_id = ?) AS total_chats,
          COALESCE((SELECT SUM(tokens) FROM agent_usage WHERE user_id = ?), 0) AS tokens_used
    """, (user_id, user_id, user_id)).fetchone()
    popular_agents = _rows(conn.execute("""
        SELECT a.id, COALESCE(a.name, u.agent_id) AS name, COUNT(u.id) AS chats, COALESCE(SUM(u.tokens), 0) AS tokens
        FROM agent_usage u
        LEFT JOIN agents a ON a.id = u.agent_id
        WHERE u.user_id = ?
        GROUP BY u.agent_id
        ORDER BY chats DESC
        LIMIT 10
    """, (user_id,)).fetchall())
    recent_usage = _rows(conn.execute("""
        SELECT u.agent_id, COALESCE(a.name, u.agent_id) AS agent_name, u.message, u.tokens, u.created_at
        FROM agent_usage u
        LEFT JOIN agents a ON a.id = u.agent_id
        WHERE u.user_id = ?
        ORDER BY u.created_at DESC
        LIMIT 12
    """, (user_id,)).fetchall())
    tool_usage = _rows(conn.execute("""
        SELECT tool_name, COUNT(*) AS agents
        FROM agent_tools
        WHERE agent_id IN (SELECT id FROM agents WHERE owner_id = ?)
        GROUP BY tool_name
        ORDER BY agents DESC
        LIMIT 10
    """, (user_id,)).fetchall())
    conn.close()
    return {
        "summary": {
            "total_agents": int(totals["total_agents"] or 0),
            "total_chats": int(totals["total_chats"] or 0),
            "tokens_used": int(totals["tokens_used"] or 0),
            "templates": len(TEMPLATES),
            "tools": len(TOOL_CATALOG),
        },
        "popular_agents": popular_agents,
        "recent_usage": recent_usage,
        "tool_usage": tool_usage,
    }
