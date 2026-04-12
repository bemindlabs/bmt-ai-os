"""FastAPI routes for multi-credential provider key management (BMTOS-134).

Endpoints
---------
GET    /api/v1/providers/config/{name}/keys          -- list keys with usage stats (masked)
POST   /api/v1/providers/config/{name}/keys          -- add an API key, OAuth token, or bearer token
DELETE /api/v1/providers/config/{name}/keys/{key_id} -- remove a key by ID
POST   /api/v1/providers/config/{name}/oauth/start   -- start OAuth flow (returns auth URL)
POST   /api/v1/providers/config/{name}/oauth/callback -- exchange OAuth authorization code
GET    /api/v1/providers/config/{name}/oauth/status   -- check OAuth credential status

Credential types
----------------
- ``api_key``  -- traditional API key (e.g. sk-ant-..., sk-proj-...)
- ``oauth``    -- OAuth 2.0 access/refresh token pair (auto-refreshable)
- ``token``    -- static bearer / personal-access token (not refreshable)

Key selection
-------------
- Round-robin by least-used: pick the key with the lowest usage_count.
- Cooldown on 429 responses: mark a key as unavailable for 60 seconds.
- All stored keys are encrypted at rest using Fernet symmetric encryption.
  The encryption key is derived from BMT_JWT_SECRET so no separate secret is needed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generator
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/providers/config", tags=["provider-keys"])


# ---------------------------------------------------------------------------
# Credential types
# ---------------------------------------------------------------------------


class CredentialType(str, Enum):
    API_KEY = "api_key"
    OAUTH = "oauth"
    TOKEN = "token"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_DB_PATH = "/tmp/bmt-provider-keys.db"
_ENV_DB_PATH = "BMT_PROVIDER_KEYS_DB"
_COOLDOWN_SECONDS = 60
_OAUTH_STATE_TTL = 600  # 10 minutes


# ---------------------------------------------------------------------------
# OAuth provider metadata
# ---------------------------------------------------------------------------


@dataclass
class OAuthProviderMeta:
    """OAuth configuration for a cloud provider."""

    auth_url: str
    token_url: str
    scopes: list[str] = field(default_factory=list)
    client_id_env: str = ""
    client_secret_env: str = ""
    supports_pkce: bool = True


OAUTH_PROVIDERS: dict[str, OAuthProviderMeta] = {
    "google": OAuthProviderMeta(
        auth_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/generative-language"],
        client_id_env="GOOGLE_OAUTH_CLIENT_ID",
        client_secret_env="GOOGLE_OAUTH_CLIENT_SECRET",
    ),
    "gemini": OAuthProviderMeta(
        auth_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/generative-language"],
        client_id_env="GOOGLE_OAUTH_CLIENT_ID",
        client_secret_env="GOOGLE_OAUTH_CLIENT_SECRET",
    ),
    "openai": OAuthProviderMeta(
        auth_url="https://auth.openai.com/authorize",
        token_url="https://auth.openai.com/oauth/token",
        scopes=["openai.public"],
        client_id_env="OPENAI_OAUTH_CLIENT_ID",
        client_secret_env="OPENAI_OAUTH_CLIENT_SECRET",
    ),
}

# In-memory OAuth state store (state -> {provider, verifier, redirect_uri, created_at})
_oauth_state_store: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------


def _generate_pkce_pair() -> tuple[str, str]:
    """Generate a PKCE code verifier and code challenge (S256)."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return verifier, challenge


def _cleanup_expired_oauth_states() -> None:
    """Remove expired OAuth state entries."""
    now = time.time()
    expired = [k for k, v in _oauth_state_store.items() if now - v["created_at"] > _OAUTH_STATE_TTL]
    for k in expired:
        del _oauth_state_store[k]


# ---------------------------------------------------------------------------
# Encryption helpers (Fernet-based, key derived from BMT_JWT_SECRET)
# ---------------------------------------------------------------------------


def _get_fernet():
    """Return a Fernet instance derived from BMT_JWT_SECRET.

    Falls back to a deterministic but insecure key in dev/test when the env
    var is not set.  Production must set BMT_JWT_SECRET.
    """
    try:
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
        # cryptography not installed -- store as-is (acceptable in dev)
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
        logger.warning("Failed to decrypt provider key -- returning empty string")
        return ""


def _mask_key(raw_key: str) -> str:
    """Return a masked version: show first 4 and last 4 characters."""
    if len(raw_key) <= 8:
        return "****"
    return f"{raw_key[:4]}...{raw_key[-4:]}"


def _hash_key(raw_key: str) -> str:
    """Return a stable HMAC-SHA256 hex digest of the raw key (for dedup checks)."""
    return hmac.new(b"bmt-provider-key-fingerprint", raw_key.encode(), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ProviderKey:
    id: str
    provider_name: str
    key_hash: str
    encrypted_key: str
    credential_type: str = "api_key"
    display_name: str = ""
    expires_at: float | None = None
    encrypted_refresh: str = ""
    usage_count: int = 0
    last_used: float | None = None
    last_error: str | None = None
    cooldown_until: float | None = None

    def is_in_cooldown(self) -> bool:
        """Return True if this key is currently in a rate-limit cooldown."""
        if self.cooldown_until is None:
            return False
        return time.time() < self.cooldown_until

    def is_expired(self) -> bool:
        """Return True if this credential has expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    def to_public_dict(self) -> dict:
        """Return a safe public representation (no raw key, masked value)."""
        decrypted = _decrypt(self.encrypted_key)
        status = "active"
        if self.is_in_cooldown():
            status = "cooldown"
        elif self.is_expired():
            status = "expired"

        result: dict[str, Any] = {
            "id": self.id,
            "provider_name": self.provider_name,
            "masked_key": _mask_key(decrypted),
            "credential_type": self.credential_type,
            "usage_count": self.usage_count,
            "last_used": self.last_used,
            "last_error": self.last_error,
            "cooldown_until": self.cooldown_until,
            "status": status,
        }
        if self.display_name:
            result["display_name"] = self.display_name
        if self.expires_at is not None:
            result["expires_at"] = self.expires_at
        return result


# ---------------------------------------------------------------------------
# ProviderKeyStore -- SQLite backend
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
                    credential_type TEXT    NOT NULL DEFAULT 'api_key',
                    display_name    TEXT    NOT NULL DEFAULT '',
                    expires_at      REAL,
                    encrypted_refresh TEXT  NOT NULL DEFAULT '',
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
            # Migrate: add new columns if upgrading from the old schema
            self._migrate_schema(con)

    def _migrate_schema(self, con: sqlite3.Connection) -> None:
        """Add columns introduced by OAuth/token support if they don't exist yet."""
        cursor = con.execute("PRAGMA table_info(provider_keys)")
        columns = {row[1] for row in cursor.fetchall()}
        migrations = {
            "credential_type": "TEXT NOT NULL DEFAULT 'api_key'",
            "display_name": "TEXT NOT NULL DEFAULT ''",
            "expires_at": "REAL",
            "encrypted_refresh": "TEXT NOT NULL DEFAULT ''",
        }
        for col, typedef in migrations.items():
            if col not in columns:
                con.execute(f"ALTER TABLE provider_keys ADD COLUMN {col} {typedef}")
                logger.info("Migrated provider_keys: added column %s", col)

    @staticmethod
    def _row_to_key(row: sqlite3.Row) -> ProviderKey:
        keys = row.keys()
        return ProviderKey(
            id=row["id"],
            provider_name=row["provider_name"],
            key_hash=row["key_hash"],
            encrypted_key=row["encrypted_key"],
            credential_type=row["credential_type"] if "credential_type" in keys else "api_key",
            display_name=row["display_name"] if "display_name" in keys else "",
            expires_at=row["expires_at"] if "expires_at" in keys else None,
            encrypted_refresh=row["encrypted_refresh"] if "encrypted_refresh" in keys else "",
            usage_count=row["usage_count"] or 0,
            last_used=row["last_used"],
            last_error=row["last_error"],
            cooldown_until=row["cooldown_until"],
        )

    def add_key(
        self,
        provider_name: str,
        raw_key: str,
        *,
        credential_type: str = "api_key",
        display_name: str = "",
        expires_at: float | None = None,
        refresh_token: str = "",
    ) -> ProviderKey:
        """Add a new credential for *provider_name*.

        Raises ValueError if an identical key already exists for this provider.
        """
        key_hash = _hash_key(raw_key)
        key_id = uuid.uuid4().hex
        encrypted = _encrypt(raw_key)
        encrypted_refresh = _encrypt(refresh_token) if refresh_token else ""
        now = time.time()
        try:
            with self._conn() as con:
                con.execute(
                    """
                    INSERT INTO provider_keys
                        (id, provider_name, key_hash, encrypted_key, credential_type,
                         display_name, expires_at, encrypted_refresh,
                         usage_count, last_used, last_error, cooldown_until, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL, NULL, ?)
                    """,
                    (
                        key_id,
                        provider_name,
                        key_hash,
                        encrypted,
                        credential_type,
                        display_name,
                        expires_at,
                        encrypted_refresh,
                        now,
                    ),
                )
        except sqlite3.IntegrityError:
            raise ValueError(
                f"An identical credential already exists for provider '{provider_name}'.",
            ) from None
        logger.info(
            "Added %s credential %s for provider '%s'",
            credential_type,
            key_id,
            provider_name,
        )
        return ProviderKey(
            id=key_id,
            provider_name=provider_name,
            key_hash=key_hash,
            encrypted_key=encrypted,
            credential_type=credential_type,
            display_name=display_name,
            expires_at=expires_at,
            encrypted_refresh=encrypted_refresh,
            usage_count=0,
            last_used=None,
            last_error=None,
            cooldown_until=None,
        )

    def update_oauth_tokens(
        self,
        key_id: str,
        access_token: str,
        refresh_token: str,
        expires_at: float,
    ) -> None:
        """Update an existing OAuth credential with refreshed tokens."""
        encrypted_access = _encrypt(access_token)
        encrypted_refresh = _encrypt(refresh_token) if refresh_token else ""
        new_hash = _hash_key(access_token)
        with self._conn() as con:
            con.execute(
                """
                UPDATE provider_keys
                SET encrypted_key = ?, encrypted_refresh = ?, expires_at = ?, key_hash = ?
                WHERE id = ?
                """,
                (encrypted_access, encrypted_refresh, expires_at, new_hash, key_id),
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

        Skips keys currently in a cooldown period (429 rate-limit) or expired.
        Returns None when no keys are registered or all are in cooldown.
        """
        keys = self.list_keys(provider_name)
        if not keys:
            return None
        # Filter out keys in cooldown or expired
        available = [k for k in keys if not k.is_in_cooldown() and not k.is_expired()]
        if not available:
            logger.warning(
                "All %d keys for provider '%s' are in cooldown or expired", len(keys), provider_name
            )
            return None
        # list_keys is already ordered by usage_count ASC -- pick first available
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
    credential_type: str = "api_key"
    display_name: str = ""


class OAuthStartRequest(BaseModel):
    redirect_uri: str
    client_id: str | None = None
    client_secret: str | None = None


class OAuthCallbackRequest(BaseModel):
    code: str
    state: str
    redirect_uri: str | None = None


# ---------------------------------------------------------------------------
# Routes -- Key CRUD
# ---------------------------------------------------------------------------


@router.get("/{provider_name}/keys")
async def list_provider_keys(provider_name: str) -> dict:
    """List all credentials registered for *provider_name* with masked values and usage stats."""
    store = get_key_store()
    keys = store.list_keys(provider_name)
    return {
        "provider_name": provider_name,
        "keys": [k.to_public_dict() for k in keys],
        "total": len(keys),
    }


@router.post("/{provider_name}/keys", status_code=201)
async def add_provider_key(provider_name: str, body: AddKeyRequest) -> dict:
    """Add a credential (API key, OAuth token, or bearer token) to *provider_name*.

    The key is encrypted at rest.  Duplicate keys for the same provider are
    rejected (duplicate detection is hash-based).
    """
    if not body.api_key or not body.api_key.strip():
        raise HTTPException(status_code=422, detail="api_key must not be empty.")

    if body.credential_type not in ("api_key", "oauth", "token"):
        raise HTTPException(
            status_code=422,
            detail="credential_type must be api_key, oauth, or token.",
        )

    store = get_key_store()
    try:
        key = store.add_key(
            provider_name,
            body.api_key.strip(),
            credential_type=body.credential_type,
            display_name=body.display_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {
        "provider_name": provider_name,
        "key": key.to_public_dict(),
    }


@router.delete("/{provider_name}/keys/{key_id}", status_code=200)
async def delete_provider_key(provider_name: str, key_id: str) -> dict:
    """Remove a credential by its ID.

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


# ---------------------------------------------------------------------------
# Routes -- OAuth
# ---------------------------------------------------------------------------


@router.post("/{provider_name}/oauth/start")
async def oauth_start(provider_name: str, body: OAuthStartRequest) -> dict:
    """Start an OAuth 2.0 authorization flow for *provider_name*.

    Returns the authorization URL the frontend should redirect the user to.
    Uses PKCE (S256) when the provider supports it.
    """
    _cleanup_expired_oauth_states()

    meta = OAUTH_PROVIDERS.get(provider_name.lower())
    if meta is None:
        raise HTTPException(
            status_code=400,
            detail=f"OAuth is not supported for provider '{provider_name}'. "
            f"Supported: {', '.join(OAUTH_PROVIDERS.keys())}",
        )

    # Resolve client credentials
    client_id = body.client_id or os.environ.get(meta.client_id_env, "")
    if not client_id:
        raise HTTPException(
            status_code=422,
            detail=f"OAuth client_id is required. Set {meta.client_id_env} or provide client_id.",
        )

    # Generate state and PKCE
    state = secrets.token_urlsafe(32)
    verifier, challenge = _generate_pkce_pair()

    # Store state for callback verification
    _oauth_state_store[state] = {
        "provider": provider_name,
        "verifier": verifier,
        "redirect_uri": body.redirect_uri,
        "client_id": client_id,
        "client_secret": body.client_secret or os.environ.get(meta.client_secret_env, ""),
        "created_at": time.time(),
    }

    # Build authorization URL
    params: dict[str, str] = {
        "client_id": client_id,
        "redirect_uri": body.redirect_uri,
        "response_type": "code",
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    if meta.scopes:
        params["scope"] = " ".join(meta.scopes)
    if meta.supports_pkce:
        params["code_challenge"] = challenge
        params["code_challenge_method"] = "S256"

    auth_url = f"{meta.auth_url}?{urlencode(params)}"

    return {
        "auth_url": auth_url,
        "state": state,
        "provider": provider_name,
    }


@router.post("/{provider_name}/oauth/callback")
async def oauth_callback(provider_name: str, body: OAuthCallbackRequest) -> dict:
    """Exchange an OAuth authorization code for access and refresh tokens.

    The tokens are encrypted and stored as an OAuth credential for the provider.
    """
    _cleanup_expired_oauth_states()

    # Verify state
    state_data = _oauth_state_store.pop(body.state, None)
    if state_data is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state.")

    if state_data["provider"].lower() != provider_name.lower():
        raise HTTPException(status_code=400, detail="OAuth state does not match provider.")

    meta = OAUTH_PROVIDERS.get(provider_name.lower())
    if meta is None:
        raise HTTPException(status_code=400, detail=f"OAuth not supported for '{provider_name}'.")

    redirect_uri = body.redirect_uri or state_data["redirect_uri"]

    # Exchange authorization code for tokens
    token_params: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": body.code,
        "redirect_uri": redirect_uri,
        "client_id": state_data["client_id"],
    }
    if state_data["client_secret"]:
        token_params["client_secret"] = state_data["client_secret"]
    if meta.supports_pkce:
        token_params["code_verifier"] = state_data["verifier"]

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                meta.token_url,
                data=token_params,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Token exchange failed: {exc}") from exc

    if resp.status_code != 200:
        detail = resp.text[:500]
        raise HTTPException(
            status_code=502,
            detail=f"Token exchange returned {resp.status_code}: {detail}",
        )

    token_data = resp.json()
    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")
    expires_in = token_data.get("expires_in", 3600)
    expires_at = time.time() + int(expires_in)
    email = token_data.get("email", "")

    if not access_token:
        raise HTTPException(status_code=502, detail="No access_token in token response.")

    # Store as an OAuth credential
    store = get_key_store()
    display_name = f"OAuth ({email})" if email else f"OAuth ({provider_name})"
    try:
        key = store.add_key(
            provider_name,
            access_token,
            credential_type="oauth",
            display_name=display_name,
            expires_at=expires_at,
            refresh_token=refresh_token,
        )
    except ValueError:
        # Token already exists -- update it
        existing_keys = store.list_keys(provider_name)
        oauth_keys = [k for k in existing_keys if k.credential_type == "oauth"]
        if oauth_keys:
            store.update_oauth_tokens(
                oauth_keys[0].id,
                access_token,
                refresh_token,
                expires_at,
            )
            key = store.get_key(oauth_keys[0].id)
            if key is None:
                raise HTTPException(
                    status_code=500, detail="Failed to update OAuth tokens."
                ) from None
        else:
            raise HTTPException(
                status_code=409, detail="OAuth credential already exists."
            ) from None

    return {
        "provider_name": provider_name,
        "credential_type": "oauth",
        "key": key.to_public_dict(),
        "expires_in": expires_in,
    }


@router.get("/{provider_name}/oauth/status")
async def oauth_status(provider_name: str) -> dict:
    """Check whether *provider_name* has a valid OAuth credential."""
    meta = OAUTH_PROVIDERS.get(provider_name.lower())
    supported = meta is not None

    # Check for configured OAuth client credentials
    has_client_config = False
    if meta:
        client_id = os.environ.get(meta.client_id_env, "")
        has_client_config = bool(client_id)

    store = get_key_store()
    keys = store.list_keys(provider_name)
    oauth_keys = [k for k in keys if k.credential_type == "oauth"]

    has_oauth = len(oauth_keys) > 0
    is_expired = all(k.is_expired() for k in oauth_keys) if oauth_keys else True

    return {
        "provider_name": provider_name,
        "oauth_supported": supported,
        "oauth_configured": has_oauth,
        "oauth_valid": has_oauth and not is_expired,
        "has_client_config": has_client_config,
        "credentials": [k.to_public_dict() for k in oauth_keys],
    }
