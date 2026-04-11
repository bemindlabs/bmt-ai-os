"""Unit tests for bmt_ai_os.controller.auth and auth_routes.

Covers:
- UserStore CRUD operations and password hashing
- JWT creation and verification
- JWTAuthMiddleware: exempt paths, backward-compat fallback, RBAC
- /api/v1/auth/login and /api/v1/auth/me endpoints
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path):
    """Return a temp path for an isolated SQLite auth DB."""
    return str(tmp_path / "test-auth.db")


@pytest.fixture()
def store(tmp_db):
    from bmt_ai_os.controller.auth import UserStore

    return UserStore(db_path=tmp_db)


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    """Inject a known JWT secret for all tests in this module."""
    monkeypatch.setenv("BMT_JWT_SECRET", "test-secret-key-for-unit-tests")


# ---------------------------------------------------------------------------
# UserStore
# ---------------------------------------------------------------------------


class TestUserStore:
    def test_create_and_get_user(self, store):
        user = store.create_user("alice", "s3cr3t", "admin")
        assert user.username == "alice"
        assert user.role.value == "admin"
        assert user.id is not None

        fetched = store.get_user("alice")
        assert fetched is not None
        assert fetched.username == "alice"

    def test_password_is_hashed(self, store):
        store.create_user("bob", "hunter2", "viewer")
        user = store.get_user("bob")
        assert user.password_hash != "hunter2"
        assert user.password_hash.startswith("$2b$")

    def test_authenticate_valid(self, store):
        store.create_user("carol", "pass123", "operator")
        authenticated = store.authenticate("carol", "pass123")
        assert authenticated is not None
        assert authenticated.username == "carol"

    def test_authenticate_wrong_password(self, store):
        store.create_user("dave", "correct", "viewer")
        result = store.authenticate("dave", "wrong")
        assert result is None

    def test_authenticate_nonexistent(self, store):
        result = store.authenticate("nobody", "pass")
        assert result is None

    def test_duplicate_username_raises(self, store):
        store.create_user("eve", "pw", "viewer")
        with pytest.raises(ValueError, match="already exists"):
            store.create_user("eve", "pw2", "admin")

    def test_invalid_role_raises(self, store):
        with pytest.raises(ValueError, match="Invalid role"):
            store.create_user("frank", "pw", "superuser")

    def test_list_users(self, store):
        store.create_user("u1", "pw", "viewer")
        store.create_user("u2", "pw", "operator")
        users = store.list_users()
        assert len(users) == 2
        names = {u.username for u in users}
        assert names == {"u1", "u2"}

    def test_delete_user(self, store):
        store.create_user("victim", "pw", "viewer")
        assert store.delete_user("victim") is True
        assert store.get_user("victim") is None

    def test_delete_nonexistent_returns_false(self, store):
        assert store.delete_user("ghost") is False

    def test_has_users(self, store):
        assert store.has_users() is False
        store.create_user("x", "pw", "viewer")
        assert store.has_users() is True


# ---------------------------------------------------------------------------
# JWT utilities
# ---------------------------------------------------------------------------


class TestJWT:
    def test_create_and_verify_token(self, store):
        from bmt_ai_os.controller.auth import create_token, verify_token

        user = store.create_user("jwt_user", "pw", "admin")
        token = create_token(user)
        assert isinstance(token, str)

        payload = verify_token(token)
        assert payload["sub"] == "jwt_user"
        assert payload["role"] == "admin"
        assert "exp" in payload

    def test_expired_token_raises(self, store, monkeypatch):
        import jwt as pyjwt

        from bmt_ai_os.controller.auth import create_token, verify_token

        user = store.create_user("expired_user", "pw", "viewer")

        # Monkey-patch _JWT_EXPIRY_SECONDS to -1 to force immediate expiry
        import bmt_ai_os.controller.auth as auth_mod

        monkeypatch.setattr(auth_mod, "_JWT_EXPIRY_SECONDS", -1)
        token = create_token(user)

        with pytest.raises(pyjwt.ExpiredSignatureError):
            verify_token(token)

    def test_tampered_token_raises(self, store):
        import jwt as pyjwt

        from bmt_ai_os.controller.auth import create_token, verify_token

        user = store.create_user("tamper_user", "pw", "viewer")
        token = create_token(user)
        tampered = token[:-4] + "XXXX"

        with pytest.raises(pyjwt.PyJWTError):
            verify_token(tampered)

    def test_missing_secret_raises(self, monkeypatch, store):
        monkeypatch.delenv("BMT_JWT_SECRET", raising=False)
        from bmt_ai_os.controller.auth import create_token

        user = store.create_user("nosecret_user", "pw", "viewer")
        with pytest.raises(RuntimeError, match="JWT secret not configured"):
            create_token(user)


# ---------------------------------------------------------------------------
# Role permission helper
# ---------------------------------------------------------------------------


class TestRoleAllows:
    def test_admin_can_write_anything(self):
        from bmt_ai_os.controller.auth import Role, _role_allows

        assert _role_allows(Role.admin, "DELETE", "/api/v1/models/foo") is True

    def test_viewer_can_read(self):
        from bmt_ai_os.controller.auth import Role, _role_allows

        assert _role_allows(Role.viewer, "GET", "/api/v1/status") is True

    def test_viewer_cannot_write(self):
        from bmt_ai_os.controller.auth import Role, _role_allows

        assert _role_allows(Role.viewer, "POST", "/api/v1/models") is False

    def test_operator_can_write_allowed_path(self):
        from bmt_ai_os.controller.auth import Role, _role_allows

        assert _role_allows(Role.operator, "POST", "/api/v1/rag/ingest") is True

    def test_operator_cannot_write_admin_only_path(self):
        from bmt_ai_os.controller.auth import Role, _role_allows

        assert _role_allows(Role.operator, "DELETE", "/api/v1/users") is False


# ---------------------------------------------------------------------------
# JWTAuthMiddleware via TestClient
# ---------------------------------------------------------------------------


def _make_app(tmp_db: str) -> tuple[FastAPI, TestClient]:
    """Return a minimal FastAPI app with JWTAuthMiddleware and a test client."""
    from bmt_ai_os.controller.auth import JWTAuthMiddleware, UserStore

    app = FastAPI()
    store = UserStore(db_path=tmp_db)
    app.add_middleware(JWTAuthMiddleware, store=store)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/api/v1/status")
    async def status():
        return {"status": "running"}

    @app.post("/api/v1/models")
    async def create_model():
        return {"created": True}

    return app, TestClient(app, raise_server_exceptions=False), store


class TestJWTMiddleware:
    def test_exempt_path_passes_without_token(self, tmp_db):
        app, client, _ = _make_app(tmp_db)
        resp = client.get("/healthz")
        assert resp.status_code == 200

    def test_no_users_open_access(self, tmp_db):
        """With no users registered, all paths pass through."""
        app, client, _ = _make_app(tmp_db)
        resp = client.get("/api/v1/status")
        assert resp.status_code == 200

    def test_no_users_api_key_fallthrough(self, tmp_db, monkeypatch):
        """When no users and BMT_API_KEY is set, JWT middleware skips to next."""
        monkeypatch.setenv("BMT_API_KEY", "test-key")
        app, client, _ = _make_app(tmp_db)
        # No JWT needed — falls through to whatever is next (no APIKeyMiddleware here)
        resp = client.get("/api/v1/status")
        assert resp.status_code == 200

    def test_missing_token_when_users_exist(self, tmp_db):
        app, client, store = _make_app(tmp_db)
        store.create_user("testuser", "pw", "viewer")
        resp = client.get("/api/v1/status")
        assert resp.status_code == 401

    def test_valid_token_grants_access(self, tmp_db):
        from bmt_ai_os.controller.auth import create_token

        app, client, store = _make_app(tmp_db)
        user = store.create_user("validuser", "pw", "viewer")
        token = create_token(user)
        resp = client.get("/api/v1/status", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_viewer_forbidden_on_write(self, tmp_db):
        from bmt_ai_os.controller.auth import create_token

        app, client, store = _make_app(tmp_db)
        user = store.create_user("readonly", "pw", "viewer")
        token = create_token(user)
        resp = client.post("/api/v1/models", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403

    def test_admin_allowed_on_write(self, tmp_db):
        from bmt_ai_os.controller.auth import create_token

        app, client, store = _make_app(tmp_db)
        user = store.create_user("superuser", "pw", "admin")
        token = create_token(user)
        resp = client.post("/api/v1/models", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_invalid_token_returns_401(self, tmp_db):
        app, client, store = _make_app(tmp_db)
        store.create_user("someone", "pw", "viewer")
        resp = client.get("/api/v1/status", headers={"Authorization": "Bearer not.a.real.token"})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Auth API endpoints
# ---------------------------------------------------------------------------


def _make_auth_app(tmp_db: str):
    """Return a FastAPI app with auth routes mounted."""
    import bmt_ai_os.controller.auth as auth_mod
    from bmt_ai_os.controller.auth import JWTAuthMiddleware, UserStore
    from bmt_ai_os.controller.auth_routes import router as auth_router

    # Override the module-level singleton for isolation
    store = UserStore(db_path=tmp_db)
    auth_mod._default_store = store

    app = FastAPI()
    app.add_middleware(JWTAuthMiddleware, store=store)
    app.include_router(auth_router)

    return app, TestClient(app, raise_server_exceptions=False), store


class TestAuthEndpoints:
    def test_login_success(self, tmp_db):
        app, client, store = _make_auth_app(tmp_db)
        store.create_user("loginuser", "secret", "operator")

        resp = client.post(
            "/api/v1/auth/login", json={"username": "loginuser", "password": "secret"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert body["role"] == "operator"
        assert body["username"] == "loginuser"

    def test_login_wrong_password(self, tmp_db):
        app, client, store = _make_auth_app(tmp_db)
        store.create_user("loginuser2", "correct", "viewer")

        resp = client.post(
            "/api/v1/auth/login", json={"username": "loginuser2", "password": "wrong"}
        )
        assert resp.status_code == 401

    def test_login_unknown_user(self, tmp_db):
        app, client, store = _make_auth_app(tmp_db)
        resp = client.post("/api/v1/auth/login", json={"username": "ghost", "password": "pw"})
        assert resp.status_code == 401

    def test_me_returns_user_info(self, tmp_db):
        from bmt_ai_os.controller.auth import create_token

        app, client, store = _make_auth_app(tmp_db)
        user = store.create_user("meuser", "pw", "admin")
        token = create_token(user)

        resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["username"] == "meuser"
        assert body["role"] == "admin"

    def test_me_no_users_returns_anonymous(self, tmp_db):
        """Without any registered users, /me returns anonymous access info."""
        app, client, store = _make_auth_app(tmp_db)
        # No users created — middleware passes through
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 200
        body = resp.json()
        assert body["username"] == "anonymous"
