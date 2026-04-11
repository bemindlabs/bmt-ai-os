"""Unit tests for bmt_ai_os.controller.middleware."""

from __future__ import annotations

import os
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bmt_ai_os.controller.middleware import (
    APIKeyMiddleware,
    RequestLoggingMiddleware,
    add_cors,
)

# ---------------------------------------------------------------------------
# APIKeyMiddleware
# ---------------------------------------------------------------------------


def _make_app_with_key(api_key: str | None = None) -> FastAPI:
    """Return a minimal FastAPI app with APIKeyMiddleware configured."""
    app = FastAPI()
    app.add_middleware(APIKeyMiddleware, api_key=api_key)

    @app.get("/protected")
    async def protected():
        return {"ok": True}

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    return app


class TestAPIKeyMiddleware:
    def test_allows_all_when_no_key_configured(self):
        app = _make_app_with_key(api_key=None)
        client = TestClient(app, raise_server_exceptions=True)
        # BMT_API_KEY must not be set
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BMT_API_KEY", None)
            resp = client.get("/protected")
        assert resp.status_code == 200

    def test_rejects_missing_bearer_token(self):
        app = _make_app_with_key(api_key="secret-key")
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/protected")
        assert resp.status_code == 401

    def test_rejects_wrong_key(self):
        app = _make_app_with_key(api_key="correct-key")
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/protected", headers={"Authorization": "Bearer wrong-key"})
        assert resp.status_code == 401

    def test_allows_correct_key(self):
        app = _make_app_with_key(api_key="my-secret")
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/protected", headers={"Authorization": "Bearer my-secret"})
        assert resp.status_code == 200

    def test_exempt_healthz_path(self):
        app = _make_app_with_key(api_key="secret")
        client = TestClient(app, raise_server_exceptions=True)
        # /healthz is exempt — no auth header needed
        resp = client.get("/healthz")
        assert resp.status_code == 200

    def test_reads_key_from_env(self):
        app = FastAPI()
        with patch.dict(os.environ, {"BMT_API_KEY": "env-key"}):
            app.add_middleware(APIKeyMiddleware)

            @app.get("/secret")
            async def secret():
                return {"ok": True}

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/secret")
        assert resp.status_code == 401

    def test_error_body_shape(self):
        app = _make_app_with_key(api_key="key")
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/protected")
        body = resp.json()
        assert "error" in body
        assert body["error"]["code"] == "invalid_api_key"


# ---------------------------------------------------------------------------
# add_cors
# ---------------------------------------------------------------------------


class TestAddCors:
    def test_adds_cors_middleware(self):
        app = FastAPI()
        add_cors(app)
        # The middleware stack should contain CORSMiddleware
        # user_middleware is a list of Middleware objects; check the cls attribute
        mw_types = [getattr(m, "cls", type(m)).__name__ for m in app.user_middleware]
        assert any("CORS" in name for name in mw_types)

    def test_custom_origins_from_env(self):
        app = FastAPI()
        with patch.dict(os.environ, {"BMT_CORS_ORIGINS": "https://custom.example.com"}):
            add_cors(app)
        # Should not raise; CORS headers would reflect the custom origin


# ---------------------------------------------------------------------------
# RequestLoggingMiddleware (smoke test via TestClient)
# ---------------------------------------------------------------------------


class TestRequestLoggingMiddleware:
    def test_logs_request(self, caplog):
        import logging

        app = FastAPI()
        app.add_middleware(RequestLoggingMiddleware)

        @app.get("/ping")
        async def ping():
            return {"pong": True}

        client = TestClient(app)
        with caplog.at_level(logging.INFO):
            resp = client.get("/ping")

        assert resp.status_code == 200
        # The middleware should emit a log line containing the path
        log_messages = " ".join(caplog.messages)
        assert "/ping" in log_messages
