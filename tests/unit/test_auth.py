"""Unit tests for bmt_ai_os.controller.auth and auth_routes.

Covers:
- UserStore CRUD operations and password hashing
- JWT creation and verification
- JWTAuthMiddleware: exempt paths, backward-compat fallback, RBAC
- /api/v1/auth/login and /api/v1/auth/me endpoints
- Password complexity validation (BMTOS-64)
- Startup security validation (BMTOS-54)
- ensure_default_admin() production guard (BMTOS-54)
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Passwords that satisfy complexity requirements (12+ chars, upper, lower, digit)
VALID_PW = "SecurePass1!"
VALID_PW2 = "AnotherPass2@"


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
    """Inject a known JWT secret for all tests in this module (32 chars)."""
    monkeypatch.setenv("BMT_JWT_SECRET", "test-secret-key-for-unit-tests!!")


# ---------------------------------------------------------------------------
# UserStore
# ---------------------------------------------------------------------------


class TestUserStore:
    def test_create_and_get_user(self, store):
        user = store.create_user("alice", VALID_PW, "admin")
        assert user.username == "alice"
        assert user.role.value == "admin"
        assert user.id is not None

        fetched = store.get_user("alice")
        assert fetched is not None
        assert fetched.username == "alice"

    def test_password_is_hashed(self, store):
        store.create_user("bob", VALID_PW, "viewer")
        user = store.get_user("bob")
        assert user.password_hash != VALID_PW
        assert user.password_hash.startswith("$2b$")

    def test_authenticate_valid(self, store):
        store.create_user("carol", VALID_PW, "operator")
        authenticated = store.authenticate("carol", VALID_PW)
        assert authenticated is not None
        assert authenticated.username == "carol"

    def test_authenticate_wrong_password(self, store):
        store.create_user("dave", VALID_PW, "viewer")
        result = store.authenticate("dave", "wrong")
        assert result is None

    def test_authenticate_nonexistent(self, store):
        result = store.authenticate("nobody", VALID_PW)
        assert result is None

    def test_duplicate_username_raises(self, store):
        store.create_user("eve", VALID_PW, "viewer")
        with pytest.raises(ValueError, match="already exists"):
            store.create_user("eve", VALID_PW2, "admin")

    def test_invalid_role_raises(self, store):
        with pytest.raises(ValueError, match="Invalid role"):
            store.create_user("frank", VALID_PW, "superuser")

    def test_list_users(self, store):
        store.create_user("u1", VALID_PW, "viewer")
        store.create_user("u2", VALID_PW2, "operator")
        users = store.list_users()
        assert len(users) == 2
        names = {u.username for u in users}
        assert names == {"u1", "u2"}

    def test_delete_user(self, store):
        store.create_user("victim", VALID_PW, "viewer")
        assert store.delete_user("victim") is True
        assert store.get_user("victim") is None

    def test_delete_nonexistent_returns_false(self, store):
        assert store.delete_user("ghost") is False

    def test_has_users(self, store):
        assert store.has_users() is False
        store.create_user("x", VALID_PW, "viewer")
        assert store.has_users() is True


# ---------------------------------------------------------------------------
# Password complexity validation (BMTOS-64)
# ---------------------------------------------------------------------------


class TestPasswordComplexity:
    def test_valid_password_accepted(self, store):
        # Should not raise
        user = store.create_user("goodpw", "ValidPass123!", "viewer")
        assert user.username == "goodpw"

    def test_too_short_raises(self, store):
        with pytest.raises(ValueError, match="12 characters"):
            store.create_user("short", "Short1!", "viewer")

    def test_no_uppercase_raises(self, store):
        with pytest.raises(ValueError, match="uppercase"):
            store.create_user("noup", "nouppercase1!!", "viewer")

    def test_no_lowercase_raises(self, store):
        with pytest.raises(ValueError, match="lowercase"):
            store.create_user("nolw", "NOLOWERCASE1!!", "viewer")

    def test_no_digit_raises(self, store):
        with pytest.raises(ValueError, match="digit"):
            store.create_user("nodig", "NoDigitsHere!!", "viewer")

    def test_skip_complexity_bypasses_validation(self, store):
        """Internal bootstrap path may bypass complexity checks."""
        user = store.create_user("bootstrap", "weak", "admin", skip_complexity=True)
        assert user.username == "bootstrap"

    def test_validate_password_complexity_function_directly(self):
        from bmt_ai_os.controller.auth import validate_password_complexity

        # Valid
        validate_password_complexity("ValidPass12!")  # should not raise

        # Too short
        with pytest.raises(ValueError, match="12 characters"):
            validate_password_complexity("Short1!")

        # Missing uppercase
        with pytest.raises(ValueError, match="uppercase"):
            validate_password_complexity("alllowercase1!")

        # Missing lowercase
        with pytest.raises(ValueError, match="lowercase"):
            validate_password_complexity("ALLUPPERCASE1!")

        # Missing digit
        with pytest.raises(ValueError, match="digit"):
            validate_password_complexity("NoDigitsHereXY!")


# ---------------------------------------------------------------------------
# JWT utilities
# ---------------------------------------------------------------------------


class TestJWT:
    def test_create_and_verify_token(self, store):
        from bmt_ai_os.controller.auth import create_token, verify_token

        user = store.create_user("jwt_user", VALID_PW, "admin")
        token = create_token(user)
        assert isinstance(token, str)

        payload = verify_token(token)
        assert payload["sub"] == "jwt_user"
        assert payload["role"] == "admin"
        assert "exp" in payload

    def test_expired_token_raises(self, store, monkeypatch):
        import jwt as pyjwt

        from bmt_ai_os.controller.auth import create_token, verify_token

        user = store.create_user("expired_user", VALID_PW, "viewer")

        # Monkey-patch _JWT_EXPIRY_SECONDS to -1 to force immediate expiry
        import bmt_ai_os.controller.auth as auth_mod

        monkeypatch.setattr(auth_mod, "_JWT_EXPIRY_SECONDS", -1)
        token = create_token(user)

        with pytest.raises(pyjwt.ExpiredSignatureError):
            verify_token(token)

    def test_tampered_token_raises(self, store):
        import jwt as pyjwt

        from bmt_ai_os.controller.auth import create_token, verify_token

        user = store.create_user("tamper_user", VALID_PW, "viewer")
        token = create_token(user)
        tampered = token[:-4] + "XXXX"

        with pytest.raises(pyjwt.PyJWTError):
            verify_token(tampered)

    def test_missing_secret_raises(self, monkeypatch, store):
        monkeypatch.delenv("BMT_JWT_SECRET", raising=False)
        from bmt_ai_os.controller.auth import create_token

        user = store.create_user("nosecret_user", VALID_PW, "viewer")
        with pytest.raises(RuntimeError, match="JWT secret not configured"):
            create_token(user)

    def test_short_secret_raises(self, monkeypatch, store):
        """A secret shorter than 32 chars must be rejected at token creation."""
        monkeypatch.setenv("BMT_JWT_SECRET", "tooshort")
        from bmt_ai_os.controller.auth import create_token

        user = store.create_user("shortsecret_user", VALID_PW, "viewer")
        with pytest.raises(RuntimeError, match="at least 32 characters"):
            create_token(user)


# ---------------------------------------------------------------------------
# validate_startup_security (BMTOS-54)
# ---------------------------------------------------------------------------


class TestValidateStartupSecurity:
    def test_missing_secret_calls_sys_exit(self, monkeypatch):
        monkeypatch.delenv("BMT_JWT_SECRET", raising=False)
        from bmt_ai_os.controller.auth import validate_startup_security

        with pytest.raises(SystemExit) as exc_info:
            validate_startup_security()
        assert exc_info.value.code == 1

    def test_short_secret_calls_sys_exit(self, monkeypatch):
        monkeypatch.setenv("BMT_JWT_SECRET", "short")
        from bmt_ai_os.controller.auth import validate_startup_security

        with pytest.raises(SystemExit) as exc_info:
            validate_startup_security()
        assert exc_info.value.code == 1

    def test_valid_secret_does_not_exit(self, monkeypatch):
        monkeypatch.setenv("BMT_JWT_SECRET", "a" * 32)
        from bmt_ai_os.controller.auth import validate_startup_security

        # Should complete without raising
        validate_startup_security()

    def test_stderr_message_on_missing_secret(self, monkeypatch, capsys):
        monkeypatch.delenv("BMT_JWT_SECRET", raising=False)
        from bmt_ai_os.controller.auth import validate_startup_security

        with pytest.raises(SystemExit):
            validate_startup_security()
        captured = capsys.readouterr()
        assert "BMT_JWT_SECRET" in captured.err
        assert "FATAL" in captured.err

    def test_stderr_message_on_short_secret(self, monkeypatch, capsys):
        monkeypatch.setenv("BMT_JWT_SECRET", "tiny")
        from bmt_ai_os.controller.auth import validate_startup_security

        with pytest.raises(SystemExit):
            validate_startup_security()
        captured = capsys.readouterr()
        assert "too short" in captured.err
        assert "FATAL" in captured.err


# ---------------------------------------------------------------------------
# ensure_default_admin (BMTOS-54)
# ---------------------------------------------------------------------------


class TestEnsureDefaultAdmin:
    def test_dev_mode_creates_default_admin(self, tmp_db, monkeypatch):
        monkeypatch.setenv("BMT_ENV", "dev")
        from bmt_ai_os.controller.auth import UserStore, ensure_default_admin

        store = UserStore(db_path=tmp_db)
        ensure_default_admin(store)

        admin = store.get_user("admin")
        assert admin is not None
        assert admin.role.value == "admin"

    def test_dev_mode_default_password_is_admin(self, tmp_db, monkeypatch):
        monkeypatch.setenv("BMT_ENV", "dev")
        from bmt_ai_os.controller.auth import UserStore, ensure_default_admin

        store = UserStore(db_path=tmp_db)
        ensure_default_admin(store)

        authenticated = store.authenticate("admin", "admin")
        assert authenticated is not None

    def test_production_mode_raises_when_no_users(self, tmp_db, monkeypatch):
        monkeypatch.delenv("BMT_ENV", raising=False)
        from bmt_ai_os.controller.auth import UserStore, ensure_default_admin

        store = UserStore(db_path=tmp_db)
        with pytest.raises(RuntimeError, match="Default admin credentials rejected"):
            ensure_default_admin(store)

    def test_production_mode_stderr_message(self, tmp_db, monkeypatch, capsys):
        monkeypatch.delenv("BMT_ENV", raising=False)
        from bmt_ai_os.controller.auth import UserStore, ensure_default_admin

        store = UserStore(db_path=tmp_db)
        with pytest.raises(RuntimeError):
            ensure_default_admin(store)
        captured = capsys.readouterr()
        assert "FATAL" in captured.err
        assert "admin/admin" in captured.err

    def test_skips_when_users_already_exist(self, tmp_db, monkeypatch):
        """ensure_default_admin does nothing when users already exist."""
        monkeypatch.delenv("BMT_ENV", raising=False)
        from bmt_ai_os.controller.auth import UserStore, ensure_default_admin

        store = UserStore(db_path=tmp_db)
        store.create_user("realadmin", VALID_PW, "admin")  # pre-existing user

        # Must not raise even in production mode
        ensure_default_admin(store)
        assert store.get_user("admin") is None  # default admin was not created


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
        store.create_user("testuser", VALID_PW, "viewer")
        resp = client.get("/api/v1/status")
        assert resp.status_code == 401

    def test_valid_token_grants_access(self, tmp_db):
        from bmt_ai_os.controller.auth import create_token

        app, client, store = _make_app(tmp_db)
        user = store.create_user("validuser", VALID_PW, "viewer")
        token = create_token(user)
        resp = client.get("/api/v1/status", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_viewer_forbidden_on_write(self, tmp_db):
        from bmt_ai_os.controller.auth import create_token

        app, client, store = _make_app(tmp_db)
        user = store.create_user("readonly", VALID_PW, "viewer")
        token = create_token(user)
        resp = client.post("/api/v1/models", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403

    def test_admin_allowed_on_write(self, tmp_db):
        from bmt_ai_os.controller.auth import create_token

        app, client, store = _make_app(tmp_db)
        user = store.create_user("superuser", VALID_PW, "admin")
        token = create_token(user)
        resp = client.post("/api/v1/models", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_invalid_token_returns_401(self, tmp_db):
        app, client, store = _make_app(tmp_db)
        store.create_user("someone", VALID_PW, "viewer")
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
        store.create_user("loginuser", VALID_PW, "operator")

        resp = client.post(
            "/api/v1/auth/login", json={"username": "loginuser", "password": VALID_PW}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert body["role"] == "operator"
        assert body["username"] == "loginuser"

    def test_login_wrong_password(self, tmp_db):
        app, client, store = _make_auth_app(tmp_db)
        store.create_user("loginuser2", VALID_PW, "viewer")

        resp = client.post(
            "/api/v1/auth/login", json={"username": "loginuser2", "password": "wrong"}
        )
        assert resp.status_code == 401

    def test_login_unknown_user(self, tmp_db):
        app, client, store = _make_auth_app(tmp_db)
        resp = client.post("/api/v1/auth/login", json={"username": "ghost", "password": VALID_PW})
        assert resp.status_code == 401

    def test_me_returns_user_info(self, tmp_db):
        from bmt_ai_os.controller.auth import create_token

        app, client, store = _make_auth_app(tmp_db)
        user = store.create_user("meuser", VALID_PW, "admin")
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
