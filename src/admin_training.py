"""
Update 53 — AI Training Center (admin backend APIs)
===================================================
Internal admin workspace APIs under /admin-api/training/*. The dashboard UI
(admin_training_ui.html, served at /admin/training) is a shell — every number
it shows comes from these endpoints or existing public ones. No mock data.

Module backing (honest inventory):
  Dataset Manager      -> Dataset Center on the ML service (live HTTP)
  Conversation Review  -> learning_loop /train API (+ needs-improvement/correct)
  Prompt Testing       -> /prompt-test below; ONLY providers with configured
                          API keys run (Groq/Gemini/OpenAI today). Claude and
                          DeepSeek appear as unavailable until keys exist.
  Evaluation           -> /evaluate below; background golden-set replay
                          against the LIVE /chat endpoint. Vision is excluded
                          until an image harness exists.
  Synthetic Generator  -> /synthetic below; generated pairs enter the normal
                          human-approval queue as PENDING candidates.
  Model Registry       -> /registry below; read-only truth (provider keys,
                          LoRA repos). Deploy/rollback lands with Update 54.
  Analytics            -> /overview below + existing public counters.
  Experiment Lab       -> stored prompt-test + evaluation runs (list/compare).
  AI Memory Builder    -> feedback rows (existing store) -> /feedback-to-candidate.

Auth: same X-Train-Key convention as /train (env TRAIN_ADMIN_KEY; open when
unset). The UI keeps the key in localStorage and sends it on every call.
"""

import json
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.learning_loop import (
    _db as _loop_db,
    _lock as _loop_lock,
    _fingerprint,
    require_train_admin,
    STATUS_PENDING,
)

logger = logging.getLogger("EVA.admin_training")
router = APIRouter()

HF_ML_URL = os.getenv("HF_ML_URL", "https://keshav1212-eva-ml-service.hf.space").rstrip("/")
EVAL_CHAT_URL = os.getenv("EVAL_CHAT_URL", "https://eva-ai-1-9wfc.onrender.com/chat")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

# OpenRouter free models, tried in order. Verified against their public
# /api/v1/models catalogue; override with OPENROUTER_MODELS (comma-separated).
OPENROUTER_MODELS = [
    m.strip() for m in os.getenv(
        "OPENROUTER_MODELS",
        "google/gemma-4-31b-it:free,openai/gpt-oss-20b:free,"
        "inclusionai/ling-3.0-flash:free,nvidia/nemotron-3-nano-30b-a3b:free,"
        "nvidia/nemotron-3-super-120b-a12b:free",
    ).split(",") if m.strip()
]

# Set by app.py after import so feedback queries hit the existing store
# without a circular import.
FEEDBACK_DB_PATH: Optional[str] = None

_tables_ready = False


def _db() -> sqlite3.Connection:
    """Shares learning_loop.db; adds the Training Center tables once."""
    global _tables_ready
    conn = _loop_db()
    if not _tables_ready:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS prompt_tests ("
            " id TEXT PRIMARY KEY, created_at TEXT NOT NULL,"
            " prompt TEXT NOT NULL, results TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS eval_runs ("
            " id TEXT PRIMARY KEY, created_at TEXT NOT NULL,"
            " suite TEXT NOT NULL, status TEXT NOT NULL,"
            " results TEXT)"
        )
        conn.commit()
        _tables_ready = True
    return conn


def _now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


# ── Overview / Analytics ─────────────────────────────────────────────────────

@router.get("/overview")
async def overview(_: bool = Depends(require_train_admin)):
    conn = _db()
    candidates = {r[0]: r[1] for r in conn.execute(
        "SELECT status, count(*) FROM training_candidates GROUP BY status"
    ).fetchall()}
    local_datasets = conn.execute("SELECT count(*) FROM dataset_versions").fetchone()[0]
    tests = conn.execute("SELECT count(*) FROM prompt_tests").fetchone()[0]
    evals = conn.execute("SELECT count(*) FROM eval_runs").fetchone()[0]

    # Latest finished evaluation → averages for the Analytics cards
    last_eval = None
    row = conn.execute(
        "SELECT results FROM eval_runs WHERE status='DONE' ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if row and row[0]:
        last_eval = json.loads(row[0]).get("summary")

    feedback = {"total": 0, "up": 0, "down": 0}
    if FEEDBACK_DB_PATH:
        try:
            fconn = sqlite3.connect(FEEDBACK_DB_PATH)
            feedback["total"] = fconn.execute("SELECT count(*) FROM feedback").fetchone()[0]
            feedback["up"] = fconn.execute(
                "SELECT count(*) FROM feedback WHERE rating='good' OR thumb='up'"
            ).fetchone()[0]
            feedback["down"] = fconn.execute(
                "SELECT count(*) FROM feedback WHERE rating='bad' OR thumb='down'"
            ).fetchone()[0]
            fconn.close()
        except Exception as e:
            feedback["error"] = type(e).__name__

    # Durable Dataset Center summary (live)
    dataset_center: Dict[str, Any] = {"reachable": False}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{HF_ML_URL}/datasets")
        if r.status_code == 200:
            ds = r.json().get("datasets", [])
            dataset_center = {
                "reachable": True,
                "datasets": len(ds),
                "total_rows": sum(d.get("total_rows", 0) for d in ds),
                "growth": [
                    {"id": d["id"], "rows": d.get("total_rows", 0),
                     "versions": d.get("versions", 0), "updated_at": d.get("updated_at")}
                    for d in ds
                ],
            }
    except Exception as e:
        dataset_center["error"] = type(e).__name__

    return {
        "candidates": candidates,
        "local_dataset_builds": local_datasets,
        "prompt_tests": tests,
        "eval_runs": evals,
        "last_eval_summary": last_eval,
        "feedback": feedback,
        "dataset_center": dataset_center,
    }


@router.get("/system")
async def system_overview(_: bool = Depends(require_train_admin)):
    """Update 59 — one call answering "is EVA healthy, and how big is it".

    Every field is measured or explicitly reported unavailable. Nothing is
    estimated: an unreachable component says so, and hardware that does not
    exist (GPU) is reported absent rather than shown as 0%.
    """
    components: List[Dict[str, Any]] = [
        {"name": "Backend API", "status": "up", "detail": "Render"}
    ]
    counts: Dict[str, Any] = {}
    quality: Dict[str, Any] = {}

    conn = _db()
    counts["candidates"] = conn.execute("SELECT count(*) FROM training_candidates").fetchone()[0]
    counts["candidates_pending"] = conn.execute(
        "SELECT count(*) FROM training_candidates WHERE status='PENDING'"
    ).fetchone()[0]
    counts["dataset_builds"] = conn.execute("SELECT count(*) FROM dataset_versions").fetchone()[0]
    counts["eval_runs"] = conn.execute("SELECT count(*) FROM eval_runs").fetchone()[0]
    counts["prompt_tests"] = conn.execute("SELECT count(*) FROM prompt_tests").fetchone()[0]

    row = conn.execute(
        "SELECT results FROM eval_runs WHERE status='DONE' ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if row and row[0]:
        quality = json.loads(row[0]).get("summary", {})

    if FEEDBACK_DB_PATH:
        try:
            fconn = sqlite3.connect(FEEDBACK_DB_PATH)
            for table, key in (("feedback", "feedback"), ("chat_history", "conversations")):
                try:
                    counts[key] = fconn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                except Exception:
                    pass
            fconn.close()
        except Exception:
            pass

    headers = {}
    if os.getenv("TRAIN_ADMIN_KEY"):
        headers["X-Train-Key"] = os.getenv("TRAIN_ADMIN_KEY", "")

    async def _get(path: str, **kw):
        async with httpx.AsyncClient(timeout=15) as client:
            return await client.get(f"{HF_ML_URL}{path}", headers=headers, **kw)

    try:
        r = await _get("/health")
        components.append({"name": "AI / RAG service", "status": "up" if r.status_code == 200 else "down",
                           "detail": "HF Space"})
    except Exception as e:
        components.append({"name": "AI / RAG service", "status": "down", "detail": type(e).__name__})

    try:
        d = (await _get("/rag/status", params={"workspace_id": "default-org"})).json()
        components.append({"name": "Vector DB (pgvector)", "status": "up" if d.get("online") else "down",
                           "detail": d.get("vector_store", "")})
        counts["embeddings"] = d.get("chunk_count", 0)
    except Exception as e:
        components.append({"name": "Vector DB (pgvector)", "status": "unknown", "detail": type(e).__name__})

    try:
        d = (await _get("/rag/stats", params={"workspace_id": "default-org"})).json()
        counts["documents"] = d.get("total_documents", 0)
        counts["chunks"] = d.get("total_chunks", 0)
    except Exception:
        pass

    try:
        ds = (await _get("/datasets")).json().get("datasets", [])
        components.append({"name": "Dataset store (Supabase)", "status": "up",
                           "detail": f"{len(ds)} datasets"})
        counts["datasets"] = len(ds)
        counts["dataset_rows"] = sum(x.get("total_rows", 0) for x in ds)
    except Exception as e:
        components.append({"name": "Dataset store (Supabase)", "status": "down", "detail": type(e).__name__})

    try:
        d = (await _get("/registry")).json()
        counts["model_versions"] = len(d.get("versions", []))
        counts["active_config"] = d.get("active_version")
    except Exception:
        pass

    try:
        jobs = (await _get("/train-jobs")).json().get("jobs", [])
        counts["training_jobs"] = len(jobs)
        counts["training_jobs_running"] = sum(
            1 for j in jobs if j.get("status") in ("RUNNING", "CREATED")
        )
    except Exception:
        pass

    for label, env in (("Groq", "GROQ_API_KEY"), ("Gemini", "GEMINI_API_KEY")):
        components.append({
            "name": f"LLM · {label}",
            "status": "up" if os.getenv(env) else "absent",
            "detail": "key configured" if os.getenv(env) else "no key",
        })

    runtime: Dict[str, Any] = {
        # No GPU exists on this stack — reported absent, never as a 0% gauge.
        "gpu": {"available": False, "detail": "CPU-only (Render free tier)"},
    }
    try:
        import psutil
        runtime["cpu_percent"] = psutil.cpu_percent(interval=0.15)
        vm = psutil.virtual_memory()
        runtime.update(memory_percent=vm.percent,
                       memory_used_mb=round(vm.used / 1048576),
                       memory_total_mb=round(vm.total / 1048576))
        du = psutil.disk_usage("/")
        runtime.update(disk_percent=du.percent, disk_free_gb=round(du.free / 1073741824, 1))
    except Exception:
        runtime["unavailable"] = "psutil not installed on this instance"

    analytics: Dict[str, Any] = {}
    try:
        from analytics.monitoring_store import analytics_dashboard as _ad
        summary = (_ad() or {}).get("summary", {})
        analytics = {k: summary.get(k, 0) for k in
                     ("total_chats", "tokens_used", "api_costs", "total_errors", "avg_duration_ms")}
    except Exception:
        pass

    return {
        "components": components, "counts": counts, "quality": quality,
        "runtime": runtime, "analytics": analytics,
        "deployment": {
            "backend_commit": os.getenv("RENDER_GIT_COMMIT", "") or os.getenv("SOURCE_VERSION", "") or "unknown",
            "ml_service": HF_ML_URL,
        },
    }


# ── Prompt Testing (multi-provider comparison) ───────────────────────────────

def _providers() -> List[Dict[str, Any]]:
    """Real availability only — a provider without a configured key is listed
    as unavailable, never faked."""
    return [
        {"id": "eva-groq-llama", "label": "EVA · Groq openai/gpt-oss-120b",
         "available": bool(os.getenv("GROQ_API_KEY"))},
        {"id": "gemini", "label": f"Gemini · {GEMINI_MODEL}",
         "available": bool(os.getenv("GEMINI_API_KEY"))},
        {"id": "openai", "label": "OpenAI · gpt-4o-mini",
         "available": bool(os.getenv("OPENAI_API_KEY"))},
        {"id": "openrouter",
         "label": "OpenRouter (" + str(len(OPENROUTER_MODELS)) + " free models)",
         "available": bool(os.getenv("OPENROUTER_API_KEY")),
         "reason": None if os.getenv("OPENROUTER_API_KEY") else "OPENROUTER_API_KEY not configured"},
        {"id": "claude", "label": "Claude", "available": bool(os.getenv("ANTHROPIC_API_KEY")),
         "reason": None if os.getenv("ANTHROPIC_API_KEY") else "ANTHROPIC_API_KEY not configured"},
        {"id": "deepseek", "label": "DeepSeek", "available": bool(os.getenv("DEEPSEEK_API_KEY")),
         "reason": None if os.getenv("DEEPSEEK_API_KEY") else "DEEPSEEK_API_KEY not configured"},
    ]


def _call_provider(pid: str, prompt: str) -> str:
    if pid == "eva-groq-llama":
        from groq import Groq
        client = Groq(api_key=os.getenv("GROQ_API_KEY", ""))
        r = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "user", "content": prompt}], max_tokens=700,
        )
        return r.choices[0].message.content or ""
    if pid == "gemini":
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GEMINI_API_KEY", ""))
        return genai.GenerativeModel(GEMINI_MODEL).generate_content(prompt).text or ""
    if pid == "openai":
        import openai
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}], max_tokens=700,
        )
        return r.choices[0].message.content or ""
    if pid == "claude":
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        r = client.messages.create(
            model="claude-sonnet-5", max_tokens=700,
            messages=[{"role": "user", "content": prompt}],
        )
        return r.content[0].text
    if pid == "deepseek":
        import openai
        client = openai.OpenAI(api_key=os.getenv("DEEPSEEK_API_KEY", ""),
                               base_url="https://api.deepseek.com")
        r = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}], max_tokens=700,
        )
        return r.choices[0].message.content or ""
    if pid == "openrouter":
        # Plain HTTP so this works whether or not the openai package is
        # installed on this instance.
        r = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY', '')}",
                "HTTP-Referer": os.getenv("PUBLIC_APP_URL", "https://eva-ai-1-9wfc.onrender.com"),
                "X-Title": "EVA AI",
            },
            # Shared free models get rate-limited upstream constantly, so send
            # OpenRouter's `models` fallback list: it routes to the first one
            # that is actually available instead of failing on a busy model.
            json={"models": OPENROUTER_MODELS[:3],   # OpenRouter caps this at 3
                  "model": OPENROUTER_MODELS[0],
                  "messages": [{"role": "user", "content": prompt}], "max_tokens": 700},
            timeout=60,
        )
        if r.status_code != 200:
            raise RuntimeError(f"{r.status_code}: {r.text[:200]}")
        return (r.json()["choices"][0]["message"]["content"] or "").strip()
    raise ValueError(f"Unknown provider {pid}")


class PromptTestBody(BaseModel):
    prompt: str
    providers: Optional[List[str]] = None  # default: every available one


@router.get("/providers")
async def providers(_: bool = Depends(require_train_admin)):
    return {"providers": _providers()}


@router.post("/prompt-test")
async def prompt_test(body: PromptTestBody, _: bool = Depends(require_train_admin)):
    prompt = (body.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")
    wanted = set(body.providers or [])
    results = []
    for p in _providers():
        if wanted and p["id"] not in wanted:
            continue
        if not p["available"]:
            results.append({**p, "skipped": True})
            continue
        t0 = time.time()
        try:
            answer = _call_provider(p["id"], prompt)
            results.append({
                "id": p["id"], "label": p["label"], "available": True,
                "answer": answer, "chars": len(answer),
                "latency_ms": int((time.time() - t0) * 1000),
            })
        except Exception as e:
            results.append({
                "id": p["id"], "label": p["label"], "available": True,
                "error": f"{type(e).__name__}: {str(e)[:200]}",
                "latency_ms": int((time.time() - t0) * 1000),
            })
    test_id = uuid.uuid4().hex[:12]
    conn = _db()
    conn.execute(
        "INSERT INTO prompt_tests (id, created_at, prompt, results) VALUES (?, ?, ?, ?)",
        (test_id, _now(), prompt, json.dumps(results, ensure_ascii=False)),
    )
    conn.commit()
    return {"id": test_id, "prompt": prompt, "results": results}


@router.get("/prompt-tests")
async def prompt_tests(
    limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
    _: bool = Depends(require_train_admin),
):
    conn = _db()
    rows = conn.execute(
        "SELECT id, created_at, prompt, results FROM prompt_tests "
        "ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset),
    ).fetchall()
    total = conn.execute("SELECT count(*) FROM prompt_tests").fetchone()[0]
    return {"total": total, "tests": [
        {"id": r[0], "created_at": r[1], "prompt": r[2], "results": json.loads(r[3])}
        for r in rows
    ]}


# ── Evaluation (golden-set replay against the LIVE /chat) ────────────────────
# Vision is intentionally absent: there is no image harness yet.

GOLDEN_SET = [
    {"q": "What is 2 + 2 * 3?", "category": "math", "expect_any": ["8"]},
    {"q": "What is the square root of 144?", "category": "math", "expect_any": ["12"]},
    {"q": "In Python, what does list.append() return?", "category": "coding", "expect_any": ["none"]},
    {"q": "Which HTTP status code means Not Found?", "category": "coding", "expect_any": ["404"]},
    {"q": "If all bloops are razzies and all razzies are lazzies, are all bloops lazzies? Answer yes or no with one reason.", "category": "reasoning", "expect_any": ["yes"]},
    {"q": "What is the capital of Australia?", "category": "reasoning", "expect_any": ["canberra"]},
    {"q": "Explain sheet metal bending.", "category": "mechanical", "expect_any": ["die", "bend", "deform"], "rag": True},
    {"q": "According to the documents, what is metal forming?", "category": "mechanical", "expect_any": ["forming", "die", "workpiece"], "rag": True},
]


def _run_evaluation(run_id: str) -> None:
    try:
        from src.security.hallucination_detector import detect_hallucination
    except Exception:
        detect_hallucination = None

    items = []
    for g in GOLDEN_SET:
        t0 = time.time()
        item = {"question": g["q"], "category": g["category"], "rag": g.get("rag", False)}
        try:
            with httpx.Client(timeout=45) as client:
                r = client.post(EVAL_CHAT_URL, json={"message": g["q"]})
            latency = int((time.time() - t0) * 1000)
            if r.status_code != 200:
                item.update({"ok": False, "error": f"HTTP {r.status_code}", "latency_ms": latency})
            else:
                d = r.json()
                answer = str(d.get("answer") or "")
                low = answer.lower()
                item.update({
                    "ok": True,
                    "latency_ms": latency,
                    "correct": any(k in low for k in g["expect_any"]),
                    "hallucination": bool(
                        detect_hallucination(answer)["hallucination_detected"]
                    ) if detect_hallucination else None,
                    "sources": len(d.get("sources") or []),
                    "cited": "[source" in low,
                    "answer_preview": answer[:200],
                })
        except Exception as e:
            item.update({"ok": False, "error": type(e).__name__,
                         "latency_ms": int((time.time() - t0) * 1000)})
        items.append(item)

    scored = [i for i in items if i.get("ok")]
    rag_items = [i for i in scored if i.get("rag")]
    summary = {
        "questions": len(items),
        "completed": len(scored),
        "accuracy": round(sum(1 for i in scored if i.get("correct")) / max(1, len(scored)), 3),
        "hallucination_rate": round(
            sum(1 for i in scored if i.get("hallucination")) / max(1, len(scored)), 3),
        "citation_accuracy": round(
            sum(1 for i in rag_items if i.get("sources", 0) > 0) / max(1, len(rag_items)), 3)
            if rag_items else None,
        "avg_latency_ms": int(sum(i.get("latency_ms", 0) for i in scored) / max(1, len(scored))),
        "by_category": {},
    }
    for cat in sorted({i["category"] for i in items}):
        cat_items = [i for i in scored if i["category"] == cat]
        summary["by_category"][cat] = {
            "total": len([i for i in items if i["category"] == cat]),
            "correct": sum(1 for i in cat_items if i.get("correct")),
        }

    conn = _db()
    conn.execute(
        "UPDATE eval_runs SET status='DONE', results=? WHERE id=?",
        (json.dumps({"summary": summary, "items": items}, ensure_ascii=False), run_id),
    )
    conn.commit()
    logger.info("[TRAINING-EVAL] run %s done accuracy=%s", run_id, summary["accuracy"])

    # Update 54: attach the summary to the ACTIVE registry config version so
    # each deployed routing config accumulates its own evidence. Best-effort:
    # no active version (404) or registry downtime never fails the run.
    try:
        headers = {}
        if os.getenv("TRAIN_ADMIN_KEY"):
            headers["X-Train-Key"] = os.getenv("TRAIN_ADMIN_KEY", "")
        with httpx.Client(timeout=20) as client:
            r = client.post(
                f"{HF_ML_URL}/registry/metrics",
                json={"summary": summary, "source": f"eval:{run_id}"},
                headers=headers,
            )
        logger.info("[TRAINING-EVAL] metrics attach -> %s", r.status_code)
    except Exception as e:
        logger.warning("[TRAINING-EVAL] metrics attach failed: %s", type(e).__name__)


@router.post("/evaluate")
async def evaluate(_: bool = Depends(require_train_admin)):
    run_id = uuid.uuid4().hex[:12]
    conn = _db()
    conn.execute(
        "INSERT INTO eval_runs (id, created_at, suite, status) VALUES (?, ?, 'core', 'RUNNING')",
        (run_id, _now()),
    )
    conn.commit()
    threading.Thread(target=_run_evaluation, args=(run_id,), daemon=True).start()
    return {"id": run_id, "status": "RUNNING", "questions": len(GOLDEN_SET)}


@router.get("/evaluations")
async def evaluations(
    limit: int = Query(20, ge=1, le=100), _: bool = Depends(require_train_admin)
):
    conn = _db()
    rows = conn.execute(
        "SELECT id, created_at, suite, status, results FROM eval_runs "
        "ORDER BY created_at DESC LIMIT ?", (limit,),
    ).fetchall()
    out = []
    for r in rows:
        entry = {"id": r[0], "created_at": r[1], "suite": r[2], "status": r[3]}
        if r[4]:
            entry["summary"] = json.loads(r[4]).get("summary")
        out.append(entry)
    return {"runs": out}


@router.get("/evaluations/{run_id}")
async def evaluation_detail(run_id: str, _: bool = Depends(require_train_admin)):
    row = _db().execute(
        "SELECT id, created_at, suite, status, results FROM eval_runs WHERE id=?", (run_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    detail = {"id": row[0], "created_at": row[1], "suite": row[2], "status": row[3]}
    if row[4]:
        detail.update(json.loads(row[4]))
    return detail


# ── Synthetic Dataset Generator ──────────────────────────────────────────────
# Generated pairs are inserted as PENDING candidates: synthetic data goes
# through the exact same human-approval gate as real conversations.

class SyntheticBody(BaseModel):
    mode: str = "manual"                 # manual | dataset
    prompt: Optional[str] = None         # manual: topic/instructions
    dataset_id: Optional[str] = None     # dataset: Dataset Center source
    version: Optional[int] = None
    count: int = 5


@router.post("/synthetic")
async def synthetic(body: SyntheticBody, _: bool = Depends(require_train_admin)):
    count = max(1, min(body.count, 10))
    if body.mode == "manual":
        if not (body.prompt or "").strip():
            raise HTTPException(status_code=400, detail="prompt required for manual mode")
        source_text = body.prompt.strip()[:4000]
        source_ref = "manual"
    elif body.mode == "dataset":
        if not body.dataset_id or not body.version:
            raise HTTPException(status_code=400, detail="dataset_id and version required")
        async with httpx.AsyncClient(timeout=30) as client:
            headers = {}
            if os.getenv("TRAIN_ADMIN_KEY"):
                headers["X-Train-Key"] = os.getenv("TRAIN_ADMIN_KEY", "")
            r = await client.get(
                f"{HF_ML_URL}/datasets/{body.dataset_id}/versions/{body.version}/preview",
                params={"limit": 20}, headers=headers,
            )
        if r.status_code != 200:
            raise HTTPException(status_code=422, detail=f"Dataset preview failed ({r.status_code})")
        rows = r.json().get("rows", [])
        source_text = "\n".join(json.dumps(x["content"], ensure_ascii=False) for x in rows)[:4000]
        source_ref = f"dataset:{body.dataset_id}:v{body.version}"
    else:
        raise HTTPException(status_code=400, detail="mode must be manual|dataset")

    gen_prompt = (
        f"Generate exactly {count} question-answer training pairs grounded in the "
        "material below. Return ONLY a JSON array like "
        '[{"question": "...", "answer": "..."}]. Questions must be answerable '
        "from the material; answers must be accurate and 1-4 sentences.\n\n"
        f"MATERIAL:\n{source_text}"
    )
    raw = _call_provider("eva-groq-llama", gen_prompt)
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        raise HTTPException(status_code=502, detail="Generator returned no JSON array")
    try:
        pairs = json.loads(match.group(0))
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="Generator JSON was unparseable")

    created, skipped = [], 0
    with _loop_lock:
        conn = _db()
        for p in pairs[:count]:
            q = str(p.get("question") or "").strip()
            a = str(p.get("answer") or "").strip()
            if len(q) < 5 or len(a) < 5:
                skipped += 1
                continue
            fp = _fingerprint(q, a)
            if conn.execute(
                "SELECT 1 FROM training_candidates WHERE fingerprint=?", (fp,)
            ).fetchone():
                skipped += 1
                continue
            cid = uuid.uuid4().hex[:16]
            conn.execute(
                "INSERT INTO training_candidates (id, created_at, user_ref, question, "
                "answer, provider, model, intent, agent, confidence, sources, "
                "fingerprint, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, _now(), f"synthetic:{source_ref}"[:80], q, a, "groq",
                 "openai/gpt-oss-120b", "synthetic", "", 0.0, "[]", fp, STATUS_PENDING),
            )
            created.append(cid)
        conn.commit()
    return {"ok": True, "created": len(created), "skipped": skipped,
            "candidate_ids": created, "source": source_ref,
            "note": "Pairs are PENDING candidates — human approval required before any dataset build."}


# ── AI Memory Builder (feedback → candidates) ────────────────────────────────

@router.get("/feedback")
async def feedback_list(
    limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0),
    _: bool = Depends(require_train_admin),
):
    if not FEEDBACK_DB_PATH:
        return {"total": 0, "feedback": [], "note": "feedback store not wired"}
    conn = sqlite3.connect(FEEDBACK_DB_PATH)
    try:
        rows = conn.execute(
            "SELECT id, created_at, user_id, question, response, rating, thumb, note, model "
            "FROM feedback ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset),
        ).fetchall()
        total = conn.execute("SELECT count(*) FROM feedback").fetchone()[0]
    finally:
        conn.close()
    return {"total": total, "feedback": [
        {"id": r[0], "created_at": r[1], "user_id": r[2], "question": r[3],
         "response": r[4], "rating": r[5], "thumb": r[6], "note": r[7], "model": r[8]}
        for r in rows
    ]}


class FeedbackToCandidateBody(BaseModel):
    feedback_id: int


@router.post("/feedback-to-candidate")
async def feedback_to_candidate(
    body: FeedbackToCandidateBody, _: bool = Depends(require_train_admin)
):
    if not FEEDBACK_DB_PATH:
        raise HTTPException(status_code=503, detail="feedback store not wired")
    fconn = sqlite3.connect(FEEDBACK_DB_PATH)
    try:
        row = fconn.execute(
            "SELECT question, response FROM feedback WHERE id=?", (body.feedback_id,)
        ).fetchone()
    finally:
        fconn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Feedback not found")
    q, a = (row[0] or "").strip(), (row[1] or "").strip()
    if not q or not a:
        raise HTTPException(status_code=422, detail="Feedback row has no question/response")
    fp = _fingerprint(q, a)
    with _loop_lock:
        conn = _db()
        if conn.execute(
            "SELECT 1 FROM training_candidates WHERE fingerprint=?", (fp,)
        ).fetchone():
            raise HTTPException(status_code=409, detail="Already exists as a candidate")
        cid = uuid.uuid4().hex[:16]
        conn.execute(
            "INSERT INTO training_candidates (id, created_at, user_ref, question, answer, "
            "provider, model, intent, agent, confidence, sources, fingerprint, status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (cid, _now(), f"feedback:{body.feedback_id}", q, a, "", "", "feedback",
             "", 0.0, "[]", fp, STATUS_PENDING),
        )
        conn.commit()
    return {"ok": True, "candidate_id": cid, "status": STATUS_PENDING}


# ── Model Registry (read-only truth; deploy/rollback = Update 54) ────────────

@router.get("/registry")
async def registry(_: bool = Depends(require_train_admin)):
    lora = {
        d: os.getenv(f"LORA_{d.upper()}_REPO", default)
        for d, default in [
            ("medical", "keshav1212/eva-medical-lora"),
            ("legal", "keshav1212/eva-legal-lora"),
            ("coding", "keshav1212/eva-coding-lora"),
            ("design", "keshav1212/eva-design-lora"),
            ("rag", "keshav1212/eva-rag-lora"),
        ]
    }
    return {
        "chat_providers": {
            "groq_llama": bool(os.getenv("GROQ_API_KEY")),
            "gemini": bool(os.getenv("GEMINI_API_KEY")),
            "openai": bool(os.getenv("OPENAI_API_KEY")),
        },
        "gemini_model": GEMINI_MODEL,
        "lora_repos": lora,
        "ml_service": HF_ML_URL,
        "embed_model": os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2"),
        "note": "Read-only registry. Versioned deploy/rollback ships with Update 54.",
    }
