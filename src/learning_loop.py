"""
Update 51 — Continuous-Learning Foundation
==========================================
Chat → candidate capture → human review → versioned training dataset.

Design rules (enforced by the data model, not by convention):
  - NOTHING is trained here. This module only collects and curates data.
  - A candidate enters a dataset ONLY after a human sets status=APPROVED.
  - Capture is opt-in (per-request `learn` flag, or LEARNING_CAPTURE_DEFAULT).
  - Candidates containing PII are never stored — skipped and counted.
  - Security-flagged or failed chats are never captured.
  - Capture never raises into the chat path and never alters the response.

Storage: sqlite (learning_loop.db, project root — same pattern as the other
instance-local stores). NOTE: on Render the filesystem is ephemeral, so
candidates/datasets live until the next deploy; export datasets before
redeploying, or point LEARNING_DB_PATH / LEARNING_DATASET_DIR at a disk.

Admin gating: endpoints that expose content or mutate state require the
X-Train-Key header to match env TRAIN_ADMIN_KEY. If TRAIN_ADMIN_KEY is
unset the gate is open (matches the current deployment's auth posture);
set it in Render env to lock the loop down.
"""

import hashlib
import json
import logging
import os
import random
import re
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger("EVA.learning_loop")

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("LEARNING_DB_PATH", str(ROOT_DIR / "learning_loop.db")))
DATASET_DIR = Path(os.getenv("LEARNING_DATASET_DIR", str(ROOT_DIR / "data" / "learning_datasets")))
CAPTURE_DEFAULT = os.getenv("LEARNING_CAPTURE_DEFAULT", "false").strip().lower() == "true"
ADMIN_KEY = os.getenv("TRAIN_ADMIN_KEY", "")

# ── Fixed outcome codes for capture logging/counters ─────────────────────────
# Log lines and counters use ONLY these constants — never free text derived
# from the prompt or the answer (same rule as the security firewall).
CAPTURE_CAPTURED = "CAPTURED"
CAPTURE_OPT_OUT = "OPT_OUT"
CAPTURE_NOT_SUCCESS = "NOT_SUCCESS"
CAPTURE_EMPTY = "EMPTY"
CAPTURE_NOT_ELIGIBLE = "NOT_ELIGIBLE"      # e.g. image chats: the image is not stored
CAPTURE_SECURITY_FLAGGED = "SECURITY_FLAGGED"
CAPTURE_PII_SKIPPED = "PII_SKIPPED"
CAPTURE_PII_UNAVAILABLE = "PII_UNAVAILABLE"
CAPTURE_DUPLICATE = "DUPLICATE"
CAPTURE_ERROR = "ERROR"

STATUS_PENDING = "PENDING"
STATUS_APPROVED = "APPROVED"
STATUS_REJECTED = "REJECTED"
STATUS_NEEDS_IMPROVEMENT = "NEEDS_IMPROVEMENT"  # Update 53: parked for editing
CANDIDATE_CHAT = "CHAT"
CANDIDATE_COGNITIVE = "COGNITIVE"
_COGNITIVE_CATEGORIES = {
    "STRATEGY_OUTCOME", "CAPABILITY_RELIABILITY", "VERIFICATION_GAP",
    "RECURRING_DEFECT", "REMEDY_EFFICACY",
}
_VALID_STATUSES = {
    STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED, STATUS_NEEDS_IMPROVEMENT
}

_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None

# In-process capture counters since restart (same lifecycle as the firewall's
# shadow counters). Persistent truth lives in the candidates table itself.
_capture_stats: Dict[str, int] = {}


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS training_candidates (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                user_ref TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                provider TEXT,
                model TEXT,
                intent TEXT,
                agent TEXT,
                confidence REAL,
                sources TEXT,
                fingerprint TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'PENDING',
                candidate_type TEXT NOT NULL DEFAULT 'CHAT',
                reviewer TEXT,
                reviewed_at TEXT,
                review_note TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dataset_versions (
                version INTEGER PRIMARY KEY,
                created_at TEXT NOT NULL,
                train_count INTEGER NOT NULL,
                val_count INTEGER NOT NULL,
                test_count INTEGER NOT NULL,
                total_examples INTEGER NOT NULL,
                approx_tokens INTEGER NOT NULL,
                dir_path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                seed INTEGER NOT NULL,
                notes TEXT
            )
            """
        )
        # Existing databases predate candidate_type; all historical rows are
        # chat examples, so the migration safely classifies them as CHAT.
        columns = {row[1] for row in conn.execute(
            "PRAGMA table_info(training_candidates)"
        ).fetchall()}
        if "candidate_type" not in columns:
            conn.execute(
                "ALTER TABLE training_candidates ADD COLUMN "
                "candidate_type TEXT NOT NULL DEFAULT 'CHAT'"
            )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_candidates_status "
            "ON training_candidates(status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_candidates_type_status "
            "ON training_candidates(candidate_type, status)"
        )
        conn.commit()
        _conn = conn
    return _conn


def _now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _fingerprint(question: str, answer: str) -> str:
    normalized = re.sub(r"\s+", " ", f"{question}||{answer}".strip().lower())
    return hashlib.sha1(normalized.encode("utf-8", errors="ignore")).hexdigest()


def _bump(code: str) -> None:
    with _lock:
        _capture_stats[code] = _capture_stats.get(code, 0) + 1


# ── Capture (called from /chat; must never raise, never mutate payload) ──────
def capture_candidate(
    question: str,
    payload: Dict[str, Any],
    user_ref: str,
    learn_flag: Optional[bool] = None,
    detect_pii_fn: Optional[Callable[[str], Dict[str, Any]]] = None,
    is_image_chat: bool = False,
) -> str:
    """Store a chat exchange as a PENDING training candidate.

    Returns one of the CAPTURE_* codes. Metadata-only logging: the code and
    the hashed user ref, never the question or the answer.
    """
    try:
        opted_in = learn_flag if learn_flag is not None else CAPTURE_DEFAULT
        if not opted_in:
            code = CAPTURE_OPT_OUT
        elif is_image_chat:
            # The image payload is not stored, so question+answer alone would
            # be misleading training data.
            code = CAPTURE_NOT_ELIGIBLE
        elif not payload.get("success", False) or payload.get("provider") == "firewall":
            code = CAPTURE_NOT_SUCCESS
        else:
            answer = str(payload.get("answer") or payload.get("response") or "").strip()
            question = (question or "").strip()
            security = payload.get("security") or {}
            if not question or not answer:
                code = CAPTURE_EMPTY
            elif security.get("inbound") or security.get("outbound"):
                code = CAPTURE_SECURITY_FLAGGED
            elif detect_pii_fn is None:
                # Fail closed: without a detector, privacy cannot be established.
                code = CAPTURE_PII_UNAVAILABLE
            elif (
                detect_pii_fn(question).get("pii_detected")
                or detect_pii_fn(answer).get("pii_detected")
            ):
                # PII never enters the training store — skip, do not redact.
                code = CAPTURE_PII_SKIPPED
            else:
                fp = _fingerprint(question, answer)
                with _lock:
                    conn = _db()
                    row = conn.execute(
                        "SELECT 1 FROM training_candidates WHERE fingerprint = ?",
                        (fp,),
                    ).fetchone()
                    if row:
                        code = CAPTURE_DUPLICATE
                    else:
                        conn.execute(
                            "INSERT INTO training_candidates "
                            "(id, created_at, user_ref, question, answer, provider, "
                            " model, intent, agent, confidence, sources, fingerprint, status) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                uuid.uuid4().hex[:16],
                                _now(),
                                user_ref or "anonymous",
                                question,
                                answer,
                                str(payload.get("provider") or ""),
                                str(payload.get("model") or ""),
                                str(payload.get("intent") or ""),
                                str((payload.get("agent") or {}).get("id") or ""),
                                float(payload.get("confidence") or 0.0),
                                json.dumps(payload.get("sources") or []),
                                fp,
                                STATUS_PENDING,
                            ),
                        )
                        conn.commit()
                        code = CAPTURE_CAPTURED
    except Exception as e:
        logger.warning("[LEARNING-CAPTURE] store failed: %s", type(e).__name__)
        code = CAPTURE_ERROR

    _bump(code)
    if code != CAPTURE_OPT_OUT:  # opt-out is the overwhelmingly common no-op
        logger.info("[LEARNING-CAPTURE] user=%s outcome=%s", user_ref or "anonymous", code)
    return code


# ── Cognitive observations (never chat-SFT examples) ─────────────────────────
def capture_cognitive_candidate(
    candidate: Dict[str, Any],
    user_ref: str = "anonymous",
    detect_pii_fn: Optional[Callable[[str], Dict[str, Any]]] = None,
    is_image_chat: bool = False,
) -> str:
    """Persist one sanitized cognitive observation as a human-review candidate.

    The cognitive engine supplies only fixed enum/key-value summaries. These
    records share the review queue but are explicitly typed COGNITIVE and are
    never eligible for chat SFT export.
    """
    try:
        if is_image_chat:
            code = CAPTURE_NOT_ELIGIBLE
        elif detect_pii_fn is None:
            code = CAPTURE_PII_UNAVAILABLE
        elif not isinstance(candidate, dict):
            code = CAPTURE_NOT_ELIGIBLE
        else:
            category = str(candidate.get("category") or "")
            summary = str(candidate.get("summary") or "").strip()
            approved = candidate.get("approved", True)
            safe_summary = re.fullmatch(
                r"[A-Za-z_]+=[A-Za-z0-9_.]+(?: [A-Za-z_]+=[A-Za-z0-9_.]+)*",
                summary,
            )
            if category not in _COGNITIVE_CATEGORIES or not summary or not safe_summary or approved is not False:
                code = CAPTURE_NOT_ELIGIBLE
            elif detect_pii_fn(f"{category} {summary}").get("pii_detected"):
                code = CAPTURE_PII_SKIPPED
            else:
                question = f"COGNITIVE_OBSERVATION:{category}"
                answer = summary
                fp = _fingerprint(CANDIDATE_COGNITIVE + "|" + question, answer)
                with _lock:
                    conn = _db()
                    row = conn.execute(
                        "SELECT 1 FROM training_candidates WHERE fingerprint = ?",
                        (fp,),
                    ).fetchone()
                    if row:
                        code = CAPTURE_DUPLICATE
                    else:
                        conn.execute(
                            "INSERT INTO training_candidates "
                            "(id, created_at, user_ref, question, answer, provider, "
                            "model, intent, agent, confidence, sources, fingerprint, "
                            "status, candidate_type) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                uuid.uuid4().hex[:16], _now(), user_ref or "anonymous",
                                question, answer, "cognitive_engine", "cognitive",
                                category.lower(), "cognitive",
                                max(0.0, min(1.0, float(candidate.get("confidence") or 0.0))),
                                "[]", fp, STATUS_PENDING, CANDIDATE_COGNITIVE,
                            ),
                        )
                        conn.commit()
                        code = CAPTURE_CAPTURED
    except Exception as e:
        logger.warning("[LEARNING-COGNITIVE] store failed: %s", type(e).__name__)
        code = CAPTURE_ERROR

    _bump(code)
    return code


# ── Admin gate ───────────────────────────────────────────────────────────────
def require_train_admin(x_train_key: Optional[str] = Header(None, alias="X-Train-Key")) -> bool:
    if not ADMIN_KEY:
        raise HTTPException(status_code=503, detail="Training admin access is disabled: TRAIN_ADMIN_KEY is not configured")
    if not x_train_key or not secrets.compare_digest(x_train_key, ADMIN_KEY):
        raise HTTPException(status_code=403, detail="X-Train-Key required")
    return True


# ── API ──────────────────────────────────────────────────────────────────────
router = APIRouter()


class RejectBody(BaseModel):
    note: str = ""


class BuildBody(BaseModel):
    val_ratio: float = 0.05
    test_ratio: float = 0.05
    min_answer_chars: int = 20
    max_example_chars: int = 32000
    seed: int = 42
    notes: str = ""


@router.get("/status")
async def train_status():
    """Metadata only — safe to expose."""
    conn = _db()
    counts = {s: 0 for s in _VALID_STATUSES}
    for status, n in conn.execute(
        "SELECT status, count(*) FROM training_candidates GROUP BY status"
    ).fetchall():
        counts[status] = n
    latest = conn.execute(
        "SELECT version, created_at, total_examples FROM dataset_versions "
        "ORDER BY version DESC LIMIT 1"
    ).fetchone()
    with _lock:
        capture = dict(_capture_stats)
    return {
        "candidates": counts,
        "capture_since_restart": capture,
        "capture_default": CAPTURE_DEFAULT,
        "admin_locked": bool(ADMIN_KEY),
        "latest_dataset": (
            {"version": latest[0], "created_at": latest[1], "total_examples": latest[2]}
            if latest else None
        ),
    }


@router.get("/candidates")
async def list_candidates(
    status: str = Query(STATUS_PENDING),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: bool = Depends(require_train_admin),
):
    status = status.upper()
    if status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(_VALID_STATUSES)}")
    conn = _db()
    rows = conn.execute(
        "SELECT id, created_at, user_ref, question, answer, provider, model, "
        "intent, confidence, sources, status, candidate_type FROM training_candidates "
        "WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (status, limit, offset),
    ).fetchall()
    total = conn.execute(
        "SELECT count(*) FROM training_candidates WHERE status = ?", (status,)
    ).fetchone()[0]
    return {
        "total": total,
        "candidates": [
            {
                "id": r[0], "created_at": r[1], "user_ref": r[2],
                "question": r[3], "answer": r[4], "provider": r[5],
                "model": r[6], "intent": r[7], "confidence": r[8],
                "sources": json.loads(r[9] or "[]"), "status": r[10],
                "candidate_type": r[11],
            }
            for r in rows
        ],
    }


def _review(candidate_id: str, new_status: str, note: str) -> Dict[str, Any]:
    with _lock:
        conn = _db()
        row = conn.execute(
            "SELECT status FROM training_candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Candidate not found")
        conn.execute(
            "UPDATE training_candidates SET status = ?, reviewer = ?, "
            "reviewed_at = ?, review_note = ? WHERE id = ?",
            (new_status, "admin", _now(), note[:500], candidate_id),
        )
        conn.commit()
    return {"ok": True, "id": candidate_id, "previous_status": row[0], "status": new_status}


@router.post("/candidates/{candidate_id}/approve")
async def approve_candidate(candidate_id: str, _: bool = Depends(require_train_admin)):
    return _review(candidate_id, STATUS_APPROVED, "")


@router.post("/candidates/{candidate_id}/reject")
async def reject_candidate(
    candidate_id: str, body: RejectBody = RejectBody(), _: bool = Depends(require_train_admin)
):
    return _review(candidate_id, STATUS_REJECTED, body.note)


@router.post("/candidates/{candidate_id}/needs-improvement")
async def needs_improvement_candidate(
    candidate_id: str, body: RejectBody = RejectBody(), _: bool = Depends(require_train_admin)
):
    """Update 53: park a candidate for editing — excluded from builds until
    it is corrected (which approves it) or approved/rejected outright."""
    return _review(candidate_id, STATUS_NEEDS_IMPROVEMENT, body.note)


class CorrectBody(BaseModel):
    answer: str
    note: str = ""


@router.post("/candidates/{candidate_id}/correct")
async def correct_candidate(
    candidate_id: str, body: CorrectBody, _: bool = Depends(require_train_admin)
):
    """Update 53: replace the answer with a human-corrected one and approve.
    The corrected text is what enters future dataset builds."""
    corrected = (body.answer or "").strip()
    if len(corrected) < 5:
        raise HTTPException(status_code=400, detail="Corrected answer too short")
    with _lock:
        conn = _db()
        row = conn.execute(
            "SELECT status, question, candidate_type FROM training_candidates WHERE id = ?",
            (candidate_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Candidate not found")
        if row[2] != CANDIDATE_CHAT:
            raise HTTPException(status_code=400, detail="Cognitive observations cannot be rewritten as chat examples")
        conn.execute(
            "UPDATE training_candidates SET answer = ?, fingerprint = ?, status = ?, "
            "reviewer = ?, reviewed_at = ?, review_note = ? WHERE id = ?",
            (corrected, _fingerprint(row[1], corrected), STATUS_APPROVED,
             "admin", _now(), ("corrected. " + body.note)[:500], candidate_id),
        )
        conn.commit()
    return {"ok": True, "id": candidate_id, "previous_status": row[0],
            "status": STATUS_APPROVED, "corrected": True}


@router.post("/dataset/build")
async def build_dataset(body: BuildBody = BuildBody(), _: bool = Depends(require_train_admin)):
    """Build the next dataset version from ALL currently-approved candidates.

    Clean → dedup → seeded shuffle → split → JSONL (chat-SFT format).
    Human approval upstream is the only path into this builder.
    """
    if body.val_ratio < 0 or body.test_ratio < 0 or body.val_ratio + body.test_ratio >= 0.9:
        raise HTTPException(status_code=400, detail="Invalid split ratios")

    conn = _db()
    rows = conn.execute(
        "SELECT id, question, answer, provider, model, intent, confidence, fingerprint "
        "FROM training_candidates WHERE status = ? AND candidate_type = ? ORDER BY created_at",
        (STATUS_APPROVED, CANDIDATE_CHAT),
    ).fetchall()

    # Clean + dedup (fingerprint is unique at capture, re-checked for safety)
    seen = set()
    examples: List[Dict[str, Any]] = []
    dropped = {"too_short": 0, "too_long": 0, "duplicate": 0}
    for cid, q, a, provider, model, intent, confidence, fp in rows:
        q, a = (q or "").strip(), (a or "").strip()
        if len(a) < body.min_answer_chars or len(q) < 3:
            dropped["too_short"] += 1
            continue
        if len(q) + len(a) > body.max_example_chars:
            dropped["too_long"] += 1
            continue
        if fp in seen:
            dropped["duplicate"] += 1
            continue
        seen.add(fp)
        examples.append({
            "messages": [
                {"role": "user", "content": q},
                {"role": "assistant", "content": a},
            ],
            "meta": {
                "candidate_id": cid, "provider": provider, "model": model,
                "intent": intent, "confidence": confidence,
            },
        })

    if not examples:
        raise HTTPException(status_code=400, detail="No approved candidates to build from")

    random.Random(body.seed).shuffle(examples)
    n = len(examples)
    n_val = int(n * body.val_ratio)
    n_test = int(n * body.test_ratio)
    splits = {
        "val": examples[:n_val],
        "test": examples[n_val:n_val + n_test],
        "train": examples[n_val + n_test:],
    }

    with _lock:
        version = (conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM dataset_versions"
        ).fetchone()[0]) + 1
        out_dir = DATASET_DIR / f"v{version}"
        out_dir.mkdir(parents=True, exist_ok=True)

        digest = hashlib.sha256()
        for split_name in ("train", "val", "test"):
            lines = "".join(
                json.dumps(ex, ensure_ascii=False) + "\n" for ex in splits[split_name]
            )
            (out_dir / f"{split_name}.jsonl").write_text(lines, encoding="utf-8")
            digest.update(lines.encode("utf-8"))

        approx_tokens = sum(
            len(m["content"]) for ex in examples for m in ex["messages"]
        ) // 4
        manifest = {
            "version": version, "created_at": _now(), "seed": body.seed,
            "counts": {k: len(v) for k, v in splits.items()},
            "total_examples": n, "approx_tokens": approx_tokens,
            "dropped": dropped, "sha256": digest.hexdigest(),
            "format": "chat-sft-jsonl", "notes": body.notes[:500],
        }
        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        conn.execute(
            "INSERT INTO dataset_versions (version, created_at, train_count, "
            "val_count, test_count, total_examples, approx_tokens, dir_path, "
            "sha256, seed, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                version, manifest["created_at"], len(splits["train"]),
                len(splits["val"]), len(splits["test"]), n, approx_tokens,
                str(out_dir), manifest["sha256"], body.seed, body.notes[:500],
            ),
        )
        conn.commit()

    logger.info("[LEARNING-DATASET] built v%d examples=%d tokens~%d", version, n, approx_tokens)

    # Update 52: push the built dataset to the durable Dataset Center on the
    # ML service (Supabase-backed), because this instance's filesystem is
    # ephemeral. Best-effort — a push failure never fails the build.
    pushed = False
    push_detail: Dict[str, Any] = {}
    try:
        import httpx
        hf_url = os.getenv("HF_ML_URL", "http://127.0.0.1:7860").rstrip("/")
        headers = {}
        if ADMIN_KEY:
            headers["X-Train-Key"] = ADMIN_KEY
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                f"{hf_url}/datasets/import/jsonl",
                json={
                    "name": "eva-conversations",
                    "records": examples,
                    "description": "Approved EVA chat exchanges (learning loop)",
                    "notes": f"backend dataset v{version}: {body.notes[:200]}",
                },
                headers=headers,
            )
        if resp.status_code == 200:
            pushed = True
            remote = resp.json()
            push_detail = {
                "dataset_id": remote.get("dataset_id"),
                "remote_version": remote.get("version"),
            }
        else:
            push_detail = {"status_code": resp.status_code}
    except Exception as e:
        push_detail = {"error": type(e).__name__}
        logger.warning("[LEARNING-DATASET] durable push failed: %s", type(e).__name__)

    return {"ok": True, **manifest, "pushed_to_dataset_center": pushed, "push_detail": push_detail}


@router.get("/datasets")
async def list_datasets():
    """Metadata only — safe to expose."""
    conn = _db()
    rows = conn.execute(
        "SELECT version, created_at, train_count, val_count, test_count, "
        "total_examples, approx_tokens, sha256, seed, notes "
        "FROM dataset_versions ORDER BY version DESC"
    ).fetchall()
    return {
        "datasets": [
            {
                "version": r[0], "created_at": r[1],
                "counts": {"train": r[2], "val": r[3], "test": r[4]},
                "total_examples": r[5], "approx_tokens": r[6],
                "sha256": r[7], "seed": r[8], "notes": r[9],
            }
            for r in rows
        ]
    }


@router.get("/datasets/{version}/preview")
async def preview_dataset(
    version: int,
    split: str = Query("train"),
    limit: int = Query(5, ge=1, le=50),
    _: bool = Depends(require_train_admin),
):
    if split not in ("train", "val", "test"):
        raise HTTPException(status_code=400, detail="split must be train|val|test")
    row = _db().execute(
        "SELECT dir_path FROM dataset_versions WHERE version = ?", (version,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Dataset version not found")
    path = Path(row[0]) / f"{split}.jsonl"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{split}.jsonl missing on this instance")
    examples = []
    with path.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if i >= limit:
                break
            examples.append(json.loads(line))
    return {"version": version, "split": split, "examples": examples}
