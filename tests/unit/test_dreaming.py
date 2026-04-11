"""Unit tests for bmt_ai_os.memory.dreaming — MemoryConsolidator."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from bmt_ai_os.memory.dreaming import (
    MemoryConsolidator,
    _build_summary,
    _extract_key_facts,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def conv_db(tmp_path):
    """Create a minimal conversation SQLite DB and return its path."""
    db = str(tmp_path / "conv.db")
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE conversations (
            id          TEXT PRIMARY KEY,
            title       TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );
        CREATE TABLE messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            role            TEXT NOT NULL,
            content         TEXT NOT NULL,
            created_at      TEXT NOT NULL
        );
        """
    )
    con.commit()
    con.close()
    return db


@pytest.fixture()
def mem_db(tmp_path):
    return str(tmp_path / "mem.db")


@pytest.fixture()
def consolidator(conv_db, mem_db):
    return MemoryConsolidator(conv_db=conv_db, mem_db=mem_db)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_conversation(db: str, conv_id: str, days_old: int = 10) -> None:
    """Insert a test conversation with a timestamp `days_old` days in the past."""
    updated = (datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat()
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?,?,?,?)",
        (conv_id, f"Title {conv_id}", updated, updated),
    )
    con.commit()
    con.close()


def _insert_message(db: str, conv_id: str, role: str, content: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?,?,?,?)",
        (conv_id, role, content, now),
    )
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# _extract_key_facts
# ---------------------------------------------------------------------------


class TestExtractKeyFacts:
    def test_empty_messages(self):
        assert _extract_key_facts([]) == []

    def test_no_signal_words(self):
        msgs = [{"role": "user", "content": "Hello there. How are you today?"}]
        # No signal words — may return empty
        result = _extract_key_facts(msgs)
        assert isinstance(result, list)

    def test_signal_word_triggers_extraction(self):
        msgs = [{"role": "user", "content": "This is important: always use HTTPS in production."}]
        facts = _extract_key_facts(msgs)
        assert len(facts) >= 1
        assert any("HTTPS" in f or "important" in f.lower() for f in facts)

    def test_caps_at_ten_facts(self):
        # Create many signal-word sentences
        content = ". ".join([f"Important fact number {i}" for i in range(20)])
        msgs = [{"role": "user", "content": content}]
        facts = _extract_key_facts(msgs)
        assert len(facts) <= 10

    def test_long_sentences_truncated(self):
        long_sentence = "This is important: " + "x" * 300
        msgs = [{"role": "user", "content": long_sentence}]
        facts = _extract_key_facts(msgs)
        for fact in facts:
            assert len(fact) <= 200


# ---------------------------------------------------------------------------
# _build_summary
# ---------------------------------------------------------------------------


class TestBuildSummary:
    def test_empty_messages_returns_placeholder(self):
        result = _build_summary("conv_001", [])
        assert "conv_001" in result
        assert "Empty" in result

    def test_single_message_included(self):
        msgs = [{"role": "user", "content": "Hello world"}]
        result = _build_summary("conv_001", msgs)
        assert "Hello world" in result
        assert "USER" in result

    def test_many_messages_summarised(self):
        msgs = [{"role": "user", "content": f"Question {i}"} for i in range(20)]
        result = _build_summary("conv_long", msgs)
        assert "conv_long" in result
        assert "20 messages" in result


# ---------------------------------------------------------------------------
# MemoryConsolidator.consolidate
# ---------------------------------------------------------------------------


class TestConsolidate:
    def test_empty_conv_db(self, consolidator):
        result = consolidator.consolidate(older_than_days=7)
        assert result.conversations_reviewed == 0
        assert result.memories_written == 0
        assert result.success

    def test_consolidates_old_conversation(self, consolidator, conv_db):
        _insert_conversation(conv_db, "conv_old", days_old=10)
        _insert_message(conv_db, "conv_old", "user", "What is BMT AI OS?")
        _insert_message(conv_db, "conv_old", "assistant", "It is an AI operating system.")

        result = consolidator.consolidate(older_than_days=7)

        assert result.conversations_reviewed == 1
        assert result.memories_written == 1
        assert result.memories_skipped == 0
        assert result.success

    def test_skips_recent_conversation(self, consolidator, conv_db):
        _insert_conversation(conv_db, "conv_recent", days_old=2)
        _insert_message(conv_db, "conv_recent", "user", "Hello")

        result = consolidator.consolidate(older_than_days=7)

        assert result.conversations_reviewed == 0
        assert result.memories_written == 0

    def test_skips_already_consolidated(self, consolidator, conv_db):
        _insert_conversation(conv_db, "conv_dup", days_old=10)
        _insert_message(conv_db, "conv_dup", "user", "Question")

        # First pass
        r1 = consolidator.consolidate(older_than_days=7)
        assert r1.memories_written == 1

        # Second pass — should skip
        r2 = consolidator.consolidate(older_than_days=7)
        assert r2.memories_skipped == 1
        assert r2.memories_written == 0

    def test_multiple_conversations(self, consolidator, conv_db):
        for i in range(3):
            _insert_conversation(conv_db, f"conv_{i:03d}", days_old=10)
            _insert_message(conv_db, f"conv_{i:03d}", "user", f"Question {i}")

        result = consolidator.consolidate(older_than_days=7)

        assert result.conversations_reviewed == 3
        assert result.memories_written == 3

    def test_handles_missing_conv_db(self, mem_db):
        consolidator = MemoryConsolidator(conv_db="/nonexistent/path.db", mem_db=mem_db)
        result = consolidator.consolidate(older_than_days=7)
        assert not result.success
        assert len(result.errors) >= 1


# ---------------------------------------------------------------------------
# MemoryConsolidator.list_memories / get_memory
# ---------------------------------------------------------------------------


class TestListAndGetMemories:
    def test_list_empty(self, consolidator):
        assert consolidator.list_memories() == []

    def test_list_after_consolidation(self, consolidator, conv_db):
        _insert_conversation(conv_db, "conv_list", days_old=10)
        _insert_message(conv_db, "conv_list", "user", "Tell me something important.")

        consolidator.consolidate(older_than_days=7)

        memories = consolidator.list_memories()
        assert len(memories) == 1
        m = memories[0]
        assert m["conversation_id"] == "conv_list"
        assert isinstance(m["key_facts"], list)
        assert isinstance(m["summary"], str)
        assert m["message_count"] == 1

    def test_get_memory_found(self, consolidator, conv_db):
        _insert_conversation(conv_db, "conv_get", days_old=10)
        _insert_message(conv_db, "conv_get", "user", "Important: always back up your data.")

        consolidator.consolidate(older_than_days=7)

        mem = consolidator.get_memory("conv_get")
        assert mem is not None
        assert mem["conversation_id"] == "conv_get"

    def test_get_memory_not_found(self, consolidator):
        result = consolidator.get_memory("conv_nonexistent")
        assert result is None
