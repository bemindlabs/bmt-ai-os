"""Memory dreaming and consolidation for BMT AI OS.

The MemoryConsolidator periodically reviews old conversations stored by the
conversation history API, extracts key facts and learnings, and stores a
compact summary in a SQLite ``consolidated_memories`` table.

Usage::

    consolidator = MemoryConsolidator(conv_db="/var/lib/bmt/conversations.db")
    result = consolidator.consolidate(older_than_days=7)
    print(result.memories_written, "new memories stored")
"""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Generator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_CONV_DB = "/tmp/bmt-conversations.db"
_DEFAULT_MEM_DB = "/tmp/bmt-memories.db"
_ENV_CONV_DB = "BMT_CONV_DB"
_ENV_MEM_DB = "BMT_MEM_DB"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ConsolidationResult:
    """Outcome of a single consolidation run."""

    conversations_reviewed: int = 0
    memories_written: int = 0
    memories_skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


@contextmanager
def _conn(path: str) -> Generator[sqlite3.Connection, None, None]:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _init_memory_db(path: str) -> None:
    """Create the consolidated_memories table if it does not exist."""
    with _conn(path) as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS consolidated_memories (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT    NOT NULL,
                summary         TEXT    NOT NULL,
                key_facts       TEXT    NOT NULL DEFAULT '[]',
                message_count   INTEGER NOT NULL DEFAULT 0,
                consolidated_at TEXT    NOT NULL,
                older_than_days INTEGER NOT NULL DEFAULT 7
            );

            CREATE INDEX IF NOT EXISTS idx_memories_conv
                ON consolidated_memories(conversation_id);

            CREATE INDEX IF NOT EXISTS idx_memories_date
                ON consolidated_memories(consolidated_at);
            """
        )


# ---------------------------------------------------------------------------
# Fact extraction
# ---------------------------------------------------------------------------


def _extract_key_facts(messages: list[dict]) -> list[str]:
    """Heuristically extract notable facts from a list of message dicts.

    This lightweight implementation looks for sentences containing
    keywords that tend to signal important information.  In production
    you would replace this with an LLM call.

    Parameters
    ----------
    messages:
        List of ``{"role": ..., "content": ...}`` dicts.

    Returns
    -------
    list[str]
        Up to 10 short fact strings.
    """
    _SIGNAL_WORDS = {
        "important",
        "remember",
        "note",
        "key",
        "critical",
        "must",
        "should",
        "always",
        "never",
        "error",
        "bug",
        "fixed",
        "learned",
        "decided",
        "conclusion",
        "result",
    }

    facts: list[str] = []
    for msg in messages:
        content: str = msg.get("content", "")
        # Split into sentences (naive — period / newline boundary)
        sentences = [s.strip() for s in content.replace("\n", ". ").split(".") if s.strip()]
        for sentence in sentences:
            words_lower = {w.strip(",:;!?\"'").lower() for w in sentence.split()}
            if words_lower & _SIGNAL_WORDS:
                facts.append(sentence[:200])  # cap at 200 chars
            if len(facts) >= 10:
                break
        if len(facts) >= 10:
            break

    return facts


def _build_summary(conversation_id: str, messages: list[dict]) -> str:
    """Build a short textual summary of a conversation.

    Parameters
    ----------
    conversation_id:
        The conversation ID (used in the summary header).
    messages:
        Ordered list of message dicts.
    """
    if not messages:
        return f"[Empty conversation {conversation_id}]"

    lines = [f"Conversation {conversation_id} ({len(messages)} messages):"]
    # Include first 3 + last 2 messages as representative samples
    sample_indices = list(range(min(3, len(messages))))
    if len(messages) > 3:
        sample_indices += [i for i in range(max(3, len(messages) - 2), len(messages))]

    for idx in dict.fromkeys(sample_indices):  # deduplicate, preserve order
        msg = messages[idx]
        role = msg.get("role", "unknown").upper()
        snippet = msg.get("content", "")[:150].replace("\n", " ")
        lines.append(f"  [{role}] {snippet}")

    if len(messages) > len(sample_indices):
        lines.append(f"  ... ({len(messages) - len(sample_indices)} more messages)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MemoryConsolidator
# ---------------------------------------------------------------------------


class MemoryConsolidator:
    """Periodically reviews old conversations and extracts consolidated memories.

    Parameters
    ----------
    conv_db:
        Path to the conversation SQLite database.  Falls back to the
        ``BMT_CONV_DB`` environment variable, then to the default temp path.
    mem_db:
        Path to the consolidated memories SQLite database.  Falls back to
        ``BMT_MEM_DB``, then to the default temp path.
    """

    def __init__(
        self,
        conv_db: str | None = None,
        mem_db: str | None = None,
    ) -> None:
        self._conv_db = conv_db or os.environ.get(_ENV_CONV_DB, _DEFAULT_CONV_DB)
        self._mem_db = mem_db or os.environ.get(_ENV_MEM_DB, _DEFAULT_MEM_DB)
        _init_memory_db(self._mem_db)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def consolidate(self, older_than_days: int = 7) -> ConsolidationResult:
        """Process conversations older than *older_than_days* days.

        For each qualifying conversation that has not yet been consolidated,
        this method:
          1. Retrieves all messages for that conversation.
          2. Extracts key facts using heuristic analysis.
          3. Builds a compact summary.
          4. Stores the result in ``consolidated_memories``.

        Parameters
        ----------
        older_than_days:
            Only consolidate conversations whose ``updated_at`` timestamp is
            older than this many days.

        Returns
        -------
        ConsolidationResult
            Statistics about the consolidation run.
        """
        result = ConsolidationResult()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()

        try:
            old_conversations = self._fetch_old_conversations(cutoff)
        except sqlite3.OperationalError as exc:
            logger.warning("Could not read conversation DB (%s): %s", self._conv_db, exc)
            result.errors.append(f"Cannot read conversation DB: {exc}")
            return result

        already_consolidated = self._fetch_consolidated_ids()

        for conv in old_conversations:
            conv_id: str = conv["id"]
            result.conversations_reviewed += 1

            if conv_id in already_consolidated:
                result.memories_skipped += 1
                logger.debug("Skipping already-consolidated conversation %s", conv_id)
                continue

            try:
                messages = self._fetch_messages(conv_id)
                self._write_memory(conv_id, messages, older_than_days)
                result.memories_written += 1
                logger.info("Consolidated conversation %s (%d messages)", conv_id, len(messages))
            except Exception as exc:
                error_msg = f"Failed to consolidate {conv_id}: {exc}"
                logger.warning(error_msg)
                result.errors.append(error_msg)

        return result

    def list_memories(self, limit: int = 50) -> list[dict]:
        """Return stored consolidated memories, newest first.

        Parameters
        ----------
        limit:
            Maximum number of memories to return.
        """
        with _conn(self._mem_db) as con:
            rows = con.execute(
                "SELECT id, conversation_id, summary, key_facts, message_count,"
                "       consolidated_at, older_than_days"
                " FROM consolidated_memories ORDER BY consolidated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

        import json

        return [
            {
                "id": r["id"],
                "conversation_id": r["conversation_id"],
                "summary": r["summary"],
                "key_facts": json.loads(r["key_facts"]),
                "message_count": r["message_count"],
                "consolidated_at": r["consolidated_at"],
                "older_than_days": r["older_than_days"],
            }
            for r in rows
        ]

    def get_memory(self, conversation_id: str) -> dict | None:
        """Return the consolidated memory for a specific conversation, or None."""
        import json

        with _conn(self._mem_db) as con:
            row = con.execute(
                "SELECT id, conversation_id, summary, key_facts, message_count,"
                "       consolidated_at, older_than_days"
                " FROM consolidated_memories WHERE conversation_id = ?"
                " ORDER BY consolidated_at DESC LIMIT 1",
                (conversation_id,),
            ).fetchone()

        if row is None:
            return None

        return {
            "id": row["id"],
            "conversation_id": row["conversation_id"],
            "summary": row["summary"],
            "key_facts": json.loads(row["key_facts"]),
            "message_count": row["message_count"],
            "consolidated_at": row["consolidated_at"],
            "older_than_days": row["older_than_days"],
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _fetch_old_conversations(self, cutoff_iso: str) -> list[sqlite3.Row]:
        """Return conversations updated before *cutoff_iso*."""
        with _conn(self._conv_db) as con:
            return con.execute(
                "SELECT id, title, updated_at FROM conversations"
                " WHERE updated_at < ? ORDER BY updated_at ASC",
                (cutoff_iso,),
            ).fetchall()

    def _fetch_consolidated_ids(self) -> set[str]:
        """Return the set of conversation IDs already in the memory store."""
        with _conn(self._mem_db) as con:
            rows = con.execute(
                "SELECT DISTINCT conversation_id FROM consolidated_memories"
            ).fetchall()
        return {r["conversation_id"] for r in rows}

    def _fetch_messages(self, conversation_id: str) -> list[dict]:
        """Return all messages for *conversation_id* as plain dicts."""
        with _conn(self._conv_db) as con:
            rows = con.execute(
                "SELECT role, content, created_at FROM messages"
                " WHERE conversation_id = ? ORDER BY id",
                (conversation_id,),
            ).fetchall()
        return [
            {"role": r["role"], "content": r["content"], "created_at": r["created_at"]}
            for r in rows
        ]

    def _write_memory(
        self, conversation_id: str, messages: list[dict], older_than_days: int
    ) -> None:
        """Persist a consolidated memory entry for *conversation_id*."""
        import json

        summary = _build_summary(conversation_id, messages)
        key_facts = _extract_key_facts(messages)
        now_iso = datetime.now(timezone.utc).isoformat()

        with _conn(self._mem_db) as con:
            con.execute(
                "INSERT INTO consolidated_memories"
                " (conversation_id, summary, key_facts, message_count,"
                "  consolidated_at, older_than_days)"
                " VALUES (?,?,?,?,?,?)",
                (
                    conversation_id,
                    summary,
                    json.dumps(key_facts),
                    len(messages),
                    now_iso,
                    older_than_days,
                ),
            )
