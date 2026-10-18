"""Chat history: threads and their messages, in SQLite.

A thread belongs to the hub user that created it (``x-qfz-user``; ``None`` for
direct local use) and is only visible to that user. A message is one user turn
or one assistant turn. An assistant turn keeps its *steps* in order: each model
call's text and the tool calls it made, with inputs, outputs and timings; the
model context is rebuilt from them (see ``context.py``), so nothing about the
conversation lives only in process memory.

Credentials are never stored: the browser sends them with each request.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,
    owner TEXT,
    title TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    model TEXT,
    api TEXT,
    as_of TEXT,
    summary TEXT,                  -- compacted summary of messages with seq <= summary_through
    summary_through INTEGER NOT NULL DEFAULT -1
);
CREATE INDEX IF NOT EXISTS threads_owner ON threads(owner, updated_at);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,            -- user | assistant
    content TEXT NOT NULL DEFAULT '',
    steps TEXT,                    -- assistant: JSON list of {text, tool_calls, started_at, ended_at, usage}
    status TEXT NOT NULL DEFAULT 'complete',   -- complete | interrupted | error
    error TEXT,
    model TEXT,
    usage TEXT,                    -- JSON {input_tokens, output_tokens}
    created_at REAL NOT NULL,
    finished_at REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS messages_seq ON messages(thread_id, seq);
"""


def default_path() -> Path:
    if os.environ.get("PLAYGROUND_DB"):
        return Path(os.environ["PLAYGROUND_DB"])
    state = os.environ.get("QFZ_STATE_DIR") or os.path.join(
        os.environ.get("QFZ_DATA_ROOT", "/data/qfinzero"), "_state")
    return Path(state) / "playground.sqlite3"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def title_from(text: str, limit: int = 48) -> str:
    line = " ".join(text.split())
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


class Store:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._con = sqlite3.connect(str(self.path), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA foreign_keys = ON")
        self._con.execute("PRAGMA journal_mode = WAL")
        self._con.executescript(SCHEMA)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    # ── threads ──────────────────────────────────────────────────────

    def create_thread(self, owner: Optional[str], title: str = "", **meta: Any) -> dict:
        now = time.time()
        tid = new_id("thr")
        with self._lock, self._con:
            self._con.execute(
                "INSERT INTO threads (id, owner, title, created_at, updated_at, model, api, as_of) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (tid, owner, title, now, now, meta.get("model"), meta.get("api"), meta.get("as_of")))
        return self.get_thread(tid, owner)  # type: ignore[return-value]

    def _visible(self, owner: Optional[str]) -> tuple[str, tuple]:
        return ("owner IS ?", (owner,))

    def get_thread(self, tid: str, owner: Optional[str]) -> Optional[dict]:
        cond, args = self._visible(owner)
        row = self._con.execute(f"SELECT * FROM threads WHERE id = ? AND {cond}", (tid, *args)).fetchone()
        return dict(row) if row else None

    def list_threads(self, owner: Optional[str], q: str = "", limit: int = 200) -> list[dict]:
        cond, args = self._visible(owner)
        sql = (f"SELECT t.*, (SELECT count(*) FROM messages m WHERE m.thread_id = t.id) AS message_count "
               f"FROM threads t WHERE {cond}")
        params: list[Any] = list(args)
        if q:
            sql += (" AND (t.title LIKE ? OR EXISTS (SELECT 1 FROM messages m WHERE m.thread_id = t.id "
                    "AND m.content LIKE ?))")
            params += [f"%{q}%", f"%{q}%"]
        sql += " ORDER BY t.updated_at DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self._con.execute(sql, params).fetchall()]

    def update_thread(self, tid: str, owner: Optional[str], **fields: Any) -> Optional[dict]:
        allowed = {"title", "model", "api", "as_of", "summary", "summary_through"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not self.get_thread(tid, owner):
            return None
        if sets:
            cols = ", ".join(f"{k} = ?" for k in sets)
            with self._lock, self._con:
                self._con.execute(f"UPDATE threads SET {cols}, updated_at = ? WHERE id = ?",
                                  (*sets.values(), time.time(), tid))
        return self.get_thread(tid, owner)

    def delete_thread(self, tid: str, owner: Optional[str]) -> bool:
        cond, args = self._visible(owner)
        with self._lock, self._con:
            cur = self._con.execute(f"DELETE FROM threads WHERE id = ? AND {cond}", (tid, *args))
        return cur.rowcount > 0

    # ── messages ─────────────────────────────────────────────────────

    def add_message(self, tid: str, role: str, content: str = "", **fields: Any) -> dict:
        now = time.time()
        mid = fields.get("id") or new_id("msg")
        with self._lock, self._con:
            seq = self._con.execute("SELECT coalesce(max(seq), -1) + 1 FROM messages WHERE thread_id = ?",
                                    (tid,)).fetchone()[0]
            self._con.execute(
                "INSERT INTO messages (id, thread_id, seq, role, content, steps, status, error, model, usage, "
                "created_at, finished_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (mid, tid, seq, role, content, json.dumps(fields["steps"]) if fields.get("steps") is not None else None,
                 fields.get("status", "complete"), fields.get("error"), fields.get("model"),
                 json.dumps(fields["usage"]) if fields.get("usage") else None,
                 fields.get("created_at", now), fields.get("finished_at", now)))
            self._con.execute("UPDATE threads SET updated_at = ? WHERE id = ?", (now, tid))
        return self.get_message(mid)  # type: ignore[return-value]

    def get_message(self, mid: str) -> Optional[dict]:
        row = self._con.execute("SELECT * FROM messages WHERE id = ?", (mid,)).fetchone()
        return _msg(row) if row else None

    def messages(self, tid: str) -> list[dict]:
        rows = self._con.execute("SELECT * FROM messages WHERE thread_id = ? ORDER BY seq", (tid,)).fetchall()
        return [_msg(r) for r in rows]

    def close(self) -> None:
        self._con.close()


def _msg(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["steps"] = json.loads(d["steps"]) if d.get("steps") else []
    d["usage"] = json.loads(d["usage"]) if d.get("usage") else None
    return d
