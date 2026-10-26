"""Local, durable conversation storage; histories are isolated by conversation ID."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class ConversationStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS turns (
                id INTEGER PRIMARY KEY, conversation_id TEXT NOT NULL, payload TEXT NOT NULL
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS turns_conversation ON turns(conversation_id, id)")

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30)

    def history(self, conversation_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM turns WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
                (conversation_id, limit),
            ).fetchall()
        return [json.loads(row[0]) for row in reversed(rows)]

    def context(self, conversation_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT payload FROM turns WHERE id IN (
                    SELECT id FROM turns WHERE conversation_id = ? ORDER BY id LIMIT 2
                ) OR id IN (
                    SELECT id FROM turns WHERE conversation_id = ? ORDER BY id DESC LIMIT 10
                ) ORDER BY id""",
                (conversation_id, conversation_id),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def append(self, conversation_id: str, payload: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO turns(conversation_id, payload) VALUES (?, ?)",
                       (conversation_id, json.dumps(payload)))

    def clear(self, conversation_id: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM turns WHERE conversation_id = ?", (conversation_id,))


def prompt_history(turns: list[dict[str, Any]], max_chars: int = 24000) -> list[dict[str, str]]:
    """Bound model context while retaining the opening context and recent turns."""
    selected = turns if len(turns) <= 12 else turns[:2] + turns[-10:]
    messages = []
    remaining = max_chars
    for turn in selected:
        for role, key, limit in (("user", "question", 1000), ("assistant", "answer", 1000)):
            content = str(turn[key])[:min(limit, remaining)]
            if content:
                messages.append({"role": role, "content": content})
                remaining -= len(content)
    return messages
