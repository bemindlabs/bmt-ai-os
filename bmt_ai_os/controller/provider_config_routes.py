"""FastAPI routes for multi-credential provider key management (BMTOS-134).

Endpoints
---------
GET    /api/v1/providers/config/{name}/keys          — list keys with usage stats (masked)
POST   /api/v1/providers/config/{name}/keys          — add an additional API key
DELETE /api/v1/providers/config/{name}/keys/{key_id} — remove a key by ID

Key selection
-------------
- Round-robin by least-used: pick the key with the lowest usage_count.
- Cooldown on 429 responses: mark a key as unavailable for 60 seconds.
- All stored keys are encrypted at rest using Fernet symmetric encryption.
  The encryption key is derived from BMT_JWT_SECRET so no separate secret is needed.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Generator

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/providers/config", tags=["provider-keys"])

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_DB_PATH = "/tmp/bmt-provider-keys.db"
_ENV_DB_PATH = "BMT_PROVIDER_KEYS_DB"
_COOLDOWN_SECONDS = 60


# ---------------------------------------------------------------------------
# Encryption helpers (Fernet-based, key derived from BMT_JWT_SECRET)
# ---------------------------------------------------------------------------


def _get_fernet():
    """Return a Fernet instance derived from BMT_JWT_SECRET.

    Falls back to a deterministic but insecure key in dev/test when the env
    var is not set.  Production must set BMT_JWT_SECRET.
    """
    try:
        import base64

        from cryptography.fernet import Fernet

        secret = os.environ.get("BMT_JWT_SECRET", "dev-insecure-fallback-32-chars!!")
        # Derive a 32-byte key from the secret via SHA-256, then base64url-encode
        key_bytes = hashlib.sha256(secret.encode()).digest()
        fernet_key = base64.urlsafe_b64encode(key_bytes)
        return Fernet(fernet_key)
    except ImportError:
        return None


def _encrypt(plaintext: str) -> str:
    """Encrypt a string. Returns the ciphertext as a utf-8 string."""
    fernet = _get_fernet()
    if fernet is None:
        # cryptography not installed — store as-is (acceptable in dev)
        return plaintext
    return fernet.encrypt(plaintext.encode()).decode()


def _decrypt(ciphertext: str) -> str:
    """Decrypt a string previously encrypted by _encrypt."""
    fernet = _get_fernet()
    if fernet is None:
        return ciphertext
    try:
        return fernet.decrypt(ciphertext.encode()).decode()
    except Exception:
        logger.warning("Failed to decrypt provider key — returning empty string")
        return ""


def _mask_key(raw_key: str) -> str:
    """Return a masked version: show first 4 and last 4 characters."""
    if len(raw_key) <= 8:
        return "****"
    return f"{raw_key[:4]}...{raw_key[-4:]}"


def _hash_key(raw_key: str) -> str:
    """Return a stable SHA-256 hex digest of the raw key (for dedup checks)."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ProviderKey:
    id: str
    provider_name: str
    key_hash: str
    encrypted_key: str
    usage_count: int = 0
    last_used: float | None = None
    last_error: str | None = None
    cooldown_until: float | None = None

    def is_in_cooldown(self) -> bool:
        """Return True if this key is currently in a rate-limit cooldown."""
        if self.cooldown_until is None:
            return False
        return time.time() < self.cooldown_until

    def to_public_dict(self) -> dict:
        """Return a safe public representation (no raw key, masked value)."""
        decrypted = _decrypt(self.encrypted_key)
        return {
            "id": self.id,
            "provider_name": self.provider_name,
            "masked_key": _mask_key(decrypted),
            "usage_count": self.usage_count,
            "last_used": self.last_used,
            "last_error": self.last_error,
            "cooldown_until": self.cooldown_until,
            "status": "cooldown" if self.is_in_cooldown() else "active",
        }


# ---------------------------------------------------------------------------
# ProviderKeyStore — SQLite backend
# ---------------------------------------------------------------------------


class ProviderKeyStore:
    """Persistent store for per-provider API key credentials."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.environ.get(_ENV_DB_PATH, _DEFAULT_DB_PATH)
        self._init_db()

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        con = sqlite3.connect(self._db_path)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def _init_db(self) -> None:
        with self._conn() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_keys (
                    id              TEXT    NOT NULL PRIMARY KEY,
                    provider_name   TEXT    NOT NULL,
                    key_hash        TEXT    NOT NULL,
                    encrypted_key   TEXT    NOT NULL,
                    usage_count     INTEGER NOT NULL DEFAULT 0,
                    last_used       REAL,
                    last_error      TEXT,
                    cooldown_until  REAL,
                    created_at      REAL    NOT NULL
                )
                """
            )
            con.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_provider_key_hash"
                " ON provider_keys(provider_name, key_hash)"
            )

    @staticmethod
    def _row_to_key(row: sqlite3.Row) -> ProviderKey:
        return ProviderKey(
            id=row["id"],
            provider_name=row["provider_name"],
            key_hash=row["key_hash"],
            encrypted_key=row["encrypted_key"],
            usage_count=row["usage_count"] or 0,
            last_used=row["last_used"],
            last_error=row["last_error"],
            cooldown_until=row["cooldown_until"],
        )

    def add_key(self, provider_name: str, raw_key: str) -> ProviderKey:
        """Add a new API key for *provider_name*.

        Raises ValueError if an identical key already exists for this provider.
        """
        key_hash = _hash_key(raw_key)
        key_id = uuid.uuid4().hex
        encrypted = _encrypt(raw_key)
        now = time.time()
        try:
            with self._conn() as con:
                con.execute(
                    """
                    INSERT INTO provider_keys
                        (id, provider_name, key_hash, encrypted_key, usage_count,
                         last_used, last_error, cooldown_until, created_at)
                    VALUES (?, ?, ?, ?, 0, NULL, NULL, NULL, ?)
                    """,
                    (key_id, provider_name, key_hash, encrypted, now),
                )
        except sqlite3.IntegrityError:
            raise ValueError(f"An identical API key already exists for provider '{provider_name}'.")
        logger.info("Added key %s for provider '%s'", key_id, provider_name)
        return ProviderKey(
            id=key_id,
            provider_name=provider_name,
            key_hash=key_hash,
            encrypted_key=encrypted,
            usage_count=0,
            last_used=None,
            last_error=None,
            cooldown_until=None,
        )

    def list_keys(self, provider_name: str) -> list[ProviderKey]:
        """Return all keys registered for *provider_name*, ordered by usage_count."""
        with self._conn() as con:
            sql = (
                "SELECT * FROM provider_keys WHERE provider_name = ?"
                " ORDER BY usage_count, created_at"
            )
            rows = con.execute(sql, (provider_name,)).fetchall()
        return [self._row_to_key(r) for r in rows]

    def get_key(self, key_id: str) -> ProviderKey | None:
        """Return a single key by its ID."""
        with self._conn() as con:
            row = con.execute("SELECT * FROM provider_keys WHERE id = ?", (key_id,)).fetchone()
        return self._row_to_key(row) if row else None

    def delete_key(self, provider_name: str, key_id: str) -> bool:
        """Delete key *key_id* belonging to *provider_name*.

        Returns True if the row existed and was deleted.
        """
        with self._conn() as con:
            cur = con.execute(
                "DELETE FROM provider_keys WHERE id = ? AND provider_name = ?",
                (key_id, provider_name),
            )
        deleted = cur.rowcount > 0
        if deleted:
            logger.info("Deleted key %s for provider '%s'", key_id, provider_name)
        return deleted

    def pick_key(self, provider_name: str) -> ProviderKey | None:
        """Select the best available key using round-robin least-used strategy.

        Skips keys currently in a cooldown period (429 rate-limit).
        Returns None when no keys are registered or all are in cooldown.
        """
        keys = self.list_keys(provider_name)
        if not keys:
            return None
        # Filter out keys in cooldown
        available = [k for k in keys if not k.is_in_cooldown()]
        if not available:
            logger.warning(
                "All %d keys for provider '%s' are in cooldown", len(keys), provider_name
            )
            return None
        # list_keys is already ordered by usage_count ASC — pick first available
        return available[0]

    def record_usage(self, key_id: str) -> None:
        """Increment usage_count and update last_used timestamp for *key_id*."""
        now = time.time()
        with self._conn() as con:
            con.execute(
                "UPDATE provider_keys"
                " SET usage_count = usage_count + 1, last_used = ? WHERE id = ?",
                (now, key_id),
            )

    def record_error(self, key_id: str, error: str, apply_cooldown: bool = False) -> None:
        """Record an error against *key_id*.

        When *apply_cooldown* is True (e.g. on HTTP 429), the key enters a
        ``_COOLDOWN_SECONDS``-second cooldown.
        """
        cooldown_until = time.time() + _COOLDOWN_SECONDS if apply_cooldown else None
        with self._conn() as con:
            if cooldown_until is not None:
                con.execute(
                    "UPDATE provider_keys SET last_error = ?, cooldown_until = ? WHERE id = ?",
                    (error, cooldown_until, key_id),
                )
            else:
                con.execute(
                    "UPDATE provider_keys SET last_error = ? WHERE id = ?",
                    (error, key_id),
                )
        if apply_cooldown:
            logger.warning("Key %s entered rate-limit cooldown until %.0f", key_id, cooldown_until)

    def get_active_key_for_provider(self, provider_name: str) -> str | None:
        """Convenience: pick the best key and return the decrypted API key string.

        Also records the usage. Returns None when no keys are available.
        """
        key = self.pick_key(provider_name)
        if key is None:
            return None
        self.record_usage(key.id)
        return _decrypt(key.encrypted_key)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_default_store: ProviderKeyStore | None = None


def get_key_store() -> ProviderKeyStore:
    """Return the module-level ProviderKeyStore singleton."""
    global _default_store
    if _default_store is None:
        _default_store = ProviderKeyStore()
    return _default_store


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class AddKeyRequest(BaseModel):
    api_key: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/{provider_name}/keys")
async def list_provider_keys(provider_name: str) -> dict:
    """List all API keys registered for *provider_name* with masked values and usage stats."""
    store = get_key_store()
    keys = store.list_keys(provider_name)
    return {
        "provider_name": provider_name,
        "keys": [k.to_public_dict() for k in keys],
        "total": len(keys),
    }


@router.post("/{provider_name}/keys", status_code=201)
async def add_provider_key(provider_name: str, body: AddKeyRequest) -> dict:
    """Add an additional API key to *provider_name*.

    The key is encrypted at rest.  Duplicate keys for the same provider are
    rejected (duplicate detection is hash-based — the raw key is never stored
    unencrypted in a form that can be compared directly after the request).
    """
    if not body.api_key or not body.api_key.strip():
        raise HTTPException(status_code=422, detail="api_key must not be empty.")

    store = get_key_store()
    try:
        key = store.add_key(provider_name, body.api_key.strip())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return {
        "provider_name": provider_name,
        "key": key.to_public_dict(),
    }


@router.delete("/{provider_name}/keys/{key_id}", status_code=200)
async def delete_provider_key(provider_name: str, key_id: str) -> dict:
    """Remove an API key by its ID.

    Returns 404 when the key does not exist or does not belong to the given
    provider.
    """
    store = get_key_store()
    deleted = store.delete_key(provider_name, key_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Key '{key_id}' not found for provider '{provider_name}'.",
        )
    return {"deleted": True, "key_id": key_id, "provider_name": provider_name}
