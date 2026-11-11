"""Regression tests for the typed cognitive learning queue."""
import asyncio
import json
import pytest

from src import learning_loop as ll


@pytest.fixture
def isolated_learning_db(tmp_path, monkeypatch):
    if ll._conn is not None:
        ll._conn.close()
    monkeypatch.setattr(ll, "DB_PATH", tmp_path / "learning.db")
    monkeypatch.setattr(ll, "DATASET_DIR", tmp_path / "datasets")
    monkeypatch.setattr(ll, "ADMIN_KEY", "test-admin-key")
    monkeypatch.setenv("HF_ML_URL", "http://127.0.0.1:1")
    ll._conn = None
    ll._capture_stats.clear()
    yield
    if ll._conn is not None:
        ll._conn.close()
    ll._conn = None


def no_pii(_text):
    return {"pii_detected": False}


def cognitive_candidate():
    return {
        "category": "STRATEGY_OUTCOME",
        "summary": "strategy=DIRECT category=coding outcome=VERIFIED checks_passed=1",
        "confidence": 1.0,
        "approved": False,
    }


def test_cognitive_candidate_is_pending_and_typed(isolated_learning_db):
    result = ll.capture_cognitive_candidate(cognitive_candidate(), detect_pii_fn=no_pii)
    assert result == ll.CAPTURE_CAPTURED
    row = ll._db().execute(
        "SELECT status, candidate_type, question, answer FROM training_candidates"
    ).fetchone()
    assert row[0] == ll.STATUS_PENDING
    assert row[1] == ll.CANDIDATE_COGNITIVE
    assert row[2] == "COGNITIVE_OBSERVATION:STRATEGY_OUTCOME"
    assert "outcome=VERIFIED" in row[3]


def test_cognitive_candidate_requires_pii_detector(isolated_learning_db):
    assert ll.capture_cognitive_candidate(cognitive_candidate()) == ll.CAPTURE_PII_UNAVAILABLE
    assert ll._db().execute("SELECT count(*) FROM training_candidates").fetchone()[0] == 0


def test_cognitive_candidate_rejects_pii(isolated_learning_db):
    detector = lambda _text: {"pii_detected": True}
    assert ll.capture_cognitive_candidate(cognitive_candidate(), detect_pii_fn=detector) == ll.CAPTURE_PII_SKIPPED
    assert ll._db().execute("SELECT count(*) FROM training_candidates").fetchone()[0] == 0


def test_cognitive_candidate_requires_never_approved_source(isolated_learning_db):
    candidate = cognitive_candidate()
    candidate["approved"] = True
    assert ll.capture_cognitive_candidate(candidate, detect_pii_fn=no_pii) == ll.CAPTURE_NOT_ELIGIBLE


def test_cognitive_capture_is_idempotent(isolated_learning_db):
    candidate = cognitive_candidate()
    assert ll.capture_cognitive_candidate(candidate, detect_pii_fn=no_pii) == ll.CAPTURE_CAPTURED
    assert ll.capture_cognitive_candidate(candidate, detect_pii_fn=no_pii) == ll.CAPTURE_DUPLICATE
    assert ll._db().execute("SELECT count(*) FROM training_candidates").fetchone()[0] == 1


def test_chat_capture_fails_closed_without_detector(isolated_learning_db):
    payload = {"success": True, "answer": "A sufficiently detailed answer for testing.", "provider": "test"}
    result = ll.capture_candidate("A test question", payload, "user-ref", learn_flag=True)
    assert result == ll.CAPTURE_PII_UNAVAILABLE
    assert ll._db().execute("SELECT count(*) FROM training_candidates").fetchone()[0] == 0


def test_approved_cognitive_candidate_never_enters_chat_sft(isolated_learning_db):
    cognitive = cognitive_candidate()
    assert ll.capture_cognitive_candidate(cognitive, detect_pii_fn=no_pii) == ll.CAPTURE_CAPTURED
    conn = ll._db()
    conn.execute("UPDATE training_candidates SET status = ? WHERE candidate_type = ?",
                 (ll.STATUS_APPROVED, ll.CANDIDATE_COGNITIVE))
    question, answer = "A normal chat question", "A complete answer long enough for dataset export."
    fingerprint = ll._fingerprint(question, answer)
    conn.execute(
        "INSERT INTO training_candidates "
        "(id, created_at, user_ref, question, answer, provider, model, intent, agent, "
        "confidence, sources, fingerprint, status, candidate_type) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("chat-test", ll._now(), "user-ref", question, answer, "test", "test",
         "general", "chat", 1.0, "[]", fingerprint, ll.STATUS_APPROVED, ll.CANDIDATE_CHAT),
    )
    conn.commit()

    result = asyncio.run(ll.build_dataset(ll.BuildBody(val_ratio=0, test_ratio=0)))
    assert result["total_examples"] == 1
    train_path = ll.DATASET_DIR / "v1" / "train.jsonl"
    rows = [json.loads(line) for line in train_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["meta"]["candidate_id"] == "chat-test"


def test_existing_database_rows_migrate_to_chat_type(isolated_learning_db):
    import sqlite3
    conn = sqlite3.connect(str(ll.DB_PATH))
    conn.execute(
        "CREATE TABLE training_candidates ("
        "id TEXT PRIMARY KEY, created_at TEXT NOT NULL, user_ref TEXT NOT NULL, "
        "question TEXT NOT NULL, answer TEXT NOT NULL, provider TEXT, model TEXT, "
        "intent TEXT, agent TEXT, confidence REAL, sources TEXT, "
        "fingerprint TEXT NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'PENDING', "
        "reviewer TEXT, reviewed_at TEXT, review_note TEXT)"
    )
    conn.execute(
        "INSERT INTO training_candidates "
        "(id, created_at, user_ref, question, answer, fingerprint, status) "
        "VALUES ('legacy', '2026-01-01T00:00:00Z', 'user', 'old question', "
        "'old answer', 'legacy-fingerprint', 'APPROVED')"
    )
    conn.commit()
    conn.close()
    ll._conn = None

    migrated = ll._db().execute(
        "SELECT candidate_type, status FROM training_candidates WHERE id = 'legacy'"
    ).fetchone()
    assert migrated == (ll.CANDIDATE_CHAT, ll.STATUS_APPROVED)


def test_admin_gate_fails_closed_when_key_unset(isolated_learning_db, monkeypatch):
    monkeypatch.setattr(ll, "ADMIN_KEY", "")
    with pytest.raises(ll.HTTPException) as exc:
        ll.require_train_admin("anything")
    assert exc.value.status_code == 503
