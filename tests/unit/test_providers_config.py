"""Unit tests for bmt_ai_os.providers.config.

Covers:
- ProviderSettings.from_dict
- ProvidersConfig.from_dict, enabled_providers, get_provider_settings
- load_config: path override, env var path, default fallback
- resolve_api_key: explicit > env > secrets file
- get_provider_config helper
"""

from __future__ import annotations

import yaml

from bmt_ai_os.providers.config import (
    CircuitBreakerSettings,
    ProvidersConfig,
    ProviderSettings,
    get_provider_config,
    load_config,
    resolve_api_key,
)

# ---------------------------------------------------------------------------
# ProviderSettings
# ---------------------------------------------------------------------------


class TestProviderSettings:
    def test_from_dict_full(self):
        data = {
            "enabled": True,
            "base_url": "https://api.example.com",
            "api_key": "sk-test",
            "default_model": "gpt-4o",
            "timeout": 60,
        }
        s = ProviderSettings.from_dict(data)
        assert s.enabled is True
        assert s.base_url == "https://api.example.com"
        assert s.api_key == "sk-test"
        assert s.default_model == "gpt-4o"
        assert s.timeout == 60

    def test_from_dict_defaults(self):
        s = ProviderSettings.from_dict({})
        assert s.enabled is False
        assert s.base_url == ""
        assert s.api_key == ""
        assert s.default_model == ""
        assert s.timeout == 30

    def test_from_dict_partial(self):
        s = ProviderSettings.from_dict({"enabled": True, "timeout": 90})
        assert s.enabled is True
        assert s.timeout == 90
        assert s.api_key == ""


# ---------------------------------------------------------------------------
# ProvidersConfig
# ---------------------------------------------------------------------------


class TestProvidersConfig:
    def test_from_dict_defaults(self):
        cfg = ProvidersConfig.from_dict({})
        assert cfg.active_provider == "ollama"
        assert cfg.fallback_chain == ["ollama"]
        assert cfg.providers == {}

    def test_from_dict_with_providers(self):
        data = {
            "active_provider": "openai",
            "fallback_chain": ["openai", "ollama"],
            "providers": {
                "openai": {"enabled": True, "api_key": "sk-abc", "default_model": "gpt-4o"},
                "ollama": {"enabled": True, "base_url": "http://localhost:11434"},
            },
        }
        cfg = ProvidersConfig.from_dict(data)
        assert cfg.active_provider == "openai"
        assert cfg.fallback_chain == ["openai", "ollama"]
        assert "openai" in cfg.providers
        assert cfg.providers["openai"].enabled is True
        assert cfg.providers["openai"].api_key == "sk-abc"
        assert cfg.providers["ollama"].base_url == "http://localhost:11434"

    def test_enabled_providers_filters_disabled(self):
        cfg = ProvidersConfig.from_dict(
            {
                "providers": {
                    "ollama": {"enabled": True},
                    "openai": {"enabled": False},
                    "groq": {"enabled": True},
                }
            }
        )
        enabled = cfg.enabled_providers()
        assert "ollama" in enabled
        assert "groq" in enabled
        assert "openai" not in enabled

    def test_get_provider_settings_returns_none_for_unknown(self):
        cfg = ProvidersConfig()
        assert cfg.get_provider_settings("ghost") is None

    def test_get_provider_settings_returns_settings(self):
        cfg = ProvidersConfig.from_dict(
            {"providers": {"ollama": {"enabled": True, "base_url": "http://localhost:11434"}}}
        )
        s = cfg.get_provider_settings("ollama")
        assert s is not None
        assert s.base_url == "http://localhost:11434"

    def test_default_circuit_breaker_settings(self):
        cfg = ProvidersConfig()
        assert isinstance(cfg.circuit_breaker, CircuitBreakerSettings)
        assert cfg.circuit_breaker.failure_threshold == 3
        assert cfg.circuit_breaker.cooldown_seconds == 60.0


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_returns_defaults_when_no_file(self, tmp_path):
        cfg = load_config(path=str(tmp_path / "nonexistent.yml"))
        assert cfg.active_provider == "ollama"

    def test_loads_from_explicit_path(self, tmp_path):
        config_file = tmp_path / "providers.yml"
        data = {
            "active_provider": "groq",
            "fallback_chain": ["groq", "ollama"],
            "providers": {
                "groq": {"enabled": True, "api_key": "gsk-test"},
            },
        }
        config_file.write_text(yaml.dump(data))
        cfg = load_config(path=str(config_file))
        assert cfg.active_provider == "groq"
        assert cfg.providers["groq"].api_key == "gsk-test"

    def test_loads_from_env_var_path(self, tmp_path, monkeypatch):
        config_file = tmp_path / "env_providers.yml"
        data = {"active_provider": "anthropic"}
        config_file.write_text(yaml.dump(data))
        monkeypatch.setenv("BMT_PROVIDERS_CONFIG", str(config_file))
        cfg = load_config()
        assert cfg.active_provider == "anthropic"

    def test_empty_yaml_returns_defaults(self, tmp_path):
        config_file = tmp_path / "empty.yml"
        config_file.write_text("")
        cfg = load_config(path=str(config_file))
        assert cfg.active_provider == "ollama"

    def test_partial_yaml(self, tmp_path):
        config_file = tmp_path / "partial.yml"
        config_file.write_text("active_provider: mistral\n")
        cfg = load_config(path=str(config_file))
        assert cfg.active_provider == "mistral"
        # fallback_chain should be default
        assert cfg.fallback_chain == ["ollama"]

    def test_env_var_takes_priority_over_default_paths(self, tmp_path, monkeypatch):
        """BMT_PROVIDERS_CONFIG should take priority over bundled providers.yml."""
        config_file = tmp_path / "override.yml"
        config_file.write_text("active_provider: vllm\n")
        monkeypatch.setenv("BMT_PROVIDERS_CONFIG", str(config_file))
        cfg = load_config()
        assert cfg.active_provider == "vllm"


# ---------------------------------------------------------------------------
# resolve_api_key
# ---------------------------------------------------------------------------


class TestResolveApiKey:
    def test_explicit_value_wins(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "env-value")
        result = resolve_api_key(key_name="MY_KEY", env_var="MY_KEY", explicit="direct-value")
        assert result == "direct-value"

    def test_env_var_used_when_no_explicit(self, monkeypatch):
        monkeypatch.setenv("MY_API_KEY", "from-env")
        result = resolve_api_key(key_name="MY_API_KEY", env_var="MY_API_KEY")
        assert result == "from-env"

    def test_key_name_used_as_env_when_no_env_var(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "key-from-name")
        result = resolve_api_key(key_name="OPENAI_API_KEY")
        assert result == "key-from-name"

    def test_returns_none_when_nothing_set(self, monkeypatch):
        monkeypatch.delenv("TOTALLY_MISSING_KEY_XYZ", raising=False)
        result = resolve_api_key(key_name="TOTALLY_MISSING_KEY_XYZ")
        assert result is None

    def test_secrets_file_read(self, tmp_path, monkeypatch):
        # Patch _SECRETS_DIR to point at tmp_path
        import bmt_ai_os.providers.config as cfg_module

        monkeypatch.setattr(cfg_module, "_SECRETS_DIR", tmp_path)
        monkeypatch.delenv("SECRET_KEY_TEST", raising=False)
        secret_file = tmp_path / "SECRET_KEY_TEST"
        secret_file.write_text("  file-secret  ")
        result = resolve_api_key(key_name="SECRET_KEY_TEST")
        assert result == "file-secret"

    def test_empty_explicit_falls_through_to_env(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "env-value")
        # explicit="" is falsy so env should be used
        result = resolve_api_key(key_name="MY_KEY", env_var="MY_KEY", explicit="")
        assert result == "env-value"


# ---------------------------------------------------------------------------
# get_provider_config helper
# ---------------------------------------------------------------------------


class TestGetProviderConfig:
    def test_returns_empty_for_nonexistent_provider(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BMT_PROVIDERS_CONFIG", str(tmp_path / "nonexistent.yml"))
        result = get_provider_config("ghost")
        assert result == {}

    def test_returns_section_for_existing_provider(self, tmp_path, monkeypatch):
        config_file = tmp_path / "providers.yml"
        data = {
            "providers": {
                "ollama": {"enabled": True, "base_url": "http://localhost:11434"},
            }
        }
        config_file.write_text(yaml.dump(data))
        monkeypatch.setenv("BMT_PROVIDERS_CONFIG", str(config_file))
        result = get_provider_config("ollama")
        assert result["enabled"] is True
        assert result["base_url"] == "http://localhost:11434"
