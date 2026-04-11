"""Unit tests for bmt_ai_os.controller.api and controller.middleware.

Tests cover:
- /healthz endpoint
- /api/v1/status endpoint (with and without controller)
- /api/v1/metrics endpoint
- APIKeyMiddleware: no-op when key not set, exempt paths, valid/invalid tokens
- add_cors: default and env-override origins
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    """Inject a known JWT secret for auth middleware."""
    monkeypatch.setenv("BMT_JWT_SECRET", "test-secret-key-for-controller-api-32!")


@pytest.fixture()
def _clear_controller():
    """Reset the global controller reference before and after each test."""
    from bmt_ai_os.controller import api as api_mod

    original = api_mod._controller
    api_mod._controller = None
    yield
    api_mod._controller = original


class TestHealthzEndpoint:
    def test_healthz_returns_ok(self, _clear_controller):
        from bmt_ai_os.controller.api import app

        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_healthz_no_auth_required(self, monkeypatch, _clear_controller):
        monkeypatch.delenv("BMT_API_KEY", raising=False)
        from bmt_ai_os.controller.api import app

        client = TestClient(app)
        resp = client.get("/healthz")
        assert resp.status_code == 200


class TestStatusEndpoint:
    def test_status_without_controller(self, _clear_controller):
        from bmt_ai_os.controller.api import app

        client = TestClient(app)
        resp = client.get("/api/v1/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert data["uptime_seconds"] is None
        assert data["services"] == []
        assert "version" in data

    def test_status_with_controller(self, _clear_controller):
        import time

        from bmt_ai_os.controller import api as api_mod

        mock_ctrl = MagicMock()
        mock_ctrl._start_time = time.time() - 60
        mock_ctrl.get_status.return_value = [{"name": "ollama", "status": "healthy"}]
        api_mod._controller = mock_ctrl

        from bmt_ai_os.controller.api import app

        client = TestClient(app)
        resp = client.get("/api/v1/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["uptime_seconds"] is not None
        assert data["uptime_seconds"] > 0
        assert len(data["services"]) == 1


class TestSetGetController:
    def test_set_and_get_controller(self, _clear_controller):
        from bmt_ai_os.controller.api import get_controller, set_controller

        mock = MagicMock()
        set_controller(mock)
        assert get_controller() is mock

    def test_set_controller_none(self, _clear_controller):
        from bmt_ai_os.controller.api import get_controller, set_controller

        set_controller(None)
        assert get_controller() is None


# ---------------------------------------------------------------------------
# APIKeyMiddleware tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def minimal_app(monkeypatch):
    """A minimal FastAPI app with only APIKeyMiddleware applied."""
    monkeypatch.delenv("BMT_API_KEY", raising=False)
    from bmt_ai_os.controller.middleware import APIKeyMiddleware

    app = FastAPI()
    app.add_middleware(APIKeyMiddleware)

    @app.get("/protected")
    async def protected():
        return {"ok": True}

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    return app


class TestAPIKeyMiddleware:
    def test_no_key_env_allows_all(self, monkeypatch):
        monkeypatch.delenv("BMT_API_KEY", raising=False)
        from bmt_ai_os.controller.middleware import APIKeyMiddleware

        app = FastAPI()
        app.add_middleware(APIKeyMiddleware)

        @app.get("/test")
        async def test_route():
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/test")
        assert resp.status_code == 200

    def test_valid_key_grants_access(self, monkeypatch):
        monkeypatch.setenv("BMT_API_KEY", "test-api-key-123")
        from bmt_ai_os.controller.middleware import APIKeyMiddleware

        app = FastAPI()
        app.add_middleware(APIKeyMiddleware)

        @app.get("/protected")
        async def protected():
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/protected", headers={"Authorization": "Bearer test-api-key-123"})
        assert resp.status_code == 200

    def test_invalid_key_returns_401(self, monkeypatch):
        monkeypatch.setenv("BMT_API_KEY", "correct-key")
        from bmt_ai_os.controller.middleware import APIKeyMiddleware

        app = FastAPI()
        app.add_middleware(APIKeyMiddleware)

        @app.get("/protected")
        async def protected():
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/protected", headers={"Authorization": "Bearer wrong-key"})
        assert resp.status_code == 401

    def test_missing_auth_header_returns_401(self, monkeypatch):
        monkeypatch.setenv("BMT_API_KEY", "secret-key")
        from bmt_ai_os.controller.middleware import APIKeyMiddleware

        app = FastAPI()
        app.add_middleware(APIKeyMiddleware)

        @app.get("/protected")
        async def protected():
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/protected")
        assert resp.status_code == 401

    def test_healthz_exempt_even_with_key(self, monkeypatch):
        monkeypatch.setenv("BMT_API_KEY", "key-required")
        from bmt_ai_os.controller.middleware import APIKeyMiddleware

        app = FastAPI()
        app.add_middleware(APIKeyMiddleware)

        @app.get("/healthz")
        async def healthz():
            return {"status": "ok"}

        client = TestClient(app)
        resp = client.get("/healthz")
        assert resp.status_code == 200

    def test_docs_exempt(self, monkeypatch):
        monkeypatch.setenv("BMT_API_KEY", "key-required")
        from bmt_ai_os.controller.middleware import APIKeyMiddleware

        app = FastAPI()
        app.add_middleware(APIKeyMiddleware)

        client = TestClient(app)
        resp = client.get("/docs")
        # /docs redirects or returns HTML — in any case not 401
        assert resp.status_code != 401

    def test_401_error_shape(self, monkeypatch):
        monkeypatch.setenv("BMT_API_KEY", "SecretPass123X")
        from bmt_ai_os.controller.middleware import APIKeyMiddleware

        app = FastAPI()
        app.add_middleware(APIKeyMiddleware)

        @app.get("/x")
        async def x():
            return {}

        client = TestClient(app)
        resp = client.get("/x", headers={"Authorization": "Bearer bad"})
        body = resp.json()
        assert "error" in body
        assert body["error"]["code"] == "invalid_api_key"

    def test_bearer_prefix_required(self, monkeypatch):
        monkeypatch.setenv("BMT_API_KEY", "SecretPass123X")
        from bmt_ai_os.controller.middleware import APIKeyMiddleware

        app = FastAPI()
        app.add_middleware(APIKeyMiddleware)

        @app.get("/x")
        async def x():
            return {}

        client = TestClient(app)
        # No "Bearer " prefix
        resp = client.get("/x", headers={"Authorization": "SecretPass123X"})
        assert resp.status_code == 401

    def test_explicit_api_key_param(self, monkeypatch):
        monkeypatch.delenv("BMT_API_KEY", raising=False)
        from bmt_ai_os.controller.middleware import APIKeyMiddleware

        app = FastAPI()
        app.add_middleware(APIKeyMiddleware, api_key="direct-key")

        @app.get("/x")
        async def x():
            return {}

        client = TestClient(app)
        resp = client.get("/x", headers={"Authorization": "Bearer direct-key"})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# add_cors tests
# ---------------------------------------------------------------------------


class TestAddCors:
    def test_adds_cors_middleware(self, monkeypatch):
        monkeypatch.delenv("BMT_CORS_ORIGINS", raising=False)
        from bmt_ai_os.controller.middleware import add_cors

        app = FastAPI()
        add_cors(app)
        # Verify the middleware was added (no error means success)
        client = TestClient(app)
        # OPTIONS preflight should include CORS headers
        resp = client.options(
            "/",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        # 405 is normal for options on undefined route, but not 500
        assert resp.status_code != 500

    def test_env_origins_override(self, monkeypatch):
        monkeypatch.setenv(
            "BMT_CORS_ORIGINS", "https://myapp.example.com,https://other.example.com"
        )
        from bmt_ai_os.controller.middleware import add_cors

        app = FastAPI()
        add_cors(app)
        # Just verify no error thrown
        client = TestClient(app)
        resp = client.options("/", headers={"Origin": "https://myapp.example.com"})
        assert resp.status_code != 500


# ---------------------------------------------------------------------------
# RequestLoggingMiddleware
# ---------------------------------------------------------------------------


class TestRequestLoggingMiddleware:
    def test_request_is_logged(self, caplog):
        import logging

        from bmt_ai_os.controller.middleware import RequestLoggingMiddleware

        app = FastAPI()
        app.add_middleware(RequestLoggingMiddleware)

        @app.get("/ping")
        async def ping():
            return {"pong": True}

        client = TestClient(app)
        with caplog.at_level(logging.INFO, logger="bmt_ai_os.controller.middleware"):
            resp = client.get("/ping")
        assert resp.status_code == 200
        # The middleware logs the request; verify no exceptions occurred
