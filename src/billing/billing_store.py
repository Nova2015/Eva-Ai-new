import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional


ROOT_DIR = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.getenv("EVA_BILLING_DB", ROOT_DIR / "billing.db"))
DEFAULT_ORG_ID = "default-org"
SCHEMA_VERSION = "2026_06_04_billing_v1"


PLAN_CATALOG = [
    {
        "id": "free",
        "name": "Free",
        "price_monthly_usd": 0,
        "included_tokens": 100_000,
        "monthly_agent_runs": 100,
        "documents_limit": 25,
        "team_members": 1,
        "marketplace_publications": 1,
        "features": ["Chat", "AI Studio", "Basic RAG", "Community marketplace"],
        "stripe_price_id": "",
    },
    {
        "id": "pro",
        "name": "Pro",
        "price_monthly_usd": 19,
        "included_tokens": 1_000_000,
        "monthly_agent_runs": 1_000,
        "documents_limit": 500,
        "team_members": 3,
        "marketplace_publications": 10,
        "features": ["Everything in Free", "Code Assistant", "Vision", "GitHub PR mode", "Priority usage"],
        "stripe_price_id": os.getenv("STRIPE_PRICE_PRO", ""),
    },
    {
        "id": "team",
        "name": "Team",
        "price_monthly_usd": 49,
        "included_tokens": 5_000_000,
        "monthly_agent_runs": 5_000,
        "documents_limit": 2_500,
        "team_members": 15,
        "marketplace_publications": 50,
        "features": ["Everything in Pro", "Team workspace", "Shared memory", "Run Center", "Admin analytics"],
        "stripe_price_id": os.getenv("STRIPE_PRICE_TEAM", ""),
    },
    {
        "id": "enterprise",
        "name": "Enterprise",
        "price_monthly_usd": 199,
        "included_tokens": 25_000_000,
        "monthly_agent_runs": 25_000,
        "documents_limit": 25_000,
        "team_members": 250,
        "marketplace_publications": 500,
        "features": ["Everything in Team", "Custom domains", "SAML-ready controls", "Dedicated support", "Advanced governance"],
        "stripe_price_id": os.getenv("STRIPE_PRICE_ENTERPRISE", ""),
    },
]


def now_iso():
    return datetime.utcnow().isoformat()


def period_start():
    now = datetime.utcnow()
    return datetime(now.year, now.month, 1).isoformat()


def period_end():
    now = datetime.utcnow()
    if now.month == 12:
        return datetime(now.year + 1, 1, 1).isoformat()
    return datetime(now.year, now.month + 1, 1).isoformat()


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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


def _row(row):
    if not row:
        return None
    item = dict(row)
    for key in ("features", "metadata"):
        if key in item:
            item[key] = _json(item.get(key), [] if key == "features" else {})
    for key in ("cancel_at_period_end", "active"):
        if key in item:
            item[key] = bool(item.get(key))
    return item


def _rows(rows):
    return [_row(row) for row in rows]


def init_billing_db():
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS billing_plans (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            price_monthly_usd REAL DEFAULT 0,
            included_tokens INTEGER DEFAULT 0,
            monthly_agent_runs INTEGER DEFAULT 0,
            documents_limit INTEGER DEFAULT 0,
            team_members INTEGER DEFAULT 1,
            marketplace_publications INTEGER DEFAULT 0,
            features TEXT DEFAULT '[]',
            stripe_price_id TEXT DEFAULT '',
            active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS organization_subscriptions (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL UNIQUE,
            plan_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            stripe_customer_id TEXT DEFAULT '',
            stripe_subscription_id TEXT DEFAULT '',
            billing_period_start TEXT NOT NULL,
            billing_period_end TEXT NOT NULL,
            cancel_at_period_end INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS billing_usage_events (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            user_id TEXT DEFAULT 'anonymous',
            feature TEXT NOT NULL,
            quantity INTEGER DEFAULT 1,
            tokens INTEGER DEFAULT 0,
            run_id TEXT DEFAULT '',
            metadata TEXT DEFAULT '{}',
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            subscription_id TEXT NOT NULL,
            invoice_number TEXT NOT NULL,
            amount_usd REAL DEFAULT 0,
            status TEXT DEFAULT 'draft',
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            hosted_invoice_url TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS payment_methods (
            id TEXT PRIMARY KEY,
            organization_id TEXT NOT NULL,
            provider TEXT DEFAULT 'stripe',
            brand TEXT DEFAULT '',
            last4 TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_billing_usage_org_time ON billing_usage_events(organization_id, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_billing_usage_feature ON billing_usage_events(feature, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_invoices_org ON invoices(organization_id, created_at)")
    now = now_iso()
    for plan in PLAN_CATALOG:
        conn.execute("""
            INSERT INTO billing_plans (
                id, name, price_monthly_usd, included_tokens, monthly_agent_runs,
                documents_limit, team_members, marketplace_publications, features,
                stripe_price_id, active, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                price_monthly_usd = excluded.price_monthly_usd,
                included_tokens = excluded.included_tokens,
                monthly_agent_runs = excluded.monthly_agent_runs,
                documents_limit = excluded.documents_limit,
                team_members = excluded.team_members,
                marketplace_publications = excluded.marketplace_publications,
                features = excluded.features,
                stripe_price_id = excluded.stripe_price_id,
                active = 1,
                updated_at = excluded.updated_at
        """, (
            plan["id"],
            plan["name"],
            plan["price_monthly_usd"],
            plan["included_tokens"],
            plan["monthly_agent_runs"],
            plan["documents_limit"],
            plan["team_members"],
            plan["marketplace_publications"],
            _dumps(plan["features"]),
            plan["stripe_price_id"],
            now,
            now,
        ))
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        (SCHEMA_VERSION, now),
    )
    conn.commit()
    conn.close()


def list_plans():
    init_billing_db()
    conn = _connect()
    plans = _rows(conn.execute("""
        SELECT * FROM billing_plans
        WHERE active = 1
        ORDER BY price_monthly_usd ASC
    """).fetchall())
    conn.close()
    return plans


def get_plan(plan_id):
    init_billing_db()
    conn = _connect()
    plan = _row(conn.execute("SELECT * FROM billing_plans WHERE id = ? AND active = 1", (plan_id,)).fetchone())
    conn.close()
    return plan


def ensure_subscription(organization_id=DEFAULT_ORG_ID):
    init_billing_db()
    organization_id = organization_id or DEFAULT_ORG_ID
    now = now_iso()
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM organization_subscriptions WHERE organization_id = ?",
        (organization_id,),
    ).fetchone()
    if not row:
        sub_id = uuid.uuid4().hex
        conn.execute("""
            INSERT INTO organization_subscriptions (
                id, organization_id, plan_id, status, billing_period_start,
                billing_period_end, cancel_at_period_end, created_at, updated_at
            )
            VALUES (?, ?, 'free', 'active', ?, ?, 0, ?, ?)
        """, (sub_id, organization_id, period_start(), period_end(), now, now))
        conn.execute("""
            INSERT INTO invoices (
                id, organization_id, subscription_id, invoice_number, amount_usd,
                status, period_start, period_end, hosted_invoice_url, created_at
            )
            VALUES (?, ?, ?, ?, 0, 'paid', ?, ?, '', ?)
        """, (
            uuid.uuid4().hex,
            organization_id,
            sub_id,
            f"EVA-{datetime.utcnow().strftime('%Y%m')}-FREE",
            period_start(),
            period_end(),
            now,
        ))
        conn.commit()
        row = conn.execute(
            "SELECT * FROM organization_subscriptions WHERE organization_id = ?",
            (organization_id,),
        ).fetchone()
    subscription = _row(row)
    conn.close()
    return subscription


def get_subscription(organization_id=DEFAULT_ORG_ID):
    subscription = ensure_subscription(organization_id)
    plan = get_plan(subscription["plan_id"]) or get_plan("free")
    usage = usage_summary(organization_id)
    return {
        "subscription": subscription,
        "plan": plan,
        "usage": usage,
        "entitlements": entitlements_for_plan(plan, usage),
    }


def change_subscription(organization_id=DEFAULT_ORG_ID, plan_id="free", actor_user_id="user_001"):
    init_billing_db()
    organization_id = organization_id or DEFAULT_ORG_ID
    plan = get_plan(plan_id)
    if not plan:
        raise ValueError("Plan not found")
    current = ensure_subscription(organization_id)
    now = now_iso()
    conn = _connect()
    conn.execute("""
        UPDATE organization_subscriptions
        SET plan_id = ?, status = 'active', billing_period_start = ?,
            billing_period_end = ?, cancel_at_period_end = 0, updated_at = ?
        WHERE organization_id = ?
    """, (plan_id, period_start(), period_end(), now, organization_id))
    amount = float(plan.get("price_monthly_usd") or 0)
    invoice_status = "paid" if amount == 0 else "open"
    conn.execute("""
        INSERT INTO invoices (
            id, organization_id, subscription_id, invoice_number, amount_usd,
            status, period_start, period_end, hosted_invoice_url, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        uuid.uuid4().hex,
        organization_id,
        current["id"],
        f"EVA-{datetime.utcnow().strftime('%Y%m%d')}-{plan_id.upper()}",
        amount,
        invoice_status,
        period_start(),
        period_end(),
        "",
        now,
    ))
    conn.commit()
    conn.close()
    record_usage(
        organization_id=organization_id,
        user_id=actor_user_id,
        feature="billing_plan_changed",
        quantity=1,
        tokens=0,
        metadata={"plan_id": plan_id},
    )
    return get_subscription(organization_id)


def record_usage(
    organization_id=DEFAULT_ORG_ID,
    user_id="anonymous",
    feature="chat",
    quantity=1,
    tokens=0,
    run_id="",
    metadata: Optional[Dict[str, Any]] = None,
):
    init_billing_db()
    ensure_subscription(organization_id)
    conn = _connect()
    conn.execute("""
        INSERT INTO billing_usage_events (
            id, organization_id, user_id, feature, quantity, tokens, run_id, metadata, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        uuid.uuid4().hex,
        organization_id or DEFAULT_ORG_ID,
        user_id or "anonymous",
        feature or "event",
        int(quantity or 1),
        int(tokens or 0),
        run_id or "",
        _dumps(metadata),
        now_iso(),
    ))
    conn.commit()
    conn.close()
    return usage_summary(organization_id)


def usage_summary(organization_id=DEFAULT_ORG_ID):
    init_billing_db()
    organization_id = organization_id or DEFAULT_ORG_ID
    start = period_start()
    conn = _connect()
    total = _row(conn.execute("""
        SELECT
            COUNT(*) AS events,
            COALESCE(SUM(quantity), 0) AS quantity,
            COALESCE(SUM(tokens), 0) AS tokens
        FROM billing_usage_events
        WHERE organization_id = ? AND created_at >= ?
    """, (organization_id, start)).fetchone())
    by_feature = _rows(conn.execute("""
        SELECT feature, COUNT(*) AS events, COALESCE(SUM(quantity), 0) AS quantity, COALESCE(SUM(tokens), 0) AS tokens
        FROM billing_usage_events
        WHERE organization_id = ? AND created_at >= ?
        GROUP BY feature
        ORDER BY events DESC
        LIMIT 20
    """, (organization_id, start)).fetchall())
    recent = _rows(conn.execute("""
        SELECT * FROM billing_usage_events
        WHERE organization_id = ?
        ORDER BY created_at DESC
        LIMIT 25
    """, (organization_id,)).fetchall())
    conn.close()
    return {
        "period_start": start,
        "period_end": period_end(),
        "totals": total or {"events": 0, "quantity": 0, "tokens": 0},
        "by_feature": by_feature,
        "recent": recent,
    }


def entitlements_for_plan(plan, usage=None):
    plan = plan or get_plan("free")
    usage = usage or {"totals": {"tokens": 0}}
    tokens_used = int((usage.get("totals") or {}).get("tokens") or 0)
    included_tokens = int(plan.get("included_tokens") or 0)
    return {
        "plan_id": plan.get("id"),
        "included_tokens": included_tokens,
        "tokens_used": tokens_used,
        "tokens_remaining": max(included_tokens - tokens_used, 0),
        "tokens_percent": round((tokens_used / included_tokens) * 100, 1) if included_tokens else 0,
        "monthly_agent_runs": int(plan.get("monthly_agent_runs") or 0),
        "documents_limit": int(plan.get("documents_limit") or 0),
        "team_members": int(plan.get("team_members") or 1),
        "marketplace_publications": int(plan.get("marketplace_publications") or 0),
        "features": plan.get("features") or [],
    }


def check_entitlement(organization_id=DEFAULT_ORG_ID, feature="tokens", requested=1):
    state = get_subscription(organization_id)
    entitlements = state["entitlements"]
    allowed = True
    reason = "ok"
    if feature == "tokens":
        allowed = entitlements["tokens_remaining"] >= int(requested or 0)
        reason = "Token quota exceeded" if not allowed else "ok"
    return {"allowed": allowed, "reason": reason, **state}


def list_invoices(organization_id=DEFAULT_ORG_ID):
    ensure_subscription(organization_id)
    conn = _connect()
    invoices = _rows(conn.execute("""
        SELECT * FROM invoices
        WHERE organization_id = ?
        ORDER BY created_at DESC
        LIMIT 50
    """, (organization_id or DEFAULT_ORG_ID,)).fetchall())
    conn.close()
    return invoices


def create_checkout_session(organization_id=DEFAULT_ORG_ID, plan_id="pro", success_url="", cancel_url=""):
    plan = get_plan(plan_id)
    if not plan:
        raise ValueError("Plan not found")
    record_usage(
        organization_id=organization_id,
        user_id="billing",
        feature="checkout_session_created",
        metadata={"plan_id": plan_id},
    )
    return {
        "provider": "stripe",
        "mode": "subscription",
        "plan_id": plan_id,
        "stripe_price_id": plan.get("stripe_price_id") or "",
        "checkout_url": "",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "status": "stripe_not_configured" if not plan.get("stripe_price_id") else "ready_for_stripe",
    }
