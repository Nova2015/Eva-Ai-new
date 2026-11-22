from eva_phase_common import connect_phase_db, new_id, now_iso


def init_feedback_table():
    conn = connect_phase_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS training_feedback (
            id TEXT PRIMARY KEY,
            user_id TEXT DEFAULT 'user_001',
            workspace_id TEXT DEFAULT 'default-org',
            question TEXT,
            answer TEXT,
            expected_answer TEXT,
            rating INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def record_feedback(payload):
    init_feedback_table()
    feedback_id = new_id("feedback")
    conn = connect_phase_db()
    conn.execute("""
        INSERT INTO training_feedback (
            id, user_id, workspace_id, question, answer, expected_answer, rating, notes, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        feedback_id,
        payload.get("user_id", "user_001"),
        payload.get("workspace_id", "default-org"),
        payload.get("question", ""),
        payload.get("answer", ""),
        payload.get("expected_answer", ""),
        int(payload.get("rating") or 0),
        payload.get("notes", ""),
        now_iso(),
    ))
    conn.commit()
    row = conn.execute("SELECT * FROM training_feedback WHERE id = ?", (feedback_id,)).fetchone()
    conn.close()
    return dict(row)
