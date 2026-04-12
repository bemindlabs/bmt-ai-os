"""Unit tests for bmt_ai_os.secret_files.read_secret.

Covers:
- Secret resolved from /run/secrets/<name> file (preferred path)
- Secret resolved from environment variable with warning logged
- Default value returned when neither file nor env var is present
- Empty secrets file falls through to env var
- Unreadable secrets file falls through to env var with warning
- Integration: auth._jwt_secret() uses read_secret()
- Integration: APIKeyMiddleware uses read_secret()
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reload_secrets(secrets_dir: Path):
    """Import secrets module with _SECRETS_DIR patched to *secrets_dir*."""
    import bmt_ai_os.secret_files as mod

    with patch.object(mod, "_SECRETS_DIR", secrets_dir):
        yield mod


# ---------------------------------------------------------------------------
# read_secret — file resolution
# ---------------------------------------------------------------------------


class TestReadSecretFromFile:
    def test_reads_value_from_secrets_file(self, tmp_path, monkeypatch):
        secret_file = tmp_path / "MY_SECRET"
        secret_file.write_text("file-value")

        import bmt_ai_os.secret_files as mod

        monkeypatch.setattr(mod, "_SECRETS_DIR", tmp_path)
        # Env var deliberately absent
        monkeypatch.delenv("MY_SECRET", raising=False)

        assert mod.read_secret("MY_SECRET") == "file-value"

    def test_strips_trailing_newline_from_file(self, tmp_path, monkeypatch):
        secret_file = tmp_path / "MY_SECRET"
        secret_file.write_text("file-value\n")

        import bmt_ai_os.secret_files as mod

        monkeypatch.setattr(mod, "_SECRETS_DIR", tmp_path)
        monkeypatch.delenv("MY_SECRET", raising=False)

        assert mod.read_secret("MY_SECRET") == "file-value"

    def test_no_warning_logged_when_file_present(self, tmp_path, monkeypatch, caplog):
        secret_file = tmp_path / "MY_SECRET"
        secret_file.write_text("from-file")

        import bmt_ai_os.secret_files as mod

        monkeypatch.setattr(mod, "_SECRETS_DIR", tmp_path)
        monkeypatch.delenv("MY_SECRET", raising=False)

        with caplog.at_level(logging.WARNING, logger="bmt_ai_os.secret_files"):
            mod.read_secret("MY_SECRET")

        assert "environment variable" not in caplog.text


# ---------------------------------------------------------------------------
# read_secret — env-var fallback
# ---------------------------------------------------------------------------


class TestReadSecretFromEnv:
    def test_falls_back_to_env_var_when_no_file(self, tmp_path, monkeypatch):
        import bmt_ai_os.secret_files as mod

        monkeypatch.setattr(mod, "_SECRETS_DIR", tmp_path)
        monkeypatch.setenv("MY_SECRET", "env-value")

        assert mod.read_secret("MY_SECRET") == "env-value"

    def test_logs_warning_on_env_fallback(self, tmp_path, monkeypatch, caplog):
        import bmt_ai_os.secret_files as mod

        monkeypatch.setattr(mod, "_SECRETS_DIR", tmp_path)
        monkeypatch.setenv("MY_SECRET", "env-value")

        with caplog.at_level(logging.WARNING, logger="bmt_ai_os.secret_files"):
            mod.read_secret("MY_SECRET")

        assert "MY_SECRET" in caplog.text
        assert "environment variable" in caplog.text

    def test_warning_includes_secrets_path_hint(self, tmp_path, monkeypatch, caplog):
        import bmt_ai_os.secret_files as mod

        monkeypatch.setattr(mod, "_SECRETS_DIR", tmp_path)
        monkeypatch.setenv("MY_SECRET", "env-value")

        with caplog.at_level(logging.WARNING, logger="bmt_ai_os.secret_files"):
            mod.read_secret("MY_SECRET")

        assert "/run/secrets/" in caplog.text

    def test_empty_secrets_file_falls_through_to_env(self, tmp_path, monkeypatch):
        """An empty file is treated as missing; env var should be used."""
        secret_file = tmp_path / "MY_SECRET"
        secret_file.write_text("")

        import bmt_ai_os.secret_files as mod

        monkeypatch.setattr(mod, "_SECRETS_DIR", tmp_path)
        monkeypatch.setenv("MY_SECRET", "env-fallback")

        assert mod.read_secret("MY_SECRET") == "env-fallback"


# ---------------------------------------------------------------------------
# read_secret — default value
# ---------------------------------------------------------------------------


class TestReadSecretDefault:
    def test_returns_none_when_nothing_configured(self, tmp_path, monkeypatch):
        import bmt_ai_os.secret_files as mod

        monkeypatch.setattr(mod, "_SECRETS_DIR", tmp_path)
        monkeypatch.delenv("MY_SECRET", raising=False)

        assert mod.read_secret("MY_SECRET") is None

    def test_returns_caller_default_when_nothing_configured(self, tmp_path, monkeypatch):
        import bmt_ai_os.secret_files as mod

        monkeypatch.setattr(mod, "_SECRETS_DIR", tmp_path)
        monkeypatch.delenv("MY_SECRET", raising=False)

        assert mod.read_secret("MY_SECRET", default="fallback") == "fallback"

    def test_file_takes_priority_over_default(self, tmp_path, monkeypatch):
        secret_file = tmp_path / "MY_SECRET"
        secret_file.write_text("from-file")

        import bmt_ai_os.secret_files as mod

        monkeypatch.setattr(mod, "_SECRETS_DIR", tmp_path)
        monkeypatch.delenv("MY_SECRET", raising=False)

        assert mod.read_secret("MY_SECRET", default="should-not-be-used") == "from-file"

    def test_env_takes_priority_over_default(self, tmp_path, monkeypatch):
        import bmt_ai_os.secret_files as mod

        monkeypatch.setattr(mod, "_SECRETS_DIR", tmp_path)
        monkeypatch.setenv("MY_SECRET", "from-env")

        assert mod.read_secret("MY_SECRET", default="should-not-be-used") == "from-env"


# ---------------------------------------------------------------------------
# read_secret — file takes priority over env var
# ---------------------------------------------------------------------------


class TestReadSecretPriority:
    def test_file_takes_priority_over_env_var(self, tmp_path, monkeypatch):
        secret_file = tmp_path / "MY_SECRET"
        secret_file.write_text("from-file")

        import bmt_ai_os.secret_files as mod

        monkeypatch.setattr(mod, "_SECRETS_DIR", tmp_path)
        monkeypatch.setenv("MY_SECRET", "from-env")

        result = mod.read_secret("MY_SECRET")

        assert result == "from-file"

    def test_no_env_warning_when_file_wins(self, tmp_path, monkeypatch, caplog):
        secret_file = tmp_path / "MY_SECRET"
        secret_file.write_text("from-file")

        import bmt_ai_os.secret_files as mod

        monkeypatch.setattr(mod, "_SECRETS_DIR", tmp_path)
        monkeypatch.setenv("MY_SECRET", "from-env")

        with caplog.at_level(logging.WARNING, logger="bmt_ai_os.secret_files"):
            mod.read_secret("MY_SECRET")

        assert "environment variable" not in caplog.text


# ---------------------------------------------------------------------------
# Integration: auth._jwt_secret()
# ---------------------------------------------------------------------------


class TestAuthUsesReadSecret:
    def test_jwt_secret_from_file(self, tmp_path, monkeypatch):
        """JWT secret can be loaded from /run/secrets/BMT_JWT_SECRET file."""
        secret_file = tmp_path / "BMT_JWT_SECRET"
        secret_file.write_text("FileJwtSecret1X-for-unit-test-32!")

        import bmt_ai_os.controller.auth as auth_mod
        import bmt_ai_os.secret_files as secrets_mod

        monkeypatch.setattr(secrets_mod, "_SECRETS_DIR", tmp_path)
        monkeypatch.delenv("BMT_JWT_SECRET", raising=False)

        assert auth_mod._jwt_secret() == "FileJwtSecret1X-for-unit-test-32!"

    def test_jwt_secret_from_env(self, tmp_path, monkeypatch):
        import bmt_ai_os.controller.auth as auth_mod
        import bmt_ai_os.secret_files as secrets_mod

        monkeypatch.setattr(secrets_mod, "_SECRETS_DIR", tmp_path)
        monkeypatch.setenv("BMT_JWT_SECRET", "EnvJwtSecret1X-unit-test-32chars!")

        assert auth_mod._jwt_secret() == "EnvJwtSecret1X-unit-test-32chars!"

    def test_jwt_secret_raises_when_missing(self, tmp_path, monkeypatch):
        import bmt_ai_os.controller.auth as auth_mod
        import bmt_ai_os.secret_files as secrets_mod

        monkeypatch.setattr(secrets_mod, "_SECRETS_DIR", tmp_path)
        monkeypatch.delenv("BMT_JWT_SECRET", raising=False)

        with pytest.raises(RuntimeError, match="JWT secret not configured"):
            auth_mod._jwt_secret()


# ---------------------------------------------------------------------------
# Integration: APIKeyMiddleware uses read_secret()
# ---------------------------------------------------------------------------


class TestMiddlewareUsesReadSecret:
    def test_api_key_loaded_from_file(self, tmp_path, monkeypatch):
        secret_file = tmp_path / "BMT_API_KEY"
        secret_file.write_text("file-api-key")

        import bmt_ai_os.secret_files as secrets_mod

        monkeypatch.setattr(secrets_mod, "_SECRETS_DIR", tmp_path)
        monkeypatch.delenv("BMT_API_KEY", raising=False)

        from fastapi import FastAPI

        from bmt_ai_os.controller.middleware import APIKeyMiddleware

        app = FastAPI()
        mw = APIKeyMiddleware(app)
        assert mw._api_key == "file-api-key"

    def test_api_key_loaded_from_env(self, tmp_path, monkeypatch):
        import bmt_ai_os.secret_files as secrets_mod

        monkeypatch.setattr(secrets_mod, "_SECRETS_DIR", tmp_path)
        monkeypatch.setenv("BMT_API_KEY", "env-api-key")

        from fastapi import FastAPI

        from bmt_ai_os.controller.middleware import APIKeyMiddleware

        app = FastAPI()
        mw = APIKeyMiddleware(app)
        assert mw._api_key == "env-api-key"

    def test_api_key_none_when_not_configured(self, tmp_path, monkeypatch):
        import bmt_ai_os.secret_files as secrets_mod

        monkeypatch.setattr(secrets_mod, "_SECRETS_DIR", tmp_path)
        monkeypatch.delenv("BMT_API_KEY", raising=False)

        from fastapi import FastAPI

        from bmt_ai_os.controller.middleware import APIKeyMiddleware

        app = FastAPI()
        mw = APIKeyMiddleware(app)
        assert mw._api_key is None
