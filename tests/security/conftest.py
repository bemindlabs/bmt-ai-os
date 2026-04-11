"""Security test fixtures — isolated controller for adversarial testing."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def sec_env(tmp_path: Path) -> dict[str, str]:
    return {
        "BMT_AUTH_DB": str(tmp_path / "auth.db"),
        "BMT_JWT_SECRET": "security-test-secret-32-bytes-long!!",
        "BMT_PLUGIN_STATE": str(tmp_path / "plugins.json"),
        "BMT_PLUGIN_DIR": str(tmp_path / "plugins"),
        # Raise rate limits high enough for adversarial test suites
        "BMT_LOGIN_RATE_LIMIT": "1000:300",
        "BMT_INFERENCE_RATE_LIMIT": "1000:60",
    }


@pytest.fixture
def sec_client(sec_env: dict[str, str], tmp_path: Path) -> TestClient:
    (tmp_path / "plugins").mkdir(exist_ok=True)

    import bmt_ai_os.controller.auth as auth_mod
    import bmt_ai_os.controller.rate_limit as rl_mod

    orig_store = getattr(auth_mod, "_default_store", None)
    orig_login_limiter = rl_mod._login_limiter
    orig_inference_limiter = rl_mod._inference_limiter

    with patch.dict(os.environ, sec_env):
        auth_mod._default_store = None
        rl_mod._login_limiter = None
        rl_mod._inference_limiter = None

        from bmt_ai_os.controller.api import app

        yield TestClient(app, raise_server_exceptions=False)

    auth_mod._default_store = orig_store
    rl_mod._login_limiter = orig_login_limiter
    rl_mod._inference_limiter = orig_inference_limiter


@pytest.fixture
def admin_headers(sec_client: TestClient, sec_env: dict[str, str]) -> dict[str, str]:
    with patch.dict(os.environ, sec_env):
        from bmt_ai_os.controller.auth import Role, UserStore

        store = UserStore(db_path=sec_env["BMT_AUTH_DB"])
        store.create_user("secadmin", "SecureP@ss123", Role.admin)

    resp = sec_client.post(
        "/api/v1/auth/login",
        json={"username": "secadmin", "password": "SecureP@ss123"},
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}
