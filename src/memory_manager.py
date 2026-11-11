"""
Memory Manager — Persistent user memory across sessions using SQLite.
Stores per-user conversation history + extracted facts (name, preferences, etc.)
"""

import sqlite3
import json
import os
from datetime import datetime
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory.db")

class MemoryManager:
    def __init__(self):
        self._init_db()

    def _init_db(self):
        """Create tables if they don't exist."""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS user_facts (
                user_id TEXT PRIMARY KEY,
                facts TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def add_message(self, user_id: str, role: str, content: str):
        """Store a conversation message."""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "INSERT INTO conversations (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, role, content, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()

    def get_history(self, user_id: str, last_n: int = 6) -> list:
        """Get the last N messages for a user."""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "SELECT role, content FROM conversations WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, last_n)
        )
        rows = c.fetchall()
        conn.close()
        # Return in chronological order
        return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

    def get_memory_summary(self, user_id: str) -> str:
        """Build a short memory string for the LLM prompt."""
        facts = self.get_facts(user_id)
        history = self.get_history(user_id, last_n=4)

        parts = []
        if facts:
            parts.append(f"Known facts: {json.dumps(facts)}")
        if history:
            recent = "; ".join([f"{m['role']}: {m['content'][:80]}" for m in history])
            parts.append(f"Recent chat: {recent}")

        return " | ".join(parts) if parts else ""

    def update_facts(self, user_id: str, new_facts: dict):
        """Merge new facts into existing user facts."""
        existing = self.get_facts(user_id)
        existing.update(new_facts)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO user_facts (user_id, facts, updated_at) VALUES (?, ?, ?)",
            (user_id, json.dumps(existing), datetime.now().isoformat())
        )
        conn.commit()
        conn.close()

    def get_facts(self, user_id: str) -> dict:
        """Get stored facts for a user."""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT facts FROM user_facts WHERE user_id = ?", (user_id,))
        row = c.fetchone()
        conn.close()
        if row:
            try:
                return json.loads(row[0])
            except:
                return {}
        return {}

    def extract_and_save_facts(self, user_id: str, text: str):
        """
        Simple rule-based fact extraction from user messages.
        Looks for: name, location, preferences, profession, etc.
        """
        facts = {}
        text_lower = text.lower()

        # Name detection
        for phrase in ["my name is ", "i'm ", "i am ", "call me "]:
            if phrase in text_lower:
                idx = text_lower.index(phrase) + len(phrase)
                name_candidate = text[idx:idx+30].split()[0].strip(".,!?")
                if name_candidate and name_candidate[0].isupper():
                    facts["name"] = name_candidate

        # Profession
        for phrase in ["i work as ", "i am a ", "i'm a ", "i work in "]:
            if phrase in text_lower:
                idx = text_lower.index(phrase) + len(phrase)
                profession = text[idx:idx+50].split(".")[0].strip()
                if profession:
                    facts["profession"] = profession

        # Location
        for phrase in ["i live in ", "i'm from ", "i am from ", "based in "]:
            if phrase in text_lower:
                idx = text_lower.index(phrase) + len(phrase)
                location = text[idx:idx+50].split(".")[0].strip()
                if location:
                    facts["location"] = location

        if facts:
            self.update_facts(user_id, facts)

    def clear_user_memory(self, user_id: str):
        """Clear all memory for a user (privacy/reset)."""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
        c.execute("DELETE FROM user_facts WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
