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
import time
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

# Paths that never require authentication
_EXEMPT_PREFIXES = (
    "/healthz",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/metrics",
    "/api/v1/auth/login",  # token acquisition must be exempt
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

    def authenticate(self, username: str, password: str) -> User | None:
        """Return the User if credentials are valid, else None."""
        user = self.get_user(username)
        if user is None:
            # Constant-time dummy check to prevent timing attacks
            bcrypt.checkpw(b"dummy", bcrypt.hashpw(b"dummy", bcrypt.gensalt()))
            return None
        if bcrypt.checkpw(password.encode(), user.password_hash.encode()):
            return user
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
        """Delete user by username. Returns True if the user existed."""
        with self._conn() as con:
            cur = con.execute("DELETE FROM users WHERE username = ?", (username,))
        deleted = cur.rowcount > 0
        if deleted:
            logger.info("Deleted user '%s'", username)
        return deleted

    def update_user_role(self, username: str, role: Role | str) -> bool:
        """Change the role of an existing user.

        Returns True if the user was found and updated, False if not found.
        Raises ValueError for an invalid role string.
        """
        if isinstance(role, str):
            try:
                role = Role(role)
            except ValueError:
                valid = [r.value for r in Role]
                raise ValueError(f"Invalid role '{role}'. Must be one of: {valid}")

        with self._conn() as con:
            cur = con.execute(
                "UPDATE users SET role = ? WHERE username = ?",
                (role.value, username),
            )
        updated = cur.rowcount > 0
        if updated:
            logger.info("Updated role for '%s' to '%s'", username, role.value)
        return updated

    def has_users(self) -> bool:
        """Return True if any users are registered in the store."""
        with self._conn() as con:
            count = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        return count > 0


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
    """Issue a signed JWT for *user* valid for 24 hours."""
    now = int(time.time())
    payload = {
        "sub": user.username,
        "role": user.role.value,
        "iat": now,
        "exp": now + _JWT_EXPIRY_SECONDS,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=_JWT_ALGORITHM)


def verify_token(token: str) -> dict:
    """Decode and validate *token*.

    Returns the payload dict on success.
    Raises jwt.PyJWTError (or subclass) on any validation failure.
    """
    return jwt.decode(token, _jwt_secret(), algorithms=[_JWT_ALGORITHM])


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
            payload = verify_token(token)
        except jwt.ExpiredSignatureError:
            return _auth_error("Token has expired.", code="token_expired")
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
# First-boot bootstrap
# ---------------------------------------------------------------------------

_ENV_DEFAULT_ADMIN_USER = "BMT_ADMIN_USER"
_ENV_DEFAULT_ADMIN_PASS = "BMT_ADMIN_PASS"

_DEFAULT_ADMIN_USERNAME = "admin"
_DEFAULT_ADMIN_PASSWORD = "admin"  # changed on first login in production


def ensure_default_admin(store: UserStore | None = None) -> bool:
    """Create the default admin user if no users exist.

    Called automatically during controller startup to satisfy the
    "default admin user created on first boot" acceptance criterion.

    Credentials are taken from BMT_ADMIN_USER / BMT_ADMIN_PASS env vars,
    falling back to "admin" / "admin".  A warning is emitted when the
    insecure defaults are used.

    Returns True if a new admin was created, False if users already existed.
    """
    s = store or _get_default_store()
    if s.has_users():
        return False

    username = os.environ.get(_ENV_DEFAULT_ADMIN_USER, _DEFAULT_ADMIN_USERNAME)
    password = os.environ.get(_ENV_DEFAULT_ADMIN_PASS, _DEFAULT_ADMIN_PASSWORD)

    if password == _DEFAULT_ADMIN_PASSWORD:
        logger.warning(
            "Using insecure default admin password. Set %s env var to override before first boot.",
            _ENV_DEFAULT_ADMIN_PASS,
        )

    s.create_user(username, password, Role.admin)
    logger.info("Default admin user '%s' created on first boot.", username)
    return True


# ---------------------------------------------------------------------------
# FastAPI dependency injection helpers
# ---------------------------------------------------------------------------

from fastapi import Depends, HTTPException, status  # noqa: E402
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer  # noqa: E402

_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict:
    """FastAPI dependency: decode the Bearer JWT and return the payload dict.

    Raises HTTP 401 when no/invalid token is provided, unless the store has
    no users (open-access / dev mode).
    """
    store = _get_default_store()

    # Dev/open mode: no users registered
    if not store.has_users():
        return {"sub": "anonymous", "role": Role.admin.value}

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "message": "Missing Authorization header.",
                "type": "authentication_error",
                "code": "unauthorized",
            },
        )

    try:
        payload = verify_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "message": "Token has expired.",
                "type": "authentication_error",
                "code": "token_expired",
            },
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "message": "Invalid token.",
                "type": "authentication_error",
                "code": "invalid_token",
            },
        )

    return payload


def require_role(*roles: Role) -> Callable[[dict], dict]:
    """Return a FastAPI dependency that enforces one of the listed roles.

    Usage::

        @router.delete("/api/v1/users/{username}")
        async def delete_user(user=Depends(require_role(Role.admin))):
            ...
    """

    def _check(payload: dict = Depends(get_current_user)) -> dict:
        current_role = Role(payload.get("role", Role.viewer.value))
        if current_role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "message": (
                        f"Role '{current_role.value}' is not permitted. "
                        f"Required: {[r.value for r in roles]}"
                    ),
                    "type": "authorization_error",
                    "code": "forbidden",
                },
            )
        return payload

    return _check
