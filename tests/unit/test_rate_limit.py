"""Unit tests for bmt_ai_os.controller.rate_limit.

Covers:
- SlidingWindowRateLimiter core logic (allow, deny, eviction, thread safety)
- _parse_rate config helper
- _client_ip extraction (direct + X-Forwarded-For)
- RateLimitDep FastAPI dependency (allows, 429 on excess, correct headers)
- Login and inference endpoint integration via TestClient
"""

from __future__ import annotations

import time

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset module-level limiter singletons before and after every test."""
    from bmt_ai_os.controller.rate_limit import _reset_singletons

    _reset_singletons()
    yield
    _reset_singletons()


# ---------------------------------------------------------------------------
# SlidingWindowRateLimiter — core
# ---------------------------------------------------------------------------


class TestSlidingWindowRateLimiter:
    def _make(self, limit: int = 3, window: int = 60):
        from bmt_ai_os.controller.rate_limit import SlidingWindowRateLimiter

        return SlidingWindowRateLimiter(limit=limit, window_seconds=window)

    def test_allows_up_to_limit(self):
        limiter = self._make(limit=3)
        for _ in range(3):
            allowed, _, _ = limiter.check("192.0.2.1")
            assert allowed is True

    def test_denies_over_limit(self):
        limiter = self._make(limit=3)
        for _ in range(3):
            limiter.check("192.0.2.1")
        allowed, remaining, _ = limiter.check("192.0.2.1")
        assert allowed is False
        assert remaining == 0

    def test_remaining_decrements(self):
        limiter = self._make(limit=5)
        _, remaining, _ = limiter.check("10.0.0.1")
        assert remaining == 4
        _, remaining, _ = limiter.check("10.0.0.1")
        assert remaining == 3

    def test_per_key_isolation(self):
        limiter = self._make(limit=2)
        limiter.check("1.1.1.1")
        limiter.check("1.1.1.1")
        # limit hit for 1.1.1.1 but not 2.2.2.2
        allowed_a, _, _ = limiter.check("1.1.1.1")
        allowed_b, _, _ = limiter.check("2.2.2.2")
        assert allowed_a is False
        assert allowed_b is True

    def test_reset_at_is_future(self):
        limiter = self._make(limit=1)
        limiter.check("x")
        _, _, reset_at = limiter.check("x")
        assert reset_at > time.time()

    def test_window_expiry_allows_again(self):
        """Requests outside the window no longer count."""
        from bmt_ai_os.controller.rate_limit import SlidingWindowRateLimiter

        limiter = SlidingWindowRateLimiter(limit=2, window_seconds=1)
        limiter.check("ip")
        limiter.check("ip")
        # Both slots used; third should be denied
        allowed, _, _ = limiter.check("ip")
        assert allowed is False

        # Wait for window to expire
        time.sleep(1.1)
        allowed, remaining, _ = limiter.check("ip")
        assert allowed is True
        assert remaining == 1  # one slot used (current request), one left

    def test_invalid_limit_raises(self):
        from bmt_ai_os.controller.rate_limit import SlidingWindowRateLimiter

        with pytest.raises(ValueError, match="limit must be positive"):
            SlidingWindowRateLimiter(limit=0, window_seconds=60)

    def test_invalid_window_raises(self):
        from bmt_ai_os.controller.rate_limit import SlidingWindowRateLimiter

        with pytest.raises(ValueError, match="window_seconds must be positive"):
            SlidingWindowRateLimiter(limit=5, window_seconds=0)

    def test_evict_expired_removes_empty_buckets(self):
        from bmt_ai_os.controller.rate_limit import SlidingWindowRateLimiter

        limiter = SlidingWindowRateLimiter(limit=10, window_seconds=1)
        limiter.check("evict-me")
        time.sleep(1.1)
        limiter.evict_expired()
        assert "evict-me" not in limiter._buckets

    def test_thread_safety(self):
        """Concurrent access from multiple threads must not corrupt state."""
        import threading

        from bmt_ai_os.controller.rate_limit import SlidingWindowRateLimiter

        limiter = SlidingWindowRateLimiter(limit=1000, window_seconds=60)
        errors: list[Exception] = []

        def worker():
            try:
                for _ in range(50):
                    limiter.check("shared-ip")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors


# ---------------------------------------------------------------------------
# _parse_rate
# ---------------------------------------------------------------------------


class TestParseRate:
    def test_valid_input(self):
        from bmt_ai_os.controller.rate_limit import _parse_rate

        assert _parse_rate("5:300") == (5, 300)
        assert _parse_rate("60:60") == (60, 60)
        assert _parse_rate(" 10 : 120 ") == (10, 120)

    def test_missing_colon_raises(self):
        from bmt_ai_os.controller.rate_limit import _parse_rate

        with pytest.raises(ValueError, match="Rate limit must be"):
            _parse_rate("60")

    def test_zero_limit_raises(self):
        from bmt_ai_os.controller.rate_limit import _parse_rate

        with pytest.raises(ValueError, match="positive"):
            _parse_rate("0:60")

    def test_zero_window_raises(self):
        from bmt_ai_os.controller.rate_limit import _parse_rate

        with pytest.raises(ValueError, match="positive"):
            _parse_rate("5:0")

    def test_non_integer_raises(self):
        from bmt_ai_os.controller.rate_limit import _parse_rate

        with pytest.raises(ValueError):
            _parse_rate("abc:60")


# ---------------------------------------------------------------------------
# _build_limiter — env var configuration
# ---------------------------------------------------------------------------


class TestBuildLimiter:
    def test_default_login_rate(self):
        from bmt_ai_os.controller.rate_limit import (
            _DEFAULT_LOGIN_RATE,
            _parse_rate,
            get_login_limiter,
        )

        limit, window = _parse_rate(_DEFAULT_LOGIN_RATE)
        limiter = get_login_limiter()
        assert limiter.limit == limit
        assert limiter.window_seconds == window

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("BMT_LOGIN_RATE_LIMIT", "10:120")
        from bmt_ai_os.controller.rate_limit import get_login_limiter

        limiter = get_login_limiter()
        assert limiter.limit == 10
        assert limiter.window_seconds == 120

    def test_malformed_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("BMT_INFERENCE_RATE_LIMIT", "bad-value")
        from bmt_ai_os.controller.rate_limit import (
            _DEFAULT_INFERENCE_RATE,
            _parse_rate,
            get_inference_limiter,
        )

        limit, window = _parse_rate(_DEFAULT_INFERENCE_RATE)
        limiter = get_inference_limiter()
        assert limiter.limit == limit
        assert limiter.window_seconds == window


# ---------------------------------------------------------------------------
# _client_ip
# ---------------------------------------------------------------------------


class TestClientIp:
    def _make_request(self, headers: dict, client: tuple | None = ("10.0.0.1", 9000)):
        """Build a Starlette Request with the given scope client and headers."""
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": client,
        }
        return Request(scope)

    def test_direct_connection(self):
        from bmt_ai_os.controller.rate_limit import _client_ip

        req = self._make_request({}, client=("203.0.113.5", 12345))
        assert _client_ip(req) == "203.0.113.5"

    def test_no_client_returns_unknown(self):
        from bmt_ai_os.controller.rate_limit import _client_ip

        req = self._make_request({}, client=None)
        assert _client_ip(req) == "unknown"

    def test_x_forwarded_for_single(self):
        from bmt_ai_os.controller.rate_limit import _client_ip

        req = self._make_request({"X-Forwarded-For": "198.51.100.1"})
        assert _client_ip(req) == "198.51.100.1"

    def test_x_forwarded_for_chain(self):
        from bmt_ai_os.controller.rate_limit import _client_ip

        req = self._make_request({"X-Forwarded-For": "203.0.113.10, 10.0.0.1, 172.16.0.1"})
        assert _client_ip(req) == "203.0.113.10"


# ---------------------------------------------------------------------------
# RateLimitDep FastAPI dependency — via TestClient
# ---------------------------------------------------------------------------


def _make_limited_app(limit: int = 3, window: int = 60):
    """Return a FastAPI TestClient with a rate-limited endpoint."""
    from bmt_ai_os.controller.rate_limit import RateLimitDep, SlidingWindowRateLimiter

    limiter = SlidingWindowRateLimiter(limit=limit, window_seconds=window)
    dep = RateLimitDep(lambda: limiter)

    app = FastAPI()

    @app.get("/test", dependencies=[Depends(dep)])
    async def endpoint():
        return {"ok": True}

    return TestClient(app, raise_server_exceptions=False)


class TestRateLimitDep:
    def test_allowed_requests_return_200(self):
        client = _make_limited_app(limit=5)
        for _ in range(5):
            resp = client.get("/test")
            assert resp.status_code == 200

    def test_exceeded_returns_429(self):
        client = _make_limited_app(limit=2)
        client.get("/test")
        client.get("/test")
        resp = client.get("/test")
        assert resp.status_code == 429

    def test_rate_limit_headers_present_on_allowed(self):
        client = _make_limited_app(limit=10)
        resp = client.get("/test")
        assert resp.status_code == 200
        assert "x-ratelimit-limit" in resp.headers
        assert "x-ratelimit-remaining" in resp.headers
        assert "x-ratelimit-reset" in resp.headers

    def test_rate_limit_headers_present_on_429(self):
        client = _make_limited_app(limit=1)
        client.get("/test")
        resp = client.get("/test")
        assert resp.status_code == 429
        assert resp.headers["x-ratelimit-limit"] == "1"
        assert resp.headers["x-ratelimit-remaining"] == "0"
        assert "x-ratelimit-reset" in resp.headers
        assert "retry-after" in resp.headers

    def test_remaining_header_decrements(self):
        client = _make_limited_app(limit=5)
        resp1 = client.get("/test")
        resp2 = client.get("/test")
        remaining1 = int(resp1.headers["x-ratelimit-remaining"])
        remaining2 = int(resp2.headers["x-ratelimit-remaining"])
        assert remaining1 == 4
        assert remaining2 == 3

    def test_limit_header_matches_configured_limit(self):
        client = _make_limited_app(limit=7)
        resp = client.get("/test")
        assert resp.headers["x-ratelimit-limit"] == "7"

    def test_429_error_body_structure(self):
        client = _make_limited_app(limit=1)
        client.get("/test")
        resp = client.get("/test")
        body = resp.json()
        assert "detail" in body
        detail = body["detail"]
        assert detail["code"] == "rate_limit_exceeded"
        assert detail["type"] == "rate_limit_error"


# ---------------------------------------------------------------------------
# Login endpoint integration
# ---------------------------------------------------------------------------


def _make_login_app(tmp_db: str, login_limit: int = 3):
    """Return a TestClient with auth routes and a patched login rate limiter."""
    import bmt_ai_os.controller.auth as auth_mod
    import bmt_ai_os.controller.rate_limit as rl_mod
    from bmt_ai_os.controller.auth import JWTAuthMiddleware, UserStore
    from bmt_ai_os.controller.auth_routes import router as auth_router
    from bmt_ai_os.controller.rate_limit import SlidingWindowRateLimiter

    store = UserStore(db_path=tmp_db)
    auth_mod._default_store = store

    # Swap the module-level login limiter singleton so the existing
    # login_rate_limit dependency picks it up (it calls get_login_limiter())
    rl_mod._login_limiter = SlidingWindowRateLimiter(limit=login_limit, window_seconds=300)

    app = FastAPI()
    app.add_middleware(JWTAuthMiddleware, store=store)
    app.include_router(auth_router)

    return TestClient(app, raise_server_exceptions=False), store


class TestLoginRateLimit:
    def test_login_rate_limit_blocks_after_limit(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BMT_JWT_SECRET", "test-secret-key-for-unit-tests-32b")
        tmp_db = str(tmp_path / "auth.db")

        client, store = _make_login_app(tmp_db, login_limit=3)
        store.create_user("alice", "SecurePass1!", "viewer")

        # 3 attempts should succeed or 401 (wrong password), but never 429
        for _ in range(3):
            resp = client.post(
                "/api/v1/auth/login", json={"username": "alice", "password": "WrongPass1X!"}
            )
            assert resp.status_code in (401, 200)

        # 4th attempt: rate limit exceeded
        resp = client.post(
            "/api/v1/auth/login", json={"username": "alice", "password": "WrongPass1X!"}
        )
        assert resp.status_code == 429

    def test_login_success_within_limit_has_headers(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BMT_JWT_SECRET", "test-secret-key-for-unit-tests-32b")
        tmp_db = str(tmp_path / "auth.db")

        client, store = _make_login_app(tmp_db, login_limit=5)
        store.create_user("bob", "SecurePass1!", "admin")

        resp = client.post(
            "/api/v1/auth/login", json={"username": "bob", "password": "SecurePass1!"}
        )
        assert resp.status_code == 200
        assert "x-ratelimit-limit" in resp.headers
        assert "x-ratelimit-remaining" in resp.headers
        assert "x-ratelimit-reset" in resp.headers

    def test_login_429_has_retry_after(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BMT_JWT_SECRET", "test-secret-key-for-unit-tests-32b")
        tmp_db = str(tmp_path / "auth.db")

        client, _ = _make_login_app(tmp_db, login_limit=1)
        client.post("/api/v1/auth/login", json={"username": "x", "password": "TestPassword1X"})
        resp = client.post(
            "/api/v1/auth/login", json={"username": "x", "password": "TestPassword1X"}
        )

        assert resp.status_code == 429
        assert "retry-after" in resp.headers


# ---------------------------------------------------------------------------
# Inference endpoint integration
# ---------------------------------------------------------------------------


def _make_inference_client(inference_limit: int = 3):
    """Return a TestClient with OpenAI-compat routes and a tight inference limiter."""
    from unittest.mock import AsyncMock, MagicMock

    import bmt_ai_os.controller.rate_limit as rl_mod
    from bmt_ai_os.controller.openai_compat import router as openai_router
    from bmt_ai_os.controller.rate_limit import SlidingWindowRateLimiter

    # Swap the module-level inference limiter singleton
    rl_mod._inference_limiter = SlidingWindowRateLimiter(limit=inference_limit, window_seconds=60)

    # Mock provider registry
    mock_response = MagicMock()
    mock_response.content = "Hello!"
    mock_response.model = "test-model"
    mock_response.input_tokens = 5
    mock_response.output_tokens = 3

    mock_provider = MagicMock()
    mock_provider.name = "test-provider"
    mock_provider.chat = AsyncMock(return_value=mock_response)

    mock_registry = MagicMock()
    mock_registry.get_active.return_value = mock_provider

    app = FastAPI()
    app.include_router(openai_router)

    return TestClient(app, raise_server_exceptions=False), mock_registry


class TestInferenceRateLimit:
    def test_inference_rate_limit_blocks_after_limit(self, monkeypatch):
        client, mock_registry = _make_inference_client(inference_limit=2)

        import bmt_ai_os.controller.openai_compat as oc_mod

        monkeypatch.setattr(oc_mod, "_get_provider_router", lambda: mock_registry)

        payload = {"model": "test", "messages": [{"role": "user", "content": "hi"}]}

        for _ in range(2):
            resp = client.post("/v1/chat/completions", json=payload)
            assert resp.status_code == 200

        resp = client.post("/v1/chat/completions", json=payload)
        assert resp.status_code == 429

    def test_inference_headers_on_allowed_request(self, monkeypatch):
        client, mock_registry = _make_inference_client(inference_limit=10)

        import bmt_ai_os.controller.openai_compat as oc_mod

        monkeypatch.setattr(oc_mod, "_get_provider_router", lambda: mock_registry)

        payload = {"model": "test", "messages": [{"role": "user", "content": "hello"}]}
        resp = client.post("/v1/chat/completions", json=payload)
        assert resp.status_code == 200
        assert "x-ratelimit-limit" in resp.headers
        assert resp.headers["x-ratelimit-limit"] == "10"

    def test_completions_endpoint_rate_limited(self, monkeypatch):
        client, mock_registry = _make_inference_client(inference_limit=1)

        import bmt_ai_os.controller.openai_compat as oc_mod

        monkeypatch.setattr(oc_mod, "_get_provider_router", lambda: mock_registry)

        payload = {"model": "test", "prompt": "complete this"}
        resp = client.post("/v1/completions", json=payload)
        assert resp.status_code == 200

        resp = client.post("/v1/completions", json=payload)
        assert resp.status_code == 429

    def test_inference_429_has_retry_after(self, monkeypatch):
        client, mock_registry = _make_inference_client(inference_limit=1)

        import bmt_ai_os.controller.openai_compat as oc_mod

        monkeypatch.setattr(oc_mod, "_get_provider_router", lambda: mock_registry)

        payload = {"model": "test", "messages": [{"role": "user", "content": "hi"}]}
        client.post("/v1/chat/completions", json=payload)
        resp = client.post("/v1/chat/completions", json=payload)

        assert resp.status_code == 429
        assert "retry-after" in resp.headers


# ---------------------------------------------------------------------------
# Sensitive rate-limiter singleton
# ---------------------------------------------------------------------------


class TestSensitiveRateLimiter:
    """Verify the sensitive_rate_limit dependency works like login/inference."""

    def test_get_sensitive_limiter_returns_singleton(self, monkeypatch):
        monkeypatch.setenv("BMT_SENSITIVE_RATE_LIMIT", "10:30")
        from bmt_ai_os.controller.rate_limit import _reset_singletons, get_sensitive_limiter

        _reset_singletons()
        a = get_sensitive_limiter()
        b = get_sensitive_limiter()
        assert a is b
        assert a.limit == 10
        assert a.window_seconds == 30

    def test_sensitive_rate_limit_default(self):
        from bmt_ai_os.controller.rate_limit import get_sensitive_limiter

        limiter = get_sensitive_limiter()
        assert limiter.limit == 20
        assert limiter.window_seconds == 60

    def test_sensitive_dep_returns_429(self):
        # Override the singleton with a strict 1-per-minute limiter
        import bmt_ai_os.controller.rate_limit as rl_mod
        from bmt_ai_os.controller.rate_limit import (
            SlidingWindowRateLimiter,
            sensitive_rate_limit,
        )

        rl_mod._sensitive_limiter = SlidingWindowRateLimiter(limit=1, window_seconds=60)

        app = FastAPI()

        @app.post("/keys", dependencies=[Depends(sensitive_rate_limit)])
        def create_key():
            return {"ok": True}

        client = TestClient(app)
        assert client.post("/keys").status_code == 200
        assert client.post("/keys").status_code == 429
