"""Conversation and message persistence backed by SQLite.

Tables
------
conversations
    id TEXT PRIMARY KEY
    title TEXT NOT NULL
    created_at TEXT NOT NULL   -- ISO-8601 UTC
    updated_at TEXT NOT NULL   -- ISO-8601 UTC

messages
    id TEXT PRIMARY KEY
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE
    role TEXT NOT NULL         -- "system" | "user" | "assistant"
    content TEXT NOT NULL
    created_at TEXT NOT NULL   -- ISO-8601 UTC

Configuration
-------------
DB path is read from the ``BMT_MEMORY_DB`` environment variable; when absent
the default ``/var/lib/bmt/memory.db`` is used.  The parent directory is
created automatically on first use.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# DB path resolution
# ---------------------------------------------------------------------------

_DEFAULT_DB_PATH = "/var/lib/bmt/memory.db"


def _db_path() -> Path:
    """Return the SQLite database path, honouring ``BMT_MEMORY_DB``."""
    raw = os.getenv("BMT_MEMORY_DB", _DEFAULT_DB_PATH)
    return Path(raw)


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_DDL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages (conversation_id, created_at);
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# ConversationStore
# ---------------------------------------------------------------------------


class ConversationStore:
    """Persist conversations and their messages in a local SQLite database.

    Parameters
    ----------
    db_path:
        Explicit path to the SQLite file.  Defaults to ``_db_path()`` (i.e.
        respects the ``BMT_MEMORY_DB`` env var).

    Example
    -------
    >>> store = ConversationStore()
    >>> conv = store.create_conversation("Chat about RAG")
    >>> store.add_message(conv["id"], "user", "What is RAG?")
    >>> messages = store.get_conversation(conv["id"])
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._path = Path(db_path) if db_path is not None else _db_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._apply_schema()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_schema(self) -> None:
        self._conn.executescript(_DDL)
        self._conn.commit()

    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def _commit(self) -> None:
        self._conn.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_conversation(self, title: str = "New conversation") -> dict[str, Any]:
        """Create a new conversation record and return it as a dict.

        Parameters
        ----------
        title:
            Human-readable name shown in the UI.

        Returns
        -------
        dict
            Keys: ``id``, ``title``, ``created_at``, ``updated_at``.
        """
        now = _now_iso()
        cid = _new_id()
        self._execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (cid, title, now, now),
        )
        self._commit()
        return {"id": cid, "title": title, "created_at": now, "updated_at": now}

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
    ) -> dict[str, Any]:
        """Append a message to an existing conversation.

        Parameters
        ----------
        conversation_id:
            The ``id`` of the parent conversation.
        role:
            One of ``"system"``, ``"user"``, or ``"assistant"``.
        content:
            The message body.

        Returns
        -------
        dict
            Keys: ``id``, ``conversation_id``, ``role``, ``content``,
            ``created_at``.

        Raises
        ------
        ValueError
            When *conversation_id* does not exist.
        """
        # Verify the conversation exists
        row = self._execute(
            "SELECT id FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Conversation '{conversation_id}' not found")

        now = _now_iso()
        mid = _new_id()
        self._execute(
            "INSERT INTO messages (id, conversation_id, role, content, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (mid, conversation_id, role, content, now),
        )
        # Also bump the parent conversation's updated_at
        self._execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (now, conversation_id),
        )
        self._commit()
        return {
            "id": mid,
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "created_at": now,
        }

    def get_conversation(self, conversation_id: str) -> list[dict[str, Any]]:
        """Return all messages for *conversation_id*, ordered by creation time.

        Returns an empty list when the conversation does not exist.
        """
        rows = self._execute(
            "SELECT id, conversation_id, role, content, created_at"
            " FROM messages"
            " WHERE conversation_id = ?"
            " ORDER BY created_at ASC",
            (conversation_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_conversations(self) -> list[dict[str, Any]]:
        """Return all conversations ordered by most-recently updated first."""
        rows = self._execute(
            "SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation and all its messages.

        Returns
        -------
        bool
            ``True`` if the conversation existed and was deleted, ``False``
            when no such conversation was found.
        """
        cur = self._execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        self._commit()
        return cur.rowcount > 0

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()

    # ------------------------------------------------------------------
    # Context-manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> "ConversationStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
