"""SSH key management API for BMT AI OS controller.

Endpoints
---------
POST   /api/v1/ssh-keys          — Upload an SSH private key (name + key content)
GET    /api/v1/ssh-keys          — List stored keys (no private key content returned)
DELETE /api/v1/ssh-keys/{name}   — Delete a stored key by name

Keys are stored in the same SQLite database as users (BMT_AUTH_DB).
Private key content is stored encrypted with Fernet (BMT_JWT_SECRET as
key-derivation input).  When the cryptography package is not available the key
is stored obfuscated with base64 — a best-effort fallback for minimal images.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from bmt_ai_os.controller.rate_limit import sensitive_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/ssh-keys",
    tags=["ssh-keys"],
    dependencies=[Depends(sensitive_rate_limit)],
)

_DEFAULT_DB_PATH = "/tmp/bmt-auth.db"
_ENV_DB_PATH = "BMT_AUTH_DB"
_ENV_JWT_SECRET = "BMT_JWT_SECRET"


# ---------------------------------------------------------------------------
# Encryption helpers
# ---------------------------------------------------------------------------


def _derive_fernet_key(secret: str) -> bytes:
    """Derive a 32-byte URL-safe base64 key from the JWT secret."""
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _encrypt(plaintext: str) -> str:
    """Encrypt *plaintext* using Fernet (or base64 fallback)."""
    secret = os.environ.get(_ENV_JWT_SECRET, "")
    if secret:
        try:
            from cryptography.fernet import Fernet

            f = Fernet(_derive_fernet_key(secret))
            return f.encrypt(plaintext.encode()).decode()
        except ImportError:
            pass
    # Fallback: base64 obfuscation (not encryption)
    return base64.b64encode(plaintext.encode()).decode()


def _decrypt(ciphertext: str) -> str:
    """Decrypt *ciphertext* (or decode base64 fallback)."""
    secret = os.environ.get(_ENV_JWT_SECRET, "")
    if secret:
        try:
            from cryptography.fernet import Fernet, InvalidToken

            f = Fernet(_derive_fernet_key(secret))
            try:
                return f.decrypt(ciphertext.encode()).decode()
            except InvalidToken:
                pass  # might be a base64-encoded fallback value
        except ImportError:
            pass
    # Fallback: base64 decode
    try:
        return base64.b64decode(ciphertext.encode()).decode()
    except Exception:
        return ciphertext


def _fingerprint(private_key_pem: str) -> str:
    """Return a short SHA-256 fingerprint of the key content."""
    digest = hashlib.sha256(private_key_pem.strip().encode()).digest()
    hex_pairs = ":".join(f"{b:02x}" for b in digest[:16])
    return f"SHA256:{hex_pairs}"


# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------


def _db_path() -> str:
    return os.environ.get(_ENV_DB_PATH, _DEFAULT_DB_PATH)


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    con = sqlite3.connect(_db_path())
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _ensure_table() -> None:
    with _conn() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS ssh_keys (
                name         TEXT NOT NULL PRIMARY KEY,
                private_key  TEXT NOT NULL,
                fingerprint  TEXT NOT NULL,
                created_at   TEXT NOT NULL
            )
            """
        )


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class UploadKeyRequest(BaseModel):
    name: str = Field(max_length=128)
    key: str = Field(max_length=16384)  # PEM private key content


class KeySummary(BaseModel):
    name: str
    fingerprint: str
    created_at: str


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------


def _require_admin_or_operator(request: Request) -> None:
    role = getattr(request.state, "role", None)
    if role not in ("admin", "operator"):
        raise HTTPException(
            status_code=403,
            detail={
                "message": "Admin or operator role required.",
                "type": "authorization_error",
                "code": "forbidden",
            },
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", status_code=201, summary="Upload an SSH private key")
async def upload_key(body: UploadKeyRequest, request: Request) -> KeySummary:
    """Store an SSH private key under *name*.

    The private key is encrypted before storage.  Returns the key summary
    (name, fingerprint, created_at) — never the private key content.

    Requires admin or operator role.
    """
    _require_admin_or_operator(request)
    _ensure_table()

    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail={"message": "Key name must not be empty."})

    key_content = body.key.strip()
    if not key_content:
        raise HTTPException(status_code=422, detail={"message": "Key content must not be empty."})

    fingerprint = _fingerprint(key_content)
    encrypted = _encrypt(key_content)
    created_at = datetime.now(timezone.utc).isoformat()

    try:
        with _conn() as con:
            con.execute(
                "INSERT INTO ssh_keys (name, private_key, fingerprint, created_at)"
                " VALUES (?, ?, ?, ?)",
                (name, encrypted, fingerprint, created_at),
            )
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail={"message": f"Key '{name}' already exists."},
        ) from None

    logger.info("SSH key '%s' uploaded (fingerprint=%s)", name, fingerprint)
    return KeySummary(name=name, fingerprint=fingerprint, created_at=created_at)


@router.get("", summary="List stored SSH keys")
async def list_keys(request: Request) -> list[KeySummary]:
    """Return a list of stored SSH key summaries.

    Private key content is never included in the response.
    Requires admin or operator role.
    """
    _require_admin_or_operator(request)
    _ensure_table()

    with _conn() as con:
        rows = con.execute(
            "SELECT name, fingerprint, created_at FROM ssh_keys ORDER BY created_at DESC"
        ).fetchall()

    return [
        KeySummary(name=r["name"], fingerprint=r["fingerprint"], created_at=r["created_at"])
        for r in rows
    ]


@router.delete("/{name}", summary="Delete an SSH key")
async def delete_key(name: str, request: Request) -> dict:
    """Delete the SSH key identified by *name*.

    Returns HTTP 404 if the key does not exist.
    Requires admin or operator role.
    """
    _require_admin_or_operator(request)
    _ensure_table()

    with _conn() as con:
        cur = con.execute("DELETE FROM ssh_keys WHERE name = ?", (name,))

    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail={"message": f"Key '{name}' not found."})

    logger.info("SSH key '%s' deleted", name)
    return {"deleted": True, "name": name}
