"""Multi-user authentication and RBAC for BMT AI OS controller.

Provides:
- SQLite-backed user store with bcrypt password hashing
- JWT token issuance and verification (PyJWT)
- Three-tier RBAC: admin / operator / viewer
- Token blacklist for explicit revocation (jti-based)
- Account lockout after repeated failed logins
- JWTAuthMiddleware that falls through to legacy APIKeyMiddleware when no
  users exist and BMT_API_KEY is configured (backward compatible)
"""

from __future__ import annotations

import logging
import os
import re
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
_JWT_SECRET_MIN_LENGTH = 32

# Password complexity requirements
_PASSWORD_MIN_LENGTH = 12
_PASSWORD_REQUIRES_UPPERCASE = re.compile(r"[A-Z]")
_PASSWORD_REQUIRES_LOWERCASE = re.compile(r"[a-z]")
_PASSWORD_REQUIRES_DIGIT = re.compile(r"\d")

_ENV_BMT_ENV = "BMT_ENV"
_DEFAULT_ADMIN_USERNAME = "admin"
_DEFAULT_ADMIN_PASSWORD = "admin"

# Account lockout settings
_MAX_FAILED_LOGINS = 10
_LOCKOUT_SECONDS = 900  # 15 minutes

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
    "/api/v1/fleet/health",  # fleet health check (unauthenticated monitoring)
    "/api/v1/fleet/summary",  # read-only fleet summary (dashboard monitoring)
    "/api/v1/fleet/devices",  # read-only device list (dashboard monitoring)
)

# Paths that require a valid JWT but bypass RBAC write-restrictions.
# Any authenticated user (regardless of role) may call these.
_AUTH_SELF_SERVICE_PREFIXES = (
    "/api/v1/auth/logout",
    "/api/v1/auth/me",
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
# Password complexity validation
# ---------------------------------------------------------------------------


def validate_password_complexity(password: str) -> None:
    """Raise ValueError if *password* does not meet complexity requirements.

    Requirements:
    - Minimum 12 characters
    - At least one uppercase letter (A-Z)
    - At least one lowercase letter (a-z)
    - At least one digit (0-9)
    """
    errors: list[str] = []
    if len(password) < _PASSWORD_MIN_LENGTH:
        errors.append(f"at least {_PASSWORD_MIN_LENGTH} characters")
    if not _PASSWORD_REQUIRES_UPPERCASE.search(password):
        errors.append("at least one uppercase letter (A-Z)")
    if not _PASSWORD_REQUIRES_LOWERCASE.search(password):
        errors.append("at least one lowercase letter (a-z)")
    if not _PASSWORD_REQUIRES_DIGIT.search(password):
        errors.append("at least one digit (0-9)")
    if errors:
        raise ValueError("Password must contain " + ", ".join(errors) + ".")


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
    failed_logins: int = 0
    locked_until: float | None = None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role.value,
            "created_at": self.created_at,
            "locked": self.is_locked(),
        }

    def is_locked(self) -> bool:
        """Return True if the account is currently locked."""
        if self.locked_until is None:
            return False
        return time.time() < self.locked_until


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
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    username        TEXT    NOT NULL UNIQUE,
                    password_hash   TEXT    NOT NULL,
                    role            TEXT    NOT NULL DEFAULT 'viewer',
                    created_at      TEXT    NOT NULL,
                    failed_logins   INTEGER NOT NULL DEFAULT 0,
                    locked_until    REAL
                )
                """
            )
            # Migrate: add columns to existing DBs that lack them
            existing_cols = {row[1] for row in con.execute("PRAGMA table_info(users)").fetchall()}
            if "failed_logins" not in existing_cols:
                con.execute("ALTER TABLE users ADD COLUMN failed_logins INTEGER NOT NULL DEFAULT 0")
            if "locked_until" not in existing_cols:
                con.execute("ALTER TABLE users ADD COLUMN locked_until REAL")

            con.execute(
                """
                CREATE TABLE IF NOT EXISTS token_blacklist (
                    jti         TEXT    PRIMARY KEY,
                    revoked_at  REAL    NOT NULL,
                    expires_at  REAL    NOT NULL
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
            failed_logins=row["failed_logins"] if row["failed_logins"] is not None else 0,
            locked_until=row["locked_until"],
        )

    # --- Public API ---

    def create_user(
        self,
        username: str,
        password: str,
        role: Role | str = Role.viewer,
        skip_complexity: bool = False,
    ) -> User:
        """Create a new user with a bcrypt-hashed password.

        Raises ValueError if the username already exists, the role is invalid,
        or the password does not meet complexity requirements.

        Pass ``skip_complexity=True`` only for internal/test fixtures where
        complexity enforcement is intentionally bypassed (e.g. default-admin
        bootstrap in dev mode).
        """
        if isinstance(role, str):
            try:
                role = Role(role)
            except ValueError:
                valid = [r.value for r in Role]
                raise ValueError(f"Invalid role '{role}'. Must be one of: {valid}")

        if not skip_complexity:
            validate_password_complexity(password)

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

    def authenticate(self, username: str, password: str) -> User | None:
        """Return the User if credentials are valid, else None.

        Tracks failed attempts and locks the account after _MAX_FAILED_LOGINS
        consecutive failures for _LOCKOUT_SECONDS.
        """
        user = self.get_user(username)
        if user is None:
            # Constant-time dummy check to prevent timing attacks
            bcrypt.checkpw(b"dummy", bcrypt.hashpw(b"dummy", bcrypt.gensalt()))
            return None

        # Reject immediately if the account is locked
        if user.is_locked():
            logger.warning("Authentication rejected for locked account '%s'", username)
            return None

        if bcrypt.checkpw(password.encode(), user.password_hash.encode()):
            # Successful login — reset failure counter
            with self._conn() as con:
                con.execute(
                    "UPDATE users SET failed_logins = 0, locked_until = NULL WHERE username = ?",
                    (username,),
                )
            return user

        # Failed login — increment counter and possibly lock
        new_count = user.failed_logins + 1
        locked_until: float | None = None
        if new_count >= _MAX_FAILED_LOGINS:
            locked_until = time.time() + _LOCKOUT_SECONDS
            logger.warning(
                "Account '%s' locked for %d seconds after %d failed attempts",
                username,
                _LOCKOUT_SECONDS,
                new_count,
            )
        with self._conn() as con:
            con.execute(
                "UPDATE users SET failed_logins = ?, locked_until = ? WHERE username = ?",
                (new_count, locked_until, username),
            )
        return None

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
        """Delete user by username. Returns True if the user existed.

        Also revokes all active tokens belonging to this user by inserting
        their jtis into the blacklist would require storing jti-to-user
        mappings; instead, deletion is recorded so callers can also call
        revoke_tokens_for_user() if they maintain that mapping.
        """
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

    def update_user_role(self, username: str, new_role: Role | str) -> bool:
        """Change a user's role. Returns True if the user was found and updated.

        Callers should also revoke existing tokens for the user so that role
        changes take effect immediately.
        """
        if isinstance(new_role, str):
            try:
                new_role = Role(new_role)
            except ValueError:
                valid = [r.value for r in Role]
                raise ValueError(f"Invalid role '{new_role}'. Must be one of: {valid}")

        with self._conn() as con:
            cur = con.execute(
                "UPDATE users SET role = ? WHERE username = ?",
                (new_role.value, username),
            )
        updated = cur.rowcount > 0
        if updated:
            logger.info("Updated role for user '%s' to '%s'", username, new_role.value)
        return updated

    def lock_account(self, username: str, duration_seconds: int = _LOCKOUT_SECONDS) -> bool:
        """Manually lock an account for *duration_seconds*. Returns True if found."""
        locked_until = time.time() + duration_seconds
        with self._conn() as con:
            cur = con.execute(
                "UPDATE users SET locked_until = ? WHERE username = ?",
                (locked_until, username),
            )
        updated = cur.rowcount > 0
        if updated:
            logger.info("Manually locked account '%s'", username)
        return updated

    def unlock_account(self, username: str) -> bool:
        """Remove any lock from an account. Returns True if the user was found."""
        with self._conn() as con:
            cur = con.execute(
                "UPDATE users SET locked_until = NULL, failed_logins = 0 WHERE username = ?",
                (username,),
            )
        updated = cur.rowcount > 0
        if updated:
            logger.info("Unlocked account '%s'", username)
        return updated

    # --- Token blacklist ---

    def revoke_token(self, jti: str, expires_at: float) -> None:
        """Add *jti* to the blacklist so it cannot be used for authentication."""
        with self._conn() as con:
            con.execute(
                "INSERT OR IGNORE INTO token_blacklist (jti, revoked_at, expires_at)"
                " VALUES (?,?,?)",
                (jti, time.time(), expires_at),
            )
        logger.debug("Revoked token jti=%s", jti)

    def is_token_revoked(self, jti: str) -> bool:
        """Return True if *jti* is in the blacklist."""
        with self._conn() as con:
            row = con.execute("SELECT 1 FROM token_blacklist WHERE jti = ?", (jti,)).fetchone()
        return row is not None

    def purge_expired_blacklist_entries(self) -> int:
        """Remove blacklist entries whose tokens have already expired.

        Returns the number of rows removed.
        """
        now = time.time()
        with self._conn() as con:
            cur = con.execute("DELETE FROM token_blacklist WHERE expires_at < ?", (now,))
        return cur.rowcount


# ---------------------------------------------------------------------------
# JWT token utilities
# ---------------------------------------------------------------------------


def _jwt_secret() -> str:
    secret = os.environ.get(_ENV_JWT_SECRET)
    if not secret:
        raise RuntimeError(
            f"JWT secret not configured. Set the {_ENV_JWT_SECRET} environment variable."
        )
    if len(secret) < _JWT_SECRET_MIN_LENGTH:
        raise RuntimeError(
            f"{_ENV_JWT_SECRET} must be at least {_JWT_SECRET_MIN_LENGTH} characters long "
            f"(got {len(secret)})."
        )
    return secret


def create_token(user: User) -> str:
    """Issue a signed JWT for *user* valid for 24 hours.

    The token includes a unique ``jti`` (JWT ID) claim that can be placed on
    the blacklist to revoke it before natural expiry.
    """
    now = int(time.time())
    payload = {
        "sub": user.username,
        "role": user.role.value,
        "iat": now,
        "exp": now + _JWT_EXPIRY_SECONDS,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=_JWT_ALGORITHM)


def verify_token(token: str, store: UserStore | None = None) -> dict:
    """Decode and validate *token*.

    Returns the payload dict on success.
    Raises jwt.PyJWTError (or subclass) on any validation failure.
    Raises jwt.InvalidTokenError with message 'Token has been revoked' when
    the token's jti is on the blacklist.
    """
    payload = jwt.decode(token, _jwt_secret(), algorithms=[_JWT_ALGORITHM])

    # Check blacklist when a store is available
    jti = payload.get("jti")
    if jti and store is not None and store.is_token_revoked(jti):
        raise jwt.InvalidTokenError("Token has been revoked.")

    return payload


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
        # When an explicit store is provided (tests, custom deployments) we use
        # it directly.  Otherwise we resolve the current module-level singleton
        # on every request so that test teardown/reset is picked up correctly.
        self._explicit_store: UserStore | None = store

    def _get_store(self) -> UserStore:
        return self._explicit_store if self._explicit_store is not None else _get_default_store()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        # Always exempt health / docs paths
        if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await call_next(request)

        store = self._get_store()

        # Backward-compatible: no users + API key configured → skip JWT auth
        if not store.has_users() and os.environ.get(_ENV_API_KEY):
            return await call_next(request)

        # Backward-compatible: no users, no API key → open access (local dev)
        if not store.has_users():
            return await call_next(request)

        # Extract Bearer token
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return _auth_error("Missing or malformed Authorization header.")

        token = auth_header[7:]

        try:
            payload = verify_token(token, store=store)
        except jwt.ExpiredSignatureError:
            return _auth_error("Token has expired.", code="token_expired")
        except jwt.InvalidTokenError as exc:
            if "revoked" in str(exc).lower():
                return _auth_error("Token has been revoked.", code="token_revoked")
            logger.warning("JWT validation failed: %s", exc)
            return _auth_error("Invalid token.", code="invalid_token")
        except jwt.PyJWTError as exc:
            logger.warning("JWT validation failed: %s", exc)
            return _auth_error("Invalid token.", code="invalid_token")

        # Attach user info to request state for downstream handlers
        request.state.user = payload.get("sub")
        request.state.role = payload.get("role", Role.viewer.value)
        request.state.jti = payload.get("jti")

        # Self-service auth paths bypass RBAC (any authenticated user may call them)
        if any(path.startswith(p) for p in _AUTH_SELF_SERVICE_PREFIXES):
            return await call_next(request)

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


def ensure_default_admin(store: UserStore | None = None) -> None:
    """Bootstrap a default admin user when no users exist.

    In production (BMT_ENV != 'dev'), the default admin/admin credentials are
    explicitly rejected — the operator must pre-seed a real admin user or set
    BMT_ENV=dev to allow a temporary insecure default.

    Raises RuntimeError in production when no users exist (would require
    default credentials), directing the operator to create a proper admin.
    """
    _store = store or _get_default_store()

    if _store.has_users():
        return  # users already exist — nothing to bootstrap

    is_dev = os.environ.get(_ENV_BMT_ENV, "").lower() == "dev"

    if not is_dev:
        print(
            "FATAL: No users found in the auth store and BMT_ENV is not 'dev'.\n"
            "       Default admin/admin credentials are not permitted in production.\n"
            "       Create an initial admin user or set BMT_ENV=dev for development.",
            file=sys.stderr,
        )
        raise RuntimeError(
            "Default admin credentials rejected in production. "
            "Create a real admin user or set BMT_ENV=dev."
        )

    # Dev mode only — create insecure default admin with complexity bypass
    logger.warning(
        "BMT_ENV=dev: bootstrapping default admin/admin credentials. "
        "Change the password before deploying to production."
    )
    _store.create_user(
        _DEFAULT_ADMIN_USERNAME,
        _DEFAULT_ADMIN_PASSWORD,
        Role.admin,
        skip_complexity=True,
    )


def validate_startup_security() -> None:
    """Validate security-critical configuration at controller startup.

    Checks performed (in order):
    1. BMT_JWT_SECRET is set and at least 32 characters long.

    Prints a descriptive error to stderr and raises SystemExit(1) on failure
    so the process terminates before binding any ports.
    """
    secret = os.environ.get(_ENV_JWT_SECRET, "")
    if not secret:
        print(
            f"FATAL: {_ENV_JWT_SECRET} environment variable is not set.\n"
            "       Generate a secret with: "
            'python3 -c "import secrets; print(secrets.token_hex(32))"',
            file=sys.stderr,
        )
        sys.exit(1)

    if len(secret) < _JWT_SECRET_MIN_LENGTH:
        print(
            f"FATAL: {_ENV_JWT_SECRET} is too short "
            f"({len(secret)} chars, minimum {_JWT_SECRET_MIN_LENGTH}).\n"
            "       Generate a secret with: "
            'python3 -c "import secrets; print(secrets.token_hex(32))"',
            file=sys.stderr,
        )
        sys.exit(1)
