"""Multi-user authentication and RBAC for BMT AI OS controller.

Provides:
- SQLite-backed user store with bcrypt password hashing
- JWT token issuance and verification (PyJWT)
- Three-tier RBAC: admin / operator / viewer
- JWTAuthMiddleware that falls through to legacy APIKeyMiddleware when no
  users exist and BMT_API_KEY is configured (backward compatible)
"""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Generator

import bcrypt
import jwt
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_DB_PATH = "/tmp/bmt-auth.db"
_ENV_DB_PATH = "BMT_AUTH_DB"
_ENV_JWT_SECRET = "BMT_JWT_SECRET"
_ENV_API_KEY = "BMT_API_KEY"

_JWT_ALGORITHM = "HS256"
_JWT_EXPIRY_SECONDS = 86400  # 24 hours

# Account lockout settings
_MAX_FAILED_ATTEMPTS = 5
_LOCKOUT_DURATION_SECONDS = 900  # 15 minutes

# Paths that never require authentication
_EXEMPT_PREFIXES = (
    "/healthz",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/metrics",
    "/api/v1/auth/login",  # token acquisition must be exempt
    "/api/v1/status",  # read-only monitoring (dashboard)
    "/api/v1/metrics",  # read-only monitoring (dashboard)
    "/api/v1/providers",  # provider list + switching (dashboard)
    "/api/v1/logs",  # request log viewer (dashboard)
    "/api/models",  # Ollama model list (dashboard)
    "/api/pull",  # Ollama model pull (dashboard)
    "/v1/",  # OpenAI-compatible API (models, chat, completions)
    "/api/v1/fleet/register",  # edge devices register without user tokens
    "/api/v1/fleet/heartbeat",  # edge devices send heartbeats without user tokens
    "/api/v1/fleet/health",  # fleet health check
    "/api/v1/fleet/summary",  # read-only fleet summary
    "/api/v1/fleet/devices",  # read-only device list
)


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class Role(str, Enum):
    """RBAC roles in ascending privilege order."""

    viewer = "viewer"
    operator = "operator"
    admin = "admin"


# Permissions per role — each role includes all permissions of lower roles.
_ROLE_WRITE_PATHS: dict[Role, set[str]] = {
    Role.admin: {"*"},  # full access
    Role.operator: {
        "/api/v1/models",
        "/api/v1/rag",
        "/api/v1/metrics",
        "/v1/chat",
        "/v1/completions",
        "/v1/embeddings",
    },
    Role.viewer: set(),  # read-only (GET only)
}


def _role_allows(role: Role, method: str, path: str) -> bool:
    """Return True if *role* is permitted to call *method* on *path*."""
    if role == Role.admin:
        return True
    if method.upper() == "GET":
        return True  # all roles may read
    # operator may write to specific path prefixes
    if role == Role.operator:
        for prefix in _ROLE_WRITE_PATHS[Role.operator]:
            if path.startswith(prefix):
                return True
    return False


# ---------------------------------------------------------------------------
# User model
# ---------------------------------------------------------------------------


@dataclass
class User:
    id: int
    username: str
    password_hash: str
    role: Role
    created_at: str

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role.value,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# UserStore — SQLite backend
# ---------------------------------------------------------------------------


class UserStore:
    """Persistent user store backed by a SQLite database."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.environ.get(_ENV_DB_PATH, _DEFAULT_DB_PATH)
        self._init_db()

    # --- Internal helpers ---

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
                CREATE TABLE IF NOT EXISTS users (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    username    TEXT    NOT NULL UNIQUE,
                    password_hash TEXT  NOT NULL,
                    role        TEXT    NOT NULL DEFAULT 'viewer',
                    created_at  TEXT    NOT NULL
                )
                """
            )
            # Token revocation blacklist — jti is the JWT "JWT ID" claim.
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS revoked_tokens (
                    jti         TEXT    NOT NULL PRIMARY KEY,
                    revoked_at  REAL    NOT NULL,
                    expires_at  REAL    NOT NULL
                )
                """
            )
            # Per-user lockout tracking.
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS login_attempts (
                    username        TEXT    NOT NULL PRIMARY KEY,
                    failed_count    INTEGER NOT NULL DEFAULT 0,
                    last_failed_at  REAL    NOT NULL DEFAULT 0,
                    locked_until    REAL    NOT NULL DEFAULT 0
                )
                """
            )

    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> User:
        return User(
            id=row["id"],
            username=row["username"],
            password_hash=row["password_hash"],
            role=Role(row["role"]),
            created_at=row["created_at"],
        )

    # --- Public API ---

    def create_user(self, username: str, password: str, role: Role | str = Role.viewer) -> User:
        """Create a new user with a bcrypt-hashed password.

        Raises ValueError if the username already exists or the role is invalid.
        """
        if isinstance(role, str):
            try:
                role = Role(role)
            except ValueError:
                valid = [r.value for r in Role]
                raise ValueError(f"Invalid role '{role}'. Must be one of: {valid}")

        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        created_at = datetime.now(timezone.utc).isoformat()

        try:
            with self._conn() as con:
                cur = con.execute(
                    "INSERT INTO users (username, password_hash, role, created_at)"
                    " VALUES (?,?,?,?)",
                    (username, pw_hash, role.value, created_at),
                )
                user_id = cur.lastrowid
        except sqlite3.IntegrityError:
            raise ValueError(f"Username '{username}' already exists.")

        logger.info("Created user '%s' with role '%s'", username, role.value)
        return User(
            id=user_id, username=username, password_hash=pw_hash, role=role, created_at=created_at
        )

    def get_user(self, username: str) -> User | None:
        """Return User by username, or None if not found."""
        with self._conn() as con:
            row = con.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return self._row_to_user(row) if row else None

    def list_users(self) -> list[User]:
        """Return all users ordered by id."""
        with self._conn() as con:
            rows = con.execute("SELECT * FROM users ORDER BY id").fetchall()
        return [self._row_to_user(r) for r in rows]

    def delete_user(self, username: str) -> bool:
        """Delete user by username. Returns True if the user existed."""
        with self._conn() as con:
            cur = con.execute("DELETE FROM users WHERE username = ?", (username,))
        deleted = cur.rowcount > 0
        if deleted:
            logger.info("Deleted user '%s'", username)
        return deleted

    def has_users(self) -> bool:
        """Return True if any users are registered in the store."""
        with self._conn() as con:
            count = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        return count > 0

    # --- Token revocation ---

    def revoke_token(self, jti: str, expires_at: float) -> None:
        """Add a JWT ID to the revocation blacklist.

        Args:
            jti: The ``jti`` claim from the JWT payload.
            expires_at: Unix timestamp when the token would naturally expire.
                Used to prune the blacklist of stale entries.
        """
        now = time.time()
        with self._conn() as con:
            con.execute(
                "INSERT OR REPLACE INTO revoked_tokens (jti, revoked_at, expires_at)"
                " VALUES (?, ?, ?)",
                (jti, now, expires_at),
            )
        logger.info("Revoked token jti=%s", jti)

    def is_token_revoked(self, jti: str) -> bool:
        """Return True if the given JWT ID has been revoked."""
        self._prune_revoked_tokens()
        with self._conn() as con:
            row = con.execute("SELECT 1 FROM revoked_tokens WHERE jti = ?", (jti,)).fetchone()
        return row is not None

    def _prune_revoked_tokens(self) -> None:
        """Remove expired entries from the revocation blacklist."""
        now = time.time()
        with self._conn() as con:
            con.execute("DELETE FROM revoked_tokens WHERE expires_at < ?", (now,))

    # --- Account lockout ---

    def record_failed_login(self, username: str) -> bool:
        """Record a failed login attempt for *username*.

        Returns True if the account is now locked (threshold reached).
        """
        now = time.time()
        with self._conn() as con:
            row = con.execute(
                "SELECT failed_count, locked_until FROM login_attempts WHERE username = ?",
                (username,),
            ).fetchone()

            if row is None:
                # First failure for this username
                con.execute(
                    "INSERT INTO login_attempts"
                    " (username, failed_count, last_failed_at, locked_until)"
                    " VALUES (?, 1, ?, 0)",
                    (username, now),
                )
                new_count = 1
            else:
                new_count = row["failed_count"] + 1
                locked_until = row["locked_until"]

                # If already locked, don't increment further; just reject
                if locked_until > now:
                    return True

                locked_until_new = (
                    now + _LOCKOUT_DURATION_SECONDS if new_count >= _MAX_FAILED_ATTEMPTS else 0
                )
                con.execute(
                    "UPDATE login_attempts"
                    " SET failed_count = ?, last_failed_at = ?, locked_until = ?"
                    " WHERE username = ?",
                    (new_count, now, locked_until_new, username),
                )

        if new_count >= _MAX_FAILED_ATTEMPTS:
            logger.warning(
                "Account '%s' locked after %d failed login attempts (cooldown=%ds)",
                username,
                new_count,
                _LOCKOUT_DURATION_SECONDS,
            )
            return True
        return False

    def reset_failed_logins(self, username: str) -> None:
        """Clear the failed login counter after a successful authentication."""
        with self._conn() as con:
            con.execute(
                "UPDATE login_attempts SET failed_count = 0, locked_until = 0 WHERE username = ?",
                (username,),
            )

    def is_account_locked(self, username: str) -> bool:
        """Return True if the account is currently locked out."""
        now = time.time()
        with self._conn() as con:
            row = con.execute(
                "SELECT locked_until FROM login_attempts WHERE username = ?",
                (username,),
            ).fetchone()
        if row is None:
            return False
        return float(row["locked_until"]) > now

    def authenticate(self, username: str, password: str) -> User | None:
        """Return the User if credentials are valid, else None.

        Enforces account lockout: returns None immediately when the account is
        locked, and records failed attempts (locking after the threshold).
        Resets the failure counter on success.
        """
        # Check lockout *before* hitting bcrypt to avoid unnecessary computation
        if self.is_account_locked(username):
            logger.warning("Login rejected: account '%s' is locked", username)
            return None

        user = self.get_user(username)
        if user is None:
            # Constant-time dummy check to prevent timing attacks
            bcrypt.checkpw(b"dummy", bcrypt.hashpw(b"dummy", bcrypt.gensalt()))
            # Record failure against the username even if it doesn't exist
            # to prevent username enumeration via lockout timing differences.
            self.record_failed_login(username)
            return None

        if bcrypt.checkpw(password.encode(), user.password_hash.encode()):
            self.reset_failed_logins(username)
            return user

        # Wrong password — record failure, potentially locking the account
        self.record_failed_login(username)
        return None


# ---------------------------------------------------------------------------
# JWT token utilities
# ---------------------------------------------------------------------------


def _jwt_secret() -> str:
    secret = os.environ.get(_ENV_JWT_SECRET)
    if not secret:
        raise RuntimeError(
            f"JWT secret not configured. Set the {_ENV_JWT_SECRET} environment variable."
        )
    return secret


def create_token(user: User) -> str:
    """Issue a signed JWT for *user* valid for 24 hours.

    Includes a ``jti`` (JWT ID) claim so tokens can be individually revoked
    via :py:meth:`UserStore.revoke_token`.
    """
    now = int(time.time())
    payload = {
        "sub": user.username,
        "role": user.role.value,
        "iat": now,
        "exp": now + _JWT_EXPIRY_SECONDS,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=_JWT_ALGORITHM)


def verify_token(token: str, store: UserStore | None = None) -> dict:
    """Decode and validate *token*.

    Returns the payload dict on success.
    Raises jwt.PyJWTError (or subclass) on any validation failure.
    Raises jwt.InvalidTokenError when the token has been explicitly revoked.

    Args:
        token: The raw JWT string from an Authorization header.
        store: Optional :class:`UserStore` used to check the revocation
            blacklist.  When ``None``, the module-level default store is used.
    """
    payload = jwt.decode(token, _jwt_secret(), algorithms=[_JWT_ALGORITHM])

    # Check revocation blacklist when a jti claim is present
    jti = payload.get("jti")
    if jti:
        active_store = store or _get_default_store()
        if active_store.is_token_revoked(jti):
            raise jwt.InvalidTokenError("Token has been revoked.")

    return payload


def revoke_token(token: str, store: UserStore | None = None) -> None:
    """Revoke a JWT by adding its ``jti`` to the blacklist.

    Decodes the token *without* verifying expiry (to allow revoking already-
    expired tokens during cleanup) and records the ``jti`` in the revocation
    table.

    Args:
        token: The raw JWT string.
        store: Optional :class:`UserStore`.  Defaults to the module singleton.

    Raises:
        jwt.PyJWTError: When the token cannot be decoded at all (malformed).
        ValueError: When the token has no ``jti`` claim.
    """
    # Decode without verification so we can extract the jti even for expired tokens.
    payload = jwt.decode(
        token,
        _jwt_secret(),
        algorithms=[_JWT_ALGORITHM],
        options={"verify_exp": False},
    )
    jti = payload.get("jti")
    if not jti:
        raise ValueError("Token does not contain a 'jti' claim and cannot be revoked.")
    exp = payload.get("exp", int(time.time()) + _JWT_EXPIRY_SECONDS)
    active_store = store or _get_default_store()
    active_store.revoke_token(jti, float(exp))


# ---------------------------------------------------------------------------
# JWTAuthMiddleware
# ---------------------------------------------------------------------------


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """JWT-based authentication and RBAC middleware.

    Behaviour:
    1. Exempt paths (/healthz, /docs, etc.) pass through unconditionally.
    2. When no users exist AND BMT_API_KEY is set, fall through to the
       existing APIKeyMiddleware (backward-compatible mode).
    3. Otherwise, require a valid ``Authorization: Bearer <jwt>``.
    4. After JWT validation, enforce role-based access for write operations.
    """

    def __init__(self, app: FastAPI, store: UserStore | None = None) -> None:
        super().__init__(app)
        self._store = store or _get_default_store()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        # Always exempt health / docs paths
        if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await call_next(request)

        # Backward-compatible: no users + API key configured → skip JWT auth
        if not self._store.has_users() and os.environ.get(_ENV_API_KEY):
            return await call_next(request)

        # Backward-compatible: no users, no API key → open access (local dev)
        if not self._store.has_users():
            return await call_next(request)

        # Extract Bearer token
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return _auth_error("Missing or malformed Authorization header.")

        token = auth_header[7:]

        try:
            payload = verify_token(token, store=self._store)
        except jwt.ExpiredSignatureError:
            return _auth_error("Token has expired.", code="token_expired")
        except jwt.InvalidTokenError as exc:
            logger.warning("JWT validation failed: %s", exc)
            return _auth_error("Invalid token.", code="invalid_token")
        except jwt.PyJWTError as exc:
            logger.warning("JWT validation failed: %s", exc)
            return _auth_error("Invalid token.", code="invalid_token")

        # Attach user info to request state for downstream handlers
        request.state.user = payload.get("sub")
        request.state.role = payload.get("role", Role.viewer.value)

        # Enforce RBAC
        role = Role(request.state.role)
        if not _role_allows(role, request.method, path):
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "message": (
                            f"Role '{role.value}' is not permitted to {request.method} {path}."
                        ),
                        "type": "authorization_error",
                        "code": "forbidden",
                    }
                },
            )

        return await call_next(request)


def _auth_error(message: str, code: str = "unauthorized") -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={
            "error": {
                "message": message,
                "type": "authentication_error",
                "code": code,
            }
        },
    )


# ---------------------------------------------------------------------------
# Module-level default store (lazy singleton)
# ---------------------------------------------------------------------------

_default_store: UserStore | None = None


def _get_default_store() -> UserStore:
    global _default_store
    if _default_store is None:
        _default_store = UserStore()
    return _default_store


def get_store() -> UserStore:
    """Return the module-level UserStore singleton."""
    return _get_default_store()


# ---------------------------------------------------------------------------
# Startup security validation
# ---------------------------------------------------------------------------

_ENV_ADMIN_PASS = "BMT_ADMIN_PASS"
_MIN_JWT_SECRET_LEN = 32
_DEFAULT_ADMIN_PASS = "admin"


def validate_startup_security(store: UserStore | None = None) -> None:
    """Validate critical security configuration at startup.

    Checks:
    - BMT_JWT_SECRET is set and at least 32 characters long. Exits with
      error code 1 if not, because running without a strong secret is a
      security vulnerability.
    - BMT_ADMIN_PASS is not the default "admin" value when users exist.
      Emits a warning (does not exit) because this may be intentional in
      development.

    Call this function early in the startup sequence, before binding the
    HTTP server.
    """
    # --- JWT secret check ---
    jwt_secret = os.environ.get(_ENV_JWT_SECRET, "")
    if not jwt_secret:
        logger.critical(
            "FATAL: %s environment variable is not set. "
            "A strong JWT secret is required to sign authentication tokens. "
            "Set it to a random string of at least %d characters and restart.",
            _ENV_JWT_SECRET,
            _MIN_JWT_SECRET_LEN,
        )
        sys.exit(1)

    if len(jwt_secret) < _MIN_JWT_SECRET_LEN:
        logger.critical(
            "FATAL: %s is too short (%d chars). "
            "Minimum length is %d characters. "
            "Use a cryptographically random value (e.g. `openssl rand -hex 32`).",
            _ENV_JWT_SECRET,
            len(jwt_secret),
            _MIN_JWT_SECRET_LEN,
        )
        sys.exit(1)

    logger.info("JWT secret: OK (length=%d)", len(jwt_secret))

    # --- Admin password check (warn only) ---
    active_store = store or _get_default_store()
    if active_store.has_users():
        admin_pass = os.environ.get(_ENV_ADMIN_PASS, "")
        if admin_pass == _DEFAULT_ADMIN_PASS:
            logger.warning(
                "SECURITY WARNING: %s is set to the default value '%s'. "
                "Change it to a strong password before exposing this service.",
                _ENV_ADMIN_PASS,
                _DEFAULT_ADMIN_PASS,
            )
