"""E2E test fixtures — full integrated controller with all Production Hardening features."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def e2e_env(tmp_path: Path) -> dict[str, str]:
    """Environment variables for an isolated E2E test run."""
    return {
        "BMT_AUTH_DB": str(tmp_path / "auth.db"),
        "BMT_JWT_SECRET": "e2e-test-secret-key-at-least-32-bytes!!",
        "BMT_PLUGIN_STATE": str(tmp_path / "plugins.json"),
        "BMT_PLUGIN_DIR": str(tmp_path / "plugins"),
        "BMT_LOG_FORMAT": "json",
    }


@pytest.fixture
def app(e2e_env: dict[str, str], tmp_path: Path):
    """Fully integrated FastAPI app with all routers and middleware."""
    (tmp_path / "plugins").mkdir(exist_ok=True)

    import bmt_ai_os.controller.auth as auth_mod

    # Save and restore module-level singleton to avoid polluting other tests
    orig_store = getattr(auth_mod, "_default_store", None)

    with patch.dict(os.environ, e2e_env):
        # Reset the singleton so it picks up the new env vars
        auth_mod._default_store = None

        from bmt_ai_os.controller.api import app as _app

        yield _app

    # Restore original state
    auth_mod._default_store = orig_store


@pytest.fixture
def client(app) -> TestClient:
    """TestClient for the integrated app."""
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def admin_token(client: TestClient, e2e_env: dict[str, str]) -> str:
    """Create an admin user and return a valid JWT token."""
    with patch.dict(os.environ, e2e_env):
        from bmt_ai_os.controller.auth import Role, UserStore

        store = UserStore(db_path=e2e_env["BMT_AUTH_DB"])
        store.create_user("admin", "admin-password-123", Role.admin)

        resp = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin-password-123"},
        )
        assert resp.status_code == 200, f"Login failed: {resp.text}"
        return resp.json()["access_token"]


@pytest.fixture
def auth_headers(admin_token: str) -> dict[str, str]:
    """Authorization headers with admin JWT."""
    return {"Authorization": f"Bearer {admin_token}"}
