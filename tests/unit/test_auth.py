"""Unit tests for bmt_ai_os.controller.auth and auth_routes.

Covers:
- UserStore CRUD operations and password hashing
- JWT creation and verification (including jti claim)
- Token blacklist: revoke_token, is_token_revoked
- Account lockout: failed attempts, automatic lock, manual lock/unlock
- Tokens revoked on demand (logout endpoint)
- Admin lock/unlock API endpoints
- JWTAuthMiddleware: exempt paths, backward-compat fallback, RBAC, revoked tokens
- /api/v1/auth/login, /me, /logout, /users CRUD, role update, lock/unlock
"""

from __future__ import annotations

import time

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
    monkeypatch.setenv("BMT_JWT_SECRET", "test-secret-key-for-unit-tests-32ch")


# ---------------------------------------------------------------------------
# UserStore — basic CRUD
# ---------------------------------------------------------------------------


class TestUserStore:
    def test_create_and_get_user(self, store):
        user = store.create_user("alice", "TestSecret1ABC", "admin")
        assert user.username == "alice"
        assert user.role.value == "admin"
        assert user.id is not None

        fetched = store.get_user("alice")
        assert fetched is not None
        assert fetched.username == "alice"

    def test_password_is_hashed(self, store):
        store.create_user("bob", "SecurePass1!", "viewer")
        user = store.get_user("bob")
        assert user.password_hash != "SecurePass1!"
        assert user.password_hash.startswith("$2b$")

    def test_authenticate_valid(self, store):
        store.create_user("carol", "TestPasswd123X", "operator")
        authenticated = store.authenticate("carol", "TestPasswd123X")
        assert authenticated is not None
        assert authenticated.username == "carol"

    def test_authenticate_valid_resets_failed_count(self, store):
        store.create_user("reset_user", "CorrectPass1X", "viewer")
        # Induce a failure first
        store.authenticate("reset_user", "WrongPasswd1X")
        user = store.get_user("reset_user")
        assert user.failed_logins == 1
        # Now succeed
        result = store.authenticate("reset_user", "CorrectPass1X")
        assert result is not None
        user = store.get_user("reset_user")
        assert user.failed_logins == 0
        assert user.locked_until is None

    def test_authenticate_wrong_password(self, store):
        store.create_user("dave", "CorrectPass1X", "viewer")
        result = store.authenticate("dave", "WrongPasswd1X")
        assert result is None

    def test_authenticate_nonexistent(self, store):
        result = store.authenticate("nobody", "pass")
        assert result is None

    def test_duplicate_username_raises(self, store):
        store.create_user("eve", "SecurePass1!", "viewer")
        with pytest.raises(ValueError, match="already exists"):
            store.create_user("eve", "SecurePass2!", "admin")

    def test_invalid_role_raises(self, store):
        with pytest.raises(ValueError, match="Invalid role"):
            store.create_user("frank", "SecurePass1!", "superuser")

    def test_list_users(self, store):
        store.create_user("u1", "SecurePass1!", "viewer")
        store.create_user("u2", "SecurePass1!", "operator")
        users = store.list_users()
        assert len(users) == 2
        names = {u.username for u in users}
        assert names == {"u1", "u2"}

    def test_delete_user(self, store):
        store.create_user("victim", "SecurePass1!", "viewer")
        assert store.delete_user("victim") is True
        assert store.get_user("victim") is None

    def test_delete_nonexistent_returns_false(self, store):
        assert store.delete_user("ghost") is False

    def test_has_users(self, store):
        assert store.has_users() is False
        store.create_user("x", "SecurePass1!", "viewer")
        assert store.has_users() is True

    def test_update_user_role(self, store):
        store.create_user("role_user", "SecurePass1!", "viewer")
        updated = store.update_user_role("role_user", "admin")
        assert updated is True
        assert store.get_user("role_user").role.value == "admin"

    def test_update_role_invalid_raises(self, store):
        store.create_user("role_user2", "SecurePass1!", "viewer")
        with pytest.raises(ValueError, match="Invalid role"):
            store.update_user_role("role_user2", "superuser")

    def test_update_role_nonexistent_returns_false(self, store):
        assert store.update_user_role("nobody", "admin") is False


# ---------------------------------------------------------------------------
# Password complexity — BMTOS-64
# ---------------------------------------------------------------------------


class TestPasswordComplexity:
    def test_valid_password_accepted(self, store):
        user = store.create_user("pw_ok", "ValidPass12!", "viewer")
        assert user.username == "pw_ok"

    def test_too_short_raises(self, store):
        with pytest.raises(ValueError, match="12 characters"):
            store.create_user("pw_short", "Short1A", "viewer")

    def test_no_uppercase_raises(self, store):
        with pytest.raises(ValueError, match="uppercase"):
            store.create_user("pw_noup", "nouppercase1234", "viewer")

    def test_no_digit_raises(self, store):
        with pytest.raises(ValueError, match="digit"):
            store.create_user("pw_nodig", "NoDigitsHereXY", "viewer")

    def test_skip_complexity_allowed_for_internal(self, store):
        # skip_complexity=True is used for dev-mode bootstrap only
        user = store.create_user("pw_skip", "weak", "viewer", skip_complexity=True)
        assert user.username == "pw_skip"

    def test_validate_password_complexity_function_directly(self):
        from bmt_ai_os.controller.auth import validate_password_complexity

        # Valid password should not raise
        validate_password_complexity("ValidPass12!")

    def test_validate_password_complexity_short(self):
        from bmt_ai_os.controller.auth import validate_password_complexity

        with pytest.raises(ValueError, match="12 characters"):
            validate_password_complexity("Short1A")

    def test_validate_password_complexity_no_uppercase(self):
        from bmt_ai_os.controller.auth import validate_password_complexity

        with pytest.raises(ValueError, match="uppercase"):
            validate_password_complexity("nouppercase123")

    def test_validate_password_complexity_no_digit(self):
        from bmt_ai_os.controller.auth import validate_password_complexity

        with pytest.raises(ValueError, match="digit"):
            validate_password_complexity("NoDigitssHereXY")


# ---------------------------------------------------------------------------
# Account lockout
# ---------------------------------------------------------------------------


class TestAccountLockout:
    def test_failed_logins_incremented(self, store):
        store.create_user("fail_user", "CorrectPass1X", "viewer")
        for i in range(3):
            store.authenticate("fail_user", "WrongPasswd1X")
        user = store.get_user("fail_user")
        assert user.failed_logins == 3

    def test_locked_after_threshold(self, store):
        import bmt_ai_os.controller.auth as auth_mod

        store.create_user("lockme", "CorrectPass1X", "viewer")
        threshold = auth_mod._MAX_FAILED_LOGINS
        for _ in range(threshold):
            result = store.authenticate("lockme", "WrongPasswd1X")
        assert result is None
        user = store.get_user("lockme")
        assert user.locked_until is not None
        assert user.is_locked() is True

    def test_locked_account_cannot_authenticate(self, store):
        store.create_user("locked_user", "CorrectPass1X", "viewer")
        store.lock_account("locked_user", duration_seconds=3600)
        result = store.authenticate("locked_user", "CorrectPass1X")
        assert result is None

    def test_manual_lock_account(self, store):
        store.create_user("manual_lock", "SecurePass1!", "viewer")
        locked = store.lock_account("manual_lock", duration_seconds=600)
        assert locked is True
        user = store.get_user("manual_lock")
        assert user.is_locked() is True

    def test_manual_lock_nonexistent_returns_false(self, store):
        assert store.lock_account("ghost", duration_seconds=600) is False

    def test_unlock_account(self, store):
        store.create_user("unlock_me", "SecurePass1!", "viewer")
        store.lock_account("unlock_me", duration_seconds=3600)
        assert store.get_user("unlock_me").is_locked() is True

        unlocked = store.unlock_account("unlock_me")
        assert unlocked is True
        user = store.get_user("unlock_me")
        assert user.is_locked() is False
        assert user.failed_logins == 0

    def test_unlock_nonexistent_returns_false(self, store):
        assert store.unlock_account("ghost") is False

    def test_is_locked_returns_false_when_no_lock(self, store):
        store.create_user("clean_user", "SecurePass1!", "viewer")
        user = store.get_user("clean_user")
        assert user.is_locked() is False

    def test_lock_expiry(self, store, monkeypatch):
        """After the lock window passes, is_locked() returns False."""
        store.create_user("expiry_user", "SecurePass1!", "viewer")
        # Lock for 1 second in the past
        store.lock_account("expiry_user", duration_seconds=1)
        user = store.get_user("expiry_user")
        # Travel forward in time by patching time.time
        original_time = time.time
        monkeypatch.setattr(time, "time", lambda: original_time() + 2)
        assert user.is_locked() is False


# ---------------------------------------------------------------------------
# Token blacklist
# ---------------------------------------------------------------------------


class TestTokenBlacklist:
    def test_revoke_and_check(self, store):
        jti = "test-jti-001"
        expires_at = time.time() + 3600
        assert store.is_token_revoked(jti) is False
        store.revoke_token(jti, expires_at)
        assert store.is_token_revoked(jti) is True

    def test_revoke_idempotent(self, store):
        jti = "test-jti-002"
        expires_at = time.time() + 3600
        store.revoke_token(jti, expires_at)
        store.revoke_token(jti, expires_at)  # should not raise
        assert store.is_token_revoked(jti) is True

    def test_purge_expired_entries(self, store):
        past = time.time() - 1
        future = time.time() + 3600
        store.revoke_token("expired-jti", past)
        store.revoke_token("active-jti", future)
        removed = store.purge_expired_blacklist_entries()
        assert removed == 1
        assert store.is_token_revoked("expired-jti") is False
        assert store.is_token_revoked("active-jti") is True


# ---------------------------------------------------------------------------
# JWT utilities
# ---------------------------------------------------------------------------


class TestJWT:
    def test_create_and_verify_token(self, store):
        from bmt_ai_os.controller.auth import create_token, verify_token

        user = store.create_user("jwt_user", "SecurePass1!", "admin")
        token = create_token(user)
        assert isinstance(token, str)

        payload = verify_token(token)
        assert payload["sub"] == "jwt_user"
        assert payload["role"] == "admin"
        assert "exp" in payload
        assert "jti" in payload  # must include JWT ID

    def test_jti_is_unique(self, store):
        from bmt_ai_os.controller.auth import create_token, verify_token

        user = store.create_user("jti_user", "SecurePass1!", "viewer")
        t1 = create_token(user)
        t2 = create_token(user)
        p1 = verify_token(t1)
        p2 = verify_token(t2)
        assert p1["jti"] != p2["jti"]

    def test_revoked_token_raises(self, store):
        import jwt as pyjwt

        from bmt_ai_os.controller.auth import create_token, verify_token

        user = store.create_user("revoke_jwt_user", "SecurePass1!", "viewer")
        token = create_token(user)
        payload = verify_token(token)
        jti = payload["jti"]
        expires_at = float(payload["exp"])

        store.revoke_token(jti, expires_at)

        with pytest.raises(pyjwt.InvalidTokenError, match="revoked"):
            verify_token(token, store=store)

    def test_verify_without_store_skips_blacklist(self, store):
        """verify_token() with no store argument does not check the blacklist."""
        from bmt_ai_os.controller.auth import create_token, verify_token

        user = store.create_user("no_store_user", "SecurePass1!", "viewer")
        token = create_token(user)
        payload = verify_token(token)
        jti = payload["jti"]
        expires_at = float(payload["exp"])

        store.revoke_token(jti, expires_at)
        # No store passed — should succeed
        result = verify_token(token)
        assert result["sub"] == "no_store_user"

    def test_expired_token_raises(self, store, monkeypatch):
        import jwt as pyjwt

        from bmt_ai_os.controller.auth import create_token, verify_token

        user = store.create_user("expired_user", "SecurePass1!", "viewer")

        import bmt_ai_os.controller.auth as auth_mod

        monkeypatch.setattr(auth_mod, "_JWT_EXPIRY_SECONDS", -1)
        token = create_token(user)

        with pytest.raises(pyjwt.ExpiredSignatureError):
            verify_token(token)

    def test_tampered_token_raises(self, store):
        import jwt as pyjwt

        from bmt_ai_os.controller.auth import create_token, verify_token

        user = store.create_user("tamper_user", "SecurePass1!", "viewer")
        token = create_token(user)
        tampered = token[:-4] + "XXXX"

        with pytest.raises(pyjwt.PyJWTError):
            verify_token(tampered)

    def test_missing_secret_raises(self, monkeypatch, store):
        monkeypatch.delenv("BMT_JWT_SECRET", raising=False)
        from bmt_ai_os.controller.auth import create_token

        user = store.create_user("nosecret_user", "SecurePass1!", "viewer")
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

    @app.get("/api/v1/users")
    async def users():
        return {"users": []}

    @app.post("/api/v1/users")
    async def create_user():
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
        resp = client.get("/api/v1/users")
        assert resp.status_code == 200

    def test_no_users_api_key_fallthrough(self, tmp_db, monkeypatch):
        """When no users and BMT_API_KEY is set, JWT middleware skips to next."""
        monkeypatch.setenv("BMT_API_KEY", "test-key")
        app, client, _ = _make_app(tmp_db)
        # No JWT needed — falls through to whatever is next (no APIKeyMiddleware here)
        resp = client.get("/api/v1/users")
        assert resp.status_code == 200

    def test_missing_token_when_users_exist(self, tmp_db):
        app, client, store = _make_app(tmp_db)
        store.create_user("testuser", "SecurePass1!", "viewer")
        resp = client.get("/api/v1/users")
        assert resp.status_code == 401

    def test_valid_token_grants_access(self, tmp_db):
        from bmt_ai_os.controller.auth import create_token

        app, client, store = _make_app(tmp_db)
        user = store.create_user("validuser", "SecurePass1!", "viewer")
        token = create_token(user)
        resp = client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_viewer_forbidden_on_write(self, tmp_db):
        from bmt_ai_os.controller.auth import create_token

        app, client, store = _make_app(tmp_db)
        user = store.create_user("readonly", "SecurePass1!", "viewer")
        token = create_token(user)
        resp = client.post("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403

    def test_admin_allowed_on_write(self, tmp_db):
        from bmt_ai_os.controller.auth import create_token

        app, client, store = _make_app(tmp_db)
        user = store.create_user("superuser", "SecurePass1!", "admin")
        token = create_token(user)
        resp = client.post("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_invalid_token_returns_401(self, tmp_db):
        app, client, store = _make_app(tmp_db)
        store.create_user("someone", "SecurePass1!", "viewer")
        resp = client.get("/api/v1/users", headers={"Authorization": "Bearer not.a.real.token"})
        assert resp.status_code == 401

    def test_revoked_token_returns_401(self, tmp_db):
        from bmt_ai_os.controller.auth import create_token, verify_token

        app, client, store = _make_app(tmp_db)
        user = store.create_user("revoke_user", "SecurePass1!", "viewer")
        token = create_token(user)
        payload = verify_token(token)
        store.revoke_token(payload["jti"], float(payload["exp"]))

        resp = client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "token_revoked"


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
        store.create_user("loginuser", "SecretPass123X", "operator")

        resp = client.post(
            "/api/v1/auth/login", json={"username": "loginuser", "password": "SecretPass123X"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert body["role"] == "operator"
        assert body["username"] == "loginuser"

    def test_login_wrong_password(self, tmp_db):
        app, client, store = _make_auth_app(tmp_db)
        store.create_user("loginuser2", "CorrectPass1X", "viewer")

        resp = client.post(
            "/api/v1/auth/login", json={"username": "loginuser2", "password": "WrongPass999!"}
        )
        assert resp.status_code == 401

    def test_login_unknown_user(self, tmp_db):
        app, client, store = _make_auth_app(tmp_db)
        resp = client.post(
            "/api/v1/auth/login", json={"username": "ghost", "password": "SecurePass1!"}
        )
        assert resp.status_code == 401

    def test_login_locked_account(self, tmp_db):
        app, client, store = _make_auth_app(tmp_db)
        store.create_user("locked_login", "SecretPass123X", "viewer")
        store.lock_account("locked_login", duration_seconds=3600)

        resp = client.post(
            "/api/v1/auth/login", json={"username": "locked_login", "password": "SecurePass1!"}
        )
        assert resp.status_code == 401

    def test_me_returns_user_info(self, tmp_db):
        from bmt_ai_os.controller.auth import create_token

        app, client, store = _make_auth_app(tmp_db)
        user = store.create_user("meuser", "SecurePass1!", "admin")
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

    def test_logout_revokes_token(self, tmp_db):
        from bmt_ai_os.controller.auth import create_token

        app, client, store = _make_auth_app(tmp_db)
        user = store.create_user("logout_user", "SecurePass1!", "viewer")
        token = create_token(user)
        headers = {"Authorization": f"Bearer {token}"}

        # Logout
        resp = client.post("/api/v1/auth/logout", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["revoked"] is True

        # Subsequent request with same token should be rejected
        resp2 = client.get("/api/v1/auth/me", headers=headers)
        assert resp2.status_code == 401
        assert resp2.json()["error"]["code"] == "token_revoked"

    def test_create_user_by_admin(self, tmp_db):
        from bmt_ai_os.controller.auth import create_token

        app, client, store = _make_auth_app(tmp_db)
        admin = store.create_user("admin_user", "SecurePass1!", "admin")
        token = create_token(admin)
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post(
            "/api/v1/auth/users",
            json={"username": "new_user", "password": "SecurePass1!", "role": "viewer"},
            headers=headers,
        )
        assert resp.status_code in (200, 201)
        body = resp.json()
        assert body["username"] == "new_user"
        assert body["role"] == "viewer"

    def test_create_user_non_admin_forbidden(self, tmp_db):
        from bmt_ai_os.controller.auth import create_token

        app, client, store = _make_auth_app(tmp_db)
        op = store.create_user("operator_user", "SecurePass1!", "operator")
        token = create_token(op)
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post(
            "/api/v1/auth/users",
            json={"username": "new_user", "password": "SecurePass1!", "role": "viewer"},
            headers=headers,
        )
        assert resp.status_code == 403

    def test_list_users_by_admin(self, tmp_db):
        from bmt_ai_os.controller.auth import create_token

        app, client, store = _make_auth_app(tmp_db)
        admin = store.create_user("admin_user", "SecurePass1!", "admin")
        store.create_user("other_user", "SecurePass1!", "viewer")
        token = create_token(admin)

        resp = client.get("/api/v1/auth/users", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        usernames = {u["username"] for u in resp.json()}
        assert {"admin_user", "other_user"} <= usernames

    def test_delete_user_by_admin(self, tmp_db):
        from bmt_ai_os.controller.auth import create_token

        app, client, store = _make_auth_app(tmp_db)
        admin = store.create_user("admin_user", "SecurePass1!", "admin")
        store.create_user("doomed_user", "SecurePass1!", "viewer")
        token = create_token(admin)

        resp = client.delete(
            "/api/v1/auth/users/doomed_user",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        assert store.get_user("doomed_user") is None

    def test_delete_nonexistent_user_404(self, tmp_db):
        from bmt_ai_os.controller.auth import create_token

        app, client, store = _make_auth_app(tmp_db)
        admin = store.create_user("admin_user", "SecurePass1!", "admin")
        token = create_token(admin)

        resp = client.delete(
            "/api/v1/auth/users/ghost",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    def test_update_role_by_admin(self, tmp_db):
        from bmt_ai_os.controller.auth import create_token

        app, client, store = _make_auth_app(tmp_db)
        admin = store.create_user("admin_user", "SecurePass1!", "admin")
        store.create_user("promote_me", "SecurePass1!", "viewer")
        token = create_token(admin)

        resp = client.patch(
            "/api/v1/auth/users/promote_me/role",
            json={"role": "operator"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "operator"
        assert store.get_user("promote_me").role.value == "operator"

    def test_update_role_invalid_role(self, tmp_db):
        from bmt_ai_os.controller.auth import create_token

        app, client, store = _make_auth_app(tmp_db)
        admin = store.create_user("admin_user", "SecurePass1!", "admin")
        store.create_user("target_user", "SecurePass1!", "viewer")
        token = create_token(admin)

        resp = client.patch(
            "/api/v1/auth/users/target_user/role",
            json={"role": "superuser"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400

    def test_lock_account_by_admin(self, tmp_db):
        from bmt_ai_os.controller.auth import create_token

        app, client, store = _make_auth_app(tmp_db)
        admin = store.create_user("admin_user", "SecurePass1!", "admin")
        store.create_user("lock_target", "SecurePass1!", "viewer")
        token = create_token(admin)

        resp = client.post(
            "/api/v1/auth/users/lock_target/lock",
            json={"duration_seconds": 600},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["locked"] is True
        assert body["username"] == "lock_target"
        assert store.get_user("lock_target").is_locked() is True

    def test_lock_nonexistent_user_404(self, tmp_db):
        from bmt_ai_os.controller.auth import create_token

        app, client, store = _make_auth_app(tmp_db)
        admin = store.create_user("admin_user", "SecurePass1!", "admin")
        token = create_token(admin)

        resp = client.post(
            "/api/v1/auth/users/ghost/lock",
            json={"duration_seconds": 600},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    def test_unlock_account_by_admin(self, tmp_db):
        from bmt_ai_os.controller.auth import create_token

        app, client, store = _make_auth_app(tmp_db)
        admin = store.create_user("admin_user", "SecurePass1!", "admin")
        store.create_user("unlock_target", "SecurePass1!", "viewer")
        store.lock_account("unlock_target", duration_seconds=3600)
        token = create_token(admin)

        resp = client.post(
            "/api/v1/auth/users/unlock_target/unlock",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["unlocked"] is True
        assert store.get_user("unlock_target").is_locked() is False

    def test_unlock_nonexistent_user_404(self, tmp_db):
        from bmt_ai_os.controller.auth import create_token

        app, client, store = _make_auth_app(tmp_db)
        admin = store.create_user("admin_user", "SecurePass1!", "admin")
        token = create_token(admin)

        resp = client.post(
            "/api/v1/auth/users/ghost/unlock",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404
