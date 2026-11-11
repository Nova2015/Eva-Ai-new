"""Tests for the "save this memory" chat command — memory-persistence fix.

The bug: typing "save this memory" produced only a chat summary and persisted
NOTHING (no intent handler; the primary RAG path saves no memory; the auto-save
would have stored the literal string "save this memory"). The fix recognises the
command and writes the REFERENCED content — the previous assistant answer, or
inline text the user gave — through the existing Memory V2 engine.

So the properties guarded here are: the command is detected (and questions about
memory are NOT), and the content that gets saved is the referenced answer, never
the command string.
"""

import os
import sys

import pytest


@pytest.fixture(scope="module")
def app_module():
    for rel in ("", "runtime_engine", "review_engine"):
        p = os.path.abspath(os.path.join(os.path.dirname(__file__), rel))
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
    try:
        import app
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"app.py not importable here: {type(exc).__name__}: {exc}")
    return app


PLAN = "Day 1: grammar. Day 2: vocabulary. Day 3: writing practice."
HISTORY = [
    {"role": "user", "content": "make me a 3 day english plan"},
    {"role": "assistant", "content": PLAN},
]


# ── A: the command is detected ───────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "save this memory", "remember this", "save to memory", "memorize this",
    "please save this to memory", "remember the plan",
    "save this conversation to memory", "add this to memory",
])
def test_save_commands_are_detected(app_module, text):
    # None means "not a command"; a str (even "") means "save".
    assert app_module._detect_save_memory_command(text) is not None


# ── B: questions and unrelated messages are NOT commands ─────────────────────
@pytest.mark.parametrize("text", [
    "how does memory work", "what did I save", "what is in my memory",
    "save this file", "tell me about the plan", "hello there",
    "what is my name", "can you show my memories",
    # Questions that DO contain the save pattern — these are what the question
    # guard exists for; without it they would be misread as save commands.
    "how do I save this to memory", "what should I save to memory",
    "how can I save this to memory",
])
def test_non_commands_are_not_detected(app_module, text):
    assert app_module._detect_save_memory_command(text) is None


# ── C: inline content vs referring to the previous answer ────────────────────
def test_a_bare_command_refers_to_the_previous_answer(app_module):
    # "" means: save the referenced previous answer, not any inline text.
    assert app_module._detect_save_memory_command("save this memory") == ""


@pytest.mark.parametrize("text,expected", [
    ("remember that my name is Keshav", "my name is Keshav"),
    ("save this memory: buy milk at 5pm", "buy milk at 5pm"),
    ("remember that I prefer dark mode", "I prefer dark mode"),
])
def test_inline_content_is_extracted(app_module, text, expected):
    assert app_module._detect_save_memory_command(text) == expected


# ── D: which conversation turn is treated as "this" ──────────────────────────
def test_last_assistant_text_picks_the_most_recent_answer(app_module):
    hist = [
        {"role": "assistant", "content": "older answer"},
        {"role": "user", "content": "and then?"},
        {"role": "assistant", "content": "the latest answer"},
    ]
    assert app_module._last_assistant_text(hist) == "the latest answer"


def test_last_assistant_text_is_empty_without_an_assistant_turn(app_module):
    assert app_module._last_assistant_text([{"role": "user", "content": "hi"}]) == ""


# ── E: what actually gets persisted (the heart of the fix) ───────────────────
class _FakeManager:
    def __init__(self):
        self.saved = None
        self.importance = None
        self.lifecycle = {}

    def upsert_user(self, *a, **k):
        pass

    def save_memory(
        self,
        user_id,
        content,
        importance=1,
        memory_type=None,
        **kwargs,
    ):
        self.saved = content
        self.importance = importance
        self.lifecycle = dict(kwargs)
        return 101   # a real id

def test_bare_command_saves_the_previous_answer_not_the_command(app_module, monkeypatch):
    mgr = _FakeManager()
    monkeypatch.setattr(app_module, "get_memory_v2", lambda: mgr)
    ack = app_module._save_memory_from_chat("u1", "", HISTORY)
    assert mgr.saved == PLAN                       # the plan, NOT "save this memory"
    assert "save this memory" not in (mgr.saved or "")
    assert mgr.importance == 4
    assert "Saved to memory" in ack


def test_inline_content_is_saved_when_given(app_module, monkeypatch):
    mgr = _FakeManager()
    monkeypatch.setattr(app_module, "get_memory_v2", lambda: mgr)
    app_module._save_memory_from_chat("u1", "my name is Keshav", HISTORY)
    assert mgr.saved == "my name is Keshav"        # inline wins over the previous answer


def test_nothing_to_save_is_reported_not_silently_dropped(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "get_memory_v2", lambda: _FakeManager())
    ack = app_module._save_memory_from_chat("u1", "", [])   # no history, no inline
    assert "nothing above to save" in ack.lower()


def test_a_rejected_save_is_reported(app_module, monkeypatch):
    class _Reject(_FakeManager):
        def save_memory(self, *a, **k):
            return None    # store rejected it (empty / looked like a secret)
    monkeypatch.setattr(app_module, "get_memory_v2", lambda: _Reject())
    ack = app_module._save_memory_from_chat("u1", "", HISTORY)
    assert "couldn't save" in ack.lower()


def test_missing_manager_is_reported(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "get_memory_v2", lambda: None)
    ack = app_module._save_memory_from_chat("u1", "", HISTORY)
    assert "unavailable" in ack.lower()


def test_a_storage_exception_never_raises(app_module, monkeypatch):
    class _Boom(_FakeManager):
        def save_memory(self, *a, **k):
            raise RuntimeError("db down")
    monkeypatch.setattr(app_module, "get_memory_v2", lambda: _Boom())
    ack = app_module._save_memory_from_chat("u1", "", HISTORY)   # must not raise
    assert "error" in ack.lower()

def test_explicit_save_command_marks_memory_as_user_confirmed(app_module, monkeypatch):
    mgr = _FakeManager()
    monkeypatch.setattr(app_module, "get_memory_v2", lambda: mgr)

    app_module._save_memory_from_chat(
        "u1",
        "my project is EVA",
        HISTORY,
    )

    assert mgr.lifecycle["memory_tier"] == "episodic"
    assert mgr.lifecycle["validation_status"] == "user_confirmed"
    assert mgr.lifecycle["provenance"] == "user_explicit"
    assert mgr.lifecycle["confidence"] == 1.0


def test_memory_lifecycle_schema_and_safe_promotion(tmp_path, monkeypatch):
    from memory import memory_store as store

    db = tmp_path / "memory.db"
    monkeypatch.setattr(store, "DB_PATH", db)

    store.init_memory_db()

    conn = store._connect()
    try:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(memories)")
        }
    finally:
        conn.close()

    assert {
        "memory_tier",
        "confidence",
        "provenance",
        "validation_status",
        "superseded_by",
        "updated_at",
    } <= columns

    rejected = store.save_memory(
        "u1",
        "semantic without confirmation",
        memory_tier="semantic",
        validation_status="unvalidated",
    )
    assert rejected is None

    memory_id = store.save_memory(
        "u1",
        "my project is EVA",
        memory_type="project",
        importance=4,
        memory_tier="episodic",
        confidence=0.7,
        provenance="user_explicit",
        validation_status="user_confirmed",
    )
    assert memory_id

    row = store.list_memories(
        "u1",
        query="project",
    )[0]

    assert row["memory_tier"] == "episodic"
    assert row["validation_status"] == "user_confirmed"
    assert row["provenance"] == "user_explicit"

    assert store.validate_memory(
        "u1",
        memory_id,
        "user_confirmed",
        1.0,
    )

    promoted = store.list_memories(
        "u1",
        query="project",
    )[0]

    assert promoted["memory_tier"] == "semantic"
    assert promoted["validation_status"] == "user_confirmed"
    assert promoted["confidence"] == 1.0


def test_superseded_memory_is_not_retrieved(tmp_path, monkeypatch):
    from memory import memory_store as store
    from memory.memory_retriever import retrieve_memory_items

    db = tmp_path / "memory.db"
    monkeypatch.setattr(store, "DB_PATH", db)

    old_id = store.save_memory(
        "u1",
        "old EVA project direction",
        memory_type="project",
        memory_tier="semantic",
        confidence=1.0,
        provenance="user_explicit",
        validation_status="user_confirmed",
    )

    new_id = store.save_memory(
        "u1",
        "new EVA project direction",
        memory_type="project",
        memory_tier="semantic",
        confidence=1.0,
        provenance="user_explicit",
        validation_status="user_confirmed",
    )

    assert old_id and new_id
    assert store.supersede_memory(
        "u1",
        old_id,
        new_id,
    )

    items = retrieve_memory_items(
        "u1",
        "EVA project direction",
        limit=8,
    )

    assert all(
        item.get("id") != old_id
        for item in items
    )