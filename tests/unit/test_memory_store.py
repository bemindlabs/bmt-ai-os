"""Unit tests for bmt_ai_os.memory.store (BMTOS-69)."""

from __future__ import annotations

import time

import pytest


class TestConversationStore:
    @pytest.fixture()
    def store(self, tmp_path):
        from bmt_ai_os.memory.store import ConversationStore

        with ConversationStore(db_path=tmp_path / "memory.db") as s:
            yield s

    # ------------------------------------------------------------------
    # create_conversation
    # ------------------------------------------------------------------

    def test_create_returns_dict_with_id(self, store):
        conv = store.create_conversation("Hello")
        assert "id" in conv
        assert conv["title"] == "Hello"
        assert "created_at" in conv
        assert "updated_at" in conv

    def test_create_default_title(self, store):
        conv = store.create_conversation()
        assert "New conversation" in conv["title"]

    def test_create_multiple_have_unique_ids(self, store):
        a = store.create_conversation("A")
        b = store.create_conversation("B")
        assert a["id"] != b["id"]

    # ------------------------------------------------------------------
    # add_message
    # ------------------------------------------------------------------

    def test_add_message_returns_message_dict(self, store):
        conv = store.create_conversation("Test")
        msg = store.add_message(conv["id"], "user", "Hello!")
        assert msg["role"] == "user"
        assert msg["content"] == "Hello!"
        assert msg["conversation_id"] == conv["id"]
        assert "id" in msg
        assert "created_at" in msg

    def test_add_message_updates_conversation_updated_at(self, store):
        conv = store.create_conversation("T")
        original_updated_at = conv["updated_at"]
        time.sleep(0.01)
        store.add_message(conv["id"], "user", "Hi")
        convo_list = store.list_conversations()
        found = next(c for c in convo_list if c["id"] == conv["id"])
        # updated_at should be >= original
        assert found["updated_at"] >= original_updated_at

    def test_add_message_raises_on_missing_conversation(self, store):
        with pytest.raises(ValueError, match="not found"):
            store.add_message("nonexistent-id", "user", "hi")

    def test_add_message_supports_all_roles(self, store):
        conv = store.create_conversation("roles")
        for role in ("system", "user", "assistant"):
            msg = store.add_message(conv["id"], role, f"content for {role}")
            assert msg["role"] == role

    # ------------------------------------------------------------------
    # get_conversation
    # ------------------------------------------------------------------

    def test_get_conversation_returns_messages_in_order(self, store):
        conv = store.create_conversation("Ordered")
        store.add_message(conv["id"], "user", "first")
        store.add_message(conv["id"], "assistant", "second")
        store.add_message(conv["id"], "user", "third")

        messages = store.get_conversation(conv["id"])
        assert len(messages) == 3
        assert messages[0]["content"] == "first"
        assert messages[1]["content"] == "second"
        assert messages[2]["content"] == "third"

    def test_get_conversation_returns_empty_for_missing(self, store):
        assert store.get_conversation("no-such-id") == []

    def test_get_conversation_empty_when_no_messages(self, store):
        conv = store.create_conversation("empty")
        assert store.get_conversation(conv["id"]) == []

    # ------------------------------------------------------------------
    # list_conversations
    # ------------------------------------------------------------------

    def test_list_conversations_initially_empty(self, store):
        assert store.list_conversations() == []

    def test_list_conversations_returns_all(self, store):
        store.create_conversation("A")
        store.create_conversation("B")
        store.create_conversation("C")
        result = store.list_conversations()
        assert len(result) == 3
        titles = {c["title"] for c in result}
        assert titles == {"A", "B", "C"}

    def test_list_conversations_ordered_by_updated_at_desc(self, store):
        a = store.create_conversation("A")
        store.create_conversation("B")
        # Add a message to A to make it most recently updated
        time.sleep(0.01)
        store.add_message(a["id"], "user", "bump")
        result = store.list_conversations()
        assert result[0]["id"] == a["id"]

    # ------------------------------------------------------------------
    # delete_conversation
    # ------------------------------------------------------------------

    def test_delete_returns_true_when_found(self, store):
        conv = store.create_conversation("to delete")
        assert store.delete_conversation(conv["id"]) is True

    def test_delete_returns_false_when_not_found(self, store):
        assert store.delete_conversation("ghost-id") is False

    def test_delete_removes_conversation_and_messages(self, store):
        conv = store.create_conversation("doomed")
        store.add_message(conv["id"], "user", "msg1")
        store.add_message(conv["id"], "assistant", "msg2")
        store.delete_conversation(conv["id"])

        assert store.list_conversations() == []
        assert store.get_conversation(conv["id"]) == []

    # ------------------------------------------------------------------
    # env var
    # ------------------------------------------------------------------

    def test_db_path_env_var(self, tmp_path, monkeypatch):
        db_file = str(tmp_path / "custom.db")
        monkeypatch.setenv("BMT_MEMORY_DB", db_file)
        from bmt_ai_os.memory.store import _db_path

        assert str(_db_path()) == db_file

    def test_db_path_default_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("BMT_MEMORY_DB", raising=False)
        from bmt_ai_os.memory.store import _db_path

        assert str(_db_path()) == "/var/lib/bmt/memory.db"
