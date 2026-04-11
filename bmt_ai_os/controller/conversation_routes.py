"""Conversation history API for BMT AI OS controller.

Endpoints
---------
GET    /api/v1/conversations              — list conversations (paginated)
GET    /api/v1/conversations/search       — search conversations by keyword
GET    /api/v1/conversations/{id}         — retrieve a conversation with messages
POST   /api/v1/conversations              — create a new conversation
DELETE /api/v1/conversations/{id}         — delete a conversation

Storage uses a SQLite database at the path set by the ``BMT_CONV_DB``
environment variable, defaulting to ``/tmp/bmt-conversations.db``.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

_DEFAULT_DB_PATH = "/tmp/bmt-conversations.db"
_ENV_DB_PATH = "BMT_CONV_DB"


def _db_path() -> str:
    return os.environ.get(_ENV_DB_PATH, _DEFAULT_DB_PATH)


@contextmanager
def _conn(db: str | None = None) -> Generator[sqlite3.Connection, None, None]:
    path = db or _db_path()
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _init_db(db: str | None = None) -> None:
    """Create tables if they do not exist."""
    with _conn(db) as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id          TEXT    PRIMARY KEY,
                title       TEXT    NOT NULL DEFAULT '',
                created_at  TEXT    NOT NULL,
                updated_at  TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT    NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role            TEXT    NOT NULL,
                content         TEXT    NOT NULL,
                created_at      TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_messages_conv
                ON messages(conversation_id, id);

            CREATE VIRTUAL TABLE IF NOT EXISTS conversations_fts
                USING fts5(id UNINDEXED, title, content=conversations, content_rowid=rowid);
            """
        )


# Eagerly initialise the database when the module is imported so that the
# tables exist before the first request arrives.
try:
    _init_db()
except Exception as _exc:  # pragma: no cover
    logger.warning("Could not initialise conversation DB at startup: %s", _exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_id() -> str:
    """Generate a time-sortable conversation ID."""
    return f"conv_{int(time.time() * 1000)}"


def _row_to_conversation(row: sqlite3.Row, messages: list[dict] | None = None) -> dict:
    data: dict = {
        "id": row["id"],
        "title": row["title"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if messages is not None:
        data["messages"] = messages
    return data


def _get_messages(con: sqlite3.Connection, conversation_id: str) -> list[dict]:
    rows = con.execute(
        "SELECT id, role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY id",
        (conversation_id,),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "role": r["role"],
            "content": r["content"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class MessageIn(BaseModel):
    role: str = Field(..., pattern="^(system|user|assistant)$")
    content: str = Field(..., min_length=1)


class ConversationCreate(BaseModel):
    title: str = Field(default="", max_length=500)
    messages: list[MessageIn] = Field(default_factory=list)


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class ConversationDetail(ConversationSummary):
    messages: list[dict]


class ConversationListResponse(BaseModel):
    conversations: list[ConversationSummary]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=ConversationListResponse, summary="List conversations")
async def list_conversations(
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
) -> ConversationListResponse:
    """Return a paginated list of conversations ordered by most recently updated."""
    offset = (page - 1) * page_size
    with _conn() as con:
        total: int = con.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        rows = con.execute(
            "SELECT id, title, created_at, updated_at FROM conversations"
            " ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()

    conversations = [
        ConversationSummary(
            id=r["id"],
            title=r["title"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]
    return ConversationListResponse(
        conversations=conversations,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/search", response_model=list[ConversationSummary], summary="Search conversations")
async def search_conversations(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[ConversationSummary]:
    """Full-text search over conversation titles.

    Falls back to a LIKE query when the FTS virtual table is unavailable.
    """
    with _conn() as con:
        try:
            rows = con.execute(
                """
                SELECT c.id, c.title, c.created_at, c.updated_at
                FROM conversations c
                JOIN conversations_fts fts ON c.id = fts.id
                WHERE conversations_fts MATCH ?
                ORDER BY c.updated_at DESC
                LIMIT ?
                """,
                (q, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            # FTS not available — fall back to LIKE
            rows = con.execute(
                "SELECT id, title, created_at, updated_at FROM conversations"
                " WHERE title LIKE ? ORDER BY updated_at DESC LIMIT ?",
                (f"%{q}%", limit),
            ).fetchall()

    return [
        ConversationSummary(
            id=r["id"],
            title=r["title"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]


@router.get("/{conversation_id}", response_model=ConversationDetail, summary="Get conversation")
async def get_conversation(conversation_id: str) -> ConversationDetail:
    """Return a conversation and its full message history."""
    with _conn() as con:
        row = con.execute(
            "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=404, detail=f"Conversation '{conversation_id}' not found."
            )
        messages = _get_messages(con, conversation_id)

    return ConversationDetail(
        id=row["id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        messages=messages,
    )


@router.post("", response_model=ConversationDetail, status_code=201, summary="Create conversation")
async def create_conversation(body: ConversationCreate) -> ConversationDetail:
    """Create a new conversation, optionally seeded with initial messages."""
    conv_id = _generate_id()
    now = _now_iso()

    with _conn() as con:
        con.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?,?,?,?)",
            (conv_id, body.title, now, now),
        )
        for msg in body.messages:
            con.execute(
                "INSERT INTO messages (conversation_id, role, content, created_at)"
                " VALUES (?,?,?,?)",
                (conv_id, msg.role, msg.content, now),
            )
        # Update FTS index
        try:
            con.execute(
                "INSERT OR REPLACE INTO conversations_fts(id, title) VALUES (?,?)",
                (conv_id, body.title),
            )
        except sqlite3.OperationalError:
            pass  # FTS unavailable — skip silently

        messages = _get_messages(con, conv_id)

    logger.info(
        "Created conversation %s (title=%r, messages=%d)", conv_id, body.title, len(messages)
    )
    return ConversationDetail(
        id=conv_id,
        title=body.title,
        created_at=now,
        updated_at=now,
        messages=messages,
    )


@router.delete("/{conversation_id}", status_code=204, summary="Delete conversation")
async def delete_conversation(conversation_id: str) -> None:
    """Delete a conversation and all its messages."""
    with _conn() as con:
        row = con.execute(
            "SELECT id FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=404, detail=f"Conversation '{conversation_id}' not found."
            )

        con.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        con.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        try:
            con.execute("DELETE FROM conversations_fts WHERE id = ?", (conversation_id,))
        except sqlite3.OperationalError:
            pass

    logger.info("Deleted conversation %s", conversation_id)
