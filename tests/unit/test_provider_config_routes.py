"""Unit tests for bmt_ai_os.controller.provider_config_routes (BMTOS-134).

Tests cover:
- ProviderKeyStore: add, list, delete, pick, usage/error recording
- Round-robin least-used selection
- Cooldown behaviour on rate-limit errors
- Key masking / public representation
- FastAPI endpoints via TestClient
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from bmt_ai_os.controller.provider_config_routes import (
    ProviderKeyStore,
    _decrypt,
    _encrypt,
    _hash_key,
    _mask_key,
    router,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_store(tmp_path) -> ProviderKeyStore:
    return ProviderKeyStore(db_path=str(tmp_path / "test_keys.db"))


# Minimal FastAPI app wrapping only the router under test
from fastapi import FastAPI

_app = FastAPI()
_app.include_router(router)
client = TestClient(_app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Encryption helpers
# ---------------------------------------------------------------------------


class TestEncryptionHelpers:
    def test_encrypt_decrypt_roundtrip(self):
        raw = "sk-test-abc-123"
        ciphertext = _encrypt(raw)
        assert ciphertext != raw
        assert _decrypt(ciphertext) == raw

    def test_mask_short_key(self):
        assert _mask_key("short") == "****"

    def test_mask_long_key(self):
        masked = _mask_key("sk-abcdefghijklmnop")
        assert masked.startswith("sk-a")
        assert masked.endswith("mnop")
        assert "..." in masked

    def test_hash_key_is_stable(self):
        assert _hash_key("my-key") == _hash_key("my-key")

    def test_hash_key_different_for_different_inputs(self):
        assert _hash_key("key-a") != _hash_key("key-b")


# ---------------------------------------------------------------------------
# ProviderKeyStore
# ---------------------------------------------------------------------------


class TestProviderKeyStore:
    def test_add_and_list_key(self, tmp_path):
        store = make_store(tmp_path)
        key = store.add_key("openai", "sk-test-1")
        assert key.provider_name == "openai"
        assert key.usage_count == 0
        assert key.cooldown_until is None

        keys = store.list_keys("openai")
        assert len(keys) == 1
        assert keys[0].id == key.id

    def test_list_empty_for_unknown_provider(self, tmp_path):
        store = make_store(tmp_path)
        assert store.list_keys("nonexistent") == []

    def test_add_duplicate_key_raises(self, tmp_path):
        store = make_store(tmp_path)
        store.add_key("openai", "sk-dup")
        with pytest.raises(ValueError, match="already exists"):
            store.add_key("openai", "sk-dup")

    def test_same_key_allowed_for_different_providers(self, tmp_path):
        store = make_store(tmp_path)
        store.add_key("openai", "sk-shared")
        store.add_key("groq", "sk-shared")  # should not raise
        assert len(store.list_keys("openai")) == 1
        assert len(store.list_keys("groq")) == 1

    def test_delete_key(self, tmp_path):
        store = make_store(tmp_path)
        key = store.add_key("openai", "sk-delete-me")
        deleted = store.delete_key("openai", key.id)
        assert deleted is True
        assert store.list_keys("openai") == []

    def test_delete_nonexistent_key_returns_false(self, tmp_path):
        store = make_store(tmp_path)
        assert store.delete_key("openai", "nonexistent-id") is False

    def test_delete_wrong_provider_returns_false(self, tmp_path):
        store = make_store(tmp_path)
        key = store.add_key("openai", "sk-wrong-provider")
        assert store.delete_key("groq", key.id) is False
        # Key still exists under the correct provider
        assert len(store.list_keys("openai")) == 1

    def test_record_usage_increments_count(self, tmp_path):
        store = make_store(tmp_path)
        key = store.add_key("openai", "sk-usage")
        store.record_usage(key.id)
        store.record_usage(key.id)
        updated = store.get_key(key.id)
        assert updated is not None
        assert updated.usage_count == 2
        assert updated.last_used is not None

    def test_record_error_sets_last_error(self, tmp_path):
        store = make_store(tmp_path)
        key = store.add_key("openai", "sk-error")
        store.record_error(key.id, "connection timeout")
        updated = store.get_key(key.id)
        assert updated is not None
        assert updated.last_error == "connection timeout"
        assert updated.cooldown_until is None

    def test_record_error_with_cooldown(self, tmp_path):
        store = make_store(tmp_path)
        key = store.add_key("openai", "sk-429")
        store.record_error(key.id, "rate limited", apply_cooldown=True)
        updated = store.get_key(key.id)
        assert updated is not None
        assert updated.cooldown_until is not None
        assert updated.cooldown_until > time.time()
        assert updated.is_in_cooldown() is True

    def test_is_in_cooldown_false_when_expired(self, tmp_path):
        store = make_store(tmp_path)
        key = store.add_key("openai", "sk-expired")
        # Set cooldown to already-expired timestamp
        with store._conn() as con:
            con.execute(
                "UPDATE provider_keys SET cooldown_until = ? WHERE id = ?",
                (time.time() - 1, key.id),
            )
        updated = store.get_key(key.id)
        assert updated is not None
        assert updated.is_in_cooldown() is False


# ---------------------------------------------------------------------------
# Round-robin selection
# ---------------------------------------------------------------------------


class TestPickKey:
    def test_pick_returns_none_when_no_keys(self, tmp_path):
        store = make_store(tmp_path)
        assert store.pick_key("openai") is None

    def test_pick_returns_single_key(self, tmp_path):
        store = make_store(tmp_path)
        key = store.add_key("openai", "sk-only")
        picked = store.pick_key("openai")
        assert picked is not None
        assert picked.id == key.id

    def test_pick_selects_least_used(self, tmp_path):
        store = make_store(tmp_path)
        k1 = store.add_key("openai", "sk-key-one")
        k2 = store.add_key("openai", "sk-key-two")
        # Use k1 twice
        store.record_usage(k1.id)
        store.record_usage(k1.id)
        picked = store.pick_key("openai")
        assert picked is not None
        assert picked.id == k2.id

    def test_pick_skips_keys_in_cooldown(self, tmp_path):
        store = make_store(tmp_path)
        k1 = store.add_key("openai", "sk-cooldown-key")
        k2 = store.add_key("openai", "sk-active-key")
        store.record_error(k1.id, "429", apply_cooldown=True)
        # k1 is in cooldown, so pick_key must return k2
        picked = store.pick_key("openai")
        assert picked is not None
        assert picked.id == k2.id

    def test_pick_returns_none_when_all_in_cooldown(self, tmp_path):
        store = make_store(tmp_path)
        k1 = store.add_key("openai", "sk-cd-1")
        k2 = store.add_key("openai", "sk-cd-2")
        store.record_error(k1.id, "429", apply_cooldown=True)
        store.record_error(k2.id, "429", apply_cooldown=True)
        assert store.pick_key("openai") is None

    def test_get_active_key_records_usage(self, tmp_path):
        store = make_store(tmp_path)
        store.add_key("openai", "sk-active")
        raw = store.get_active_key_for_provider("openai")
        assert raw == "sk-active"
        keys = store.list_keys("openai")
        assert keys[0].usage_count == 1

    def test_get_active_key_returns_none_when_no_keys(self, tmp_path):
        store = make_store(tmp_path)
        assert store.get_active_key_for_provider("openai") is None


# ---------------------------------------------------------------------------
# Public dict representation
# ---------------------------------------------------------------------------


class TestPublicDict:
    def test_to_public_dict_masks_key(self, tmp_path):
        store = make_store(tmp_path)
        key = store.add_key("openai", "sk-abcdefghijklmnop")
        pub = key.to_public_dict()
        assert "sk-abcdefghijklmnop" not in str(pub)
        assert pub["status"] == "active"
        assert pub["usage_count"] == 0

    def test_to_public_dict_status_cooldown(self, tmp_path):
        store = make_store(tmp_path)
        key = store.add_key("openai", "sk-429-pub")
        store.record_error(key.id, "rate limited", apply_cooldown=True)
        updated = store.get_key(key.id)
        assert updated is not None
        pub = updated.to_public_dict()
        assert pub["status"] == "cooldown"


# ---------------------------------------------------------------------------
# FastAPI endpoint tests
# ---------------------------------------------------------------------------


class TestEndpoints:
    def _fresh_router_app(self, tmp_path):
        """Return a TestClient backed by a store using a fresh DB."""
        import bmt_ai_os.controller.provider_config_routes as mod

        original = mod._default_store
        store = ProviderKeyStore(db_path=str(tmp_path / "ep_test.db"))
        mod._default_store = store
        yield TestClient(_app, raise_server_exceptions=True)
        mod._default_store = original

    def test_list_keys_empty(self, tmp_path):
        import bmt_ai_os.controller.provider_config_routes as mod

        original = mod._default_store
        mod._default_store = ProviderKeyStore(db_path=str(tmp_path / "list.db"))
        try:
            resp = client.get("/api/v1/providers/config/openai/keys")
            assert resp.status_code == 200
            body = resp.json()
            assert body["total"] == 0
            assert body["keys"] == []
        finally:
            mod._default_store = original

    def test_add_key_success(self, tmp_path):
        import bmt_ai_os.controller.provider_config_routes as mod

        original = mod._default_store
        mod._default_store = ProviderKeyStore(db_path=str(tmp_path / "add.db"))
        try:
            resp = client.post(
                "/api/v1/providers/config/openai/keys",
                json={"api_key": "sk-endpoint-test"},
            )
            assert resp.status_code == 201
            body = resp.json()
            assert body["provider_name"] == "openai"
            assert "id" in body["key"]
            assert body["key"]["status"] == "active"
            assert "sk-endpoint-test" not in str(body)
        finally:
            mod._default_store = original

    def test_add_key_empty_value_rejected(self, tmp_path):
        import bmt_ai_os.controller.provider_config_routes as mod

        original = mod._default_store
        mod._default_store = ProviderKeyStore(db_path=str(tmp_path / "empty.db"))
        try:
            resp = client.post(
                "/api/v1/providers/config/openai/keys",
                json={"api_key": "   "},
            )
            assert resp.status_code == 422
        finally:
            mod._default_store = original

    def test_add_duplicate_key_returns_409(self, tmp_path):
        import bmt_ai_os.controller.provider_config_routes as mod

        original = mod._default_store
        mod._default_store = ProviderKeyStore(db_path=str(tmp_path / "dup.db"))
        try:
            client.post(
                "/api/v1/providers/config/openai/keys",
                json={"api_key": "sk-dup-ep"},
            )
            resp = client.post(
                "/api/v1/providers/config/openai/keys",
                json={"api_key": "sk-dup-ep"},
            )
            assert resp.status_code == 409
        finally:
            mod._default_store = original

    def test_delete_key_success(self, tmp_path):
        import bmt_ai_os.controller.provider_config_routes as mod

        original = mod._default_store
        store = ProviderKeyStore(db_path=str(tmp_path / "del.db"))
        mod._default_store = store
        try:
            key = store.add_key("openai", "sk-to-delete")
            resp = client.delete(f"/api/v1/providers/config/openai/keys/{key.id}")
            assert resp.status_code == 200
            body = resp.json()
            assert body["deleted"] is True
            assert body["key_id"] == key.id
        finally:
            mod._default_store = original

    def test_delete_nonexistent_key_returns_404(self, tmp_path):
        import bmt_ai_os.controller.provider_config_routes as mod

        original = mod._default_store
        mod._default_store = ProviderKeyStore(db_path=str(tmp_path / "del404.db"))
        try:
            resp = client.delete("/api/v1/providers/config/openai/keys/no-such-id")
            assert resp.status_code == 404
        finally:
            mod._default_store = original

    def test_list_keys_after_add(self, tmp_path):
        import bmt_ai_os.controller.provider_config_routes as mod

        original = mod._default_store
        store = ProviderKeyStore(db_path=str(tmp_path / "list_after.db"))
        mod._default_store = store
        try:
            store.add_key("groq", "sk-groq-1")
            store.add_key("groq", "sk-groq-2")
            resp = client.get("/api/v1/providers/config/groq/keys")
            assert resp.status_code == 200
            body = resp.json()
            assert body["total"] == 2
            # Verify no raw keys are in the response
            body_str = str(body)
            assert "sk-groq-1" not in body_str
            assert "sk-groq-2" not in body_str
        finally:
            mod._default_store = original
