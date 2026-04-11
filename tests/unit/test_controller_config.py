"""Unit tests for bmt_ai_os.controller.config.

Covers:
- ControllerConfig defaults and __post_init__ service population
- ServiceDef fields
- _apply_env_overrides from BMT_ env vars
- _parse_services from raw list
- load_config: explicit path, default paths, env overrides
"""

from __future__ import annotations

import yaml

from bmt_ai_os.controller.config import (
    ControllerConfig,
    ServiceDef,
    _apply_env_overrides,
    _parse_services,
    load_config,
)

# ---------------------------------------------------------------------------
# ControllerConfig defaults
# ---------------------------------------------------------------------------


class TestControllerConfigDefaults:
    def test_default_api_port(self):
        cfg = ControllerConfig()
        assert cfg.api_port == 8080

    def test_default_api_host(self):
        cfg = ControllerConfig()
        assert cfg.api_host == "0.0.0.0"

    def test_default_health_interval(self):
        cfg = ControllerConfig()
        assert cfg.health_interval == 30

    def test_default_max_restarts(self):
        cfg = ControllerConfig()
        assert cfg.max_restarts == 3

    def test_default_log_level(self):
        cfg = ControllerConfig()
        assert cfg.log_level == "INFO"

    def test_default_services_populated(self):
        cfg = ControllerConfig()
        service_names = [s.name for s in cfg.services]
        assert "ollama" in service_names
        assert "chromadb" in service_names

    def test_default_services_have_correct_ports(self):
        cfg = ControllerConfig()
        ports = {s.name: s.port for s in cfg.services}
        assert ports["ollama"] == 11434
        assert ports["chromadb"] == 8000

    def test_custom_services_override_defaults(self):
        custom = [ServiceDef("custom", "bmt-custom", "http://localhost:9999/health", 9999)]
        cfg = ControllerConfig(services=custom)
        assert len(cfg.services) == 1
        assert cfg.services[0].name == "custom"

    def test_health_timeout_default(self):
        cfg = ControllerConfig()
        assert cfg.health_timeout == 5

    def test_circuit_breaker_defaults(self):
        cfg = ControllerConfig()
        assert cfg.circuit_breaker_threshold == 5
        assert cfg.circuit_breaker_reset == 300


# ---------------------------------------------------------------------------
# ServiceDef
# ---------------------------------------------------------------------------


class TestServiceDef:
    def test_fields(self):
        svc = ServiceDef("myservice", "bmt-myservice", "http://localhost:1234/health", 1234)
        assert svc.name == "myservice"
        assert svc.container_name == "bmt-myservice"
        assert svc.health_url == "http://localhost:1234/health"
        assert svc.port == 1234


# ---------------------------------------------------------------------------
# _apply_env_overrides
# ---------------------------------------------------------------------------


class TestApplyEnvOverrides:
    def test_override_api_port(self, monkeypatch):
        monkeypatch.setenv("BMT_API_PORT", "9090")
        cfg = ControllerConfig()
        _apply_env_overrides(cfg)
        assert cfg.api_port == 9090

    def test_override_api_host(self, monkeypatch):
        monkeypatch.setenv("BMT_API_HOST", "127.0.0.1")
        cfg = ControllerConfig()
        _apply_env_overrides(cfg)
        assert cfg.api_host == "127.0.0.1"

    def test_override_health_interval(self, monkeypatch):
        monkeypatch.setenv("BMT_HEALTH_INTERVAL", "60")
        cfg = ControllerConfig()
        _apply_env_overrides(cfg)
        assert cfg.health_interval == 60

    def test_override_log_level(self, monkeypatch):
        monkeypatch.setenv("BMT_LOG_LEVEL", "DEBUG")
        cfg = ControllerConfig()
        _apply_env_overrides(cfg)
        assert cfg.log_level == "DEBUG"

    def test_override_compose_file(self, monkeypatch):
        monkeypatch.setenv("BMT_COMPOSE_FILE", "/tmp/custom-compose.yml")
        cfg = ControllerConfig()
        _apply_env_overrides(cfg)
        assert cfg.compose_file == "/tmp/custom-compose.yml"

    def test_override_max_restarts(self, monkeypatch):
        monkeypatch.setenv("BMT_MAX_RESTARTS", "5")
        cfg = ControllerConfig()
        _apply_env_overrides(cfg)
        assert cfg.max_restarts == 5

    def test_unset_envs_leave_defaults(self, monkeypatch):
        for key in [
            "BMT_API_PORT",
            "BMT_API_HOST",
            "BMT_HEALTH_INTERVAL",
            "BMT_MAX_RESTARTS",
            "BMT_CIRCUIT_BREAKER_THRESHOLD",
        ]:
            monkeypatch.delenv(key, raising=False)
        cfg = ControllerConfig()
        _apply_env_overrides(cfg)
        assert cfg.api_port == 8080


# ---------------------------------------------------------------------------
# _parse_services
# ---------------------------------------------------------------------------


class TestParseServices:
    def test_parses_list(self):
        raw = [
            {
                "name": "ollama",
                "container_name": "bmt-ollama",
                "health_url": "http://localhost:11434/api/tags",
                "port": 11434,
            },
            {
                "name": "chromadb",
                "container_name": "bmt-chromadb",
                "health_url": "http://localhost:8000/api/v1/heartbeat",
                "port": 8000,
            },
        ]
        services = _parse_services(raw)
        assert len(services) == 2
        assert services[0].name == "ollama"
        assert services[1].port == 8000

    def test_empty_list(self):
        assert _parse_services([]) == []


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_returns_defaults_when_no_file(self, tmp_path):
        cfg = load_config(path=str(tmp_path / "nonexistent.yml"))
        assert cfg.api_port == 8080

    def test_loads_explicit_path(self, tmp_path):
        config_data = {
            "api_port": 9000,
            "api_host": "127.0.0.1",
            "log_level": "DEBUG",
            "health_interval": 10,
        }
        config_file = tmp_path / "controller.yml"
        config_file.write_text(yaml.dump(config_data))
        cfg = load_config(path=str(config_file))
        assert cfg.api_port == 9000
        assert cfg.api_host == "127.0.0.1"
        assert cfg.log_level == "DEBUG"
        assert cfg.health_interval == 10

    def test_loads_services_from_yaml(self, tmp_path):
        config_data = {
            "services": [
                {
                    "name": "custom",
                    "container_name": "bmt-custom",
                    "health_url": "http://localhost:9999/health",
                    "port": 9999,
                }
            ]
        }
        config_file = tmp_path / "controller.yml"
        config_file.write_text(yaml.dump(config_data))
        cfg = load_config(path=str(config_file))
        assert len(cfg.services) == 1
        assert cfg.services[0].name == "custom"

    def test_env_overrides_applied_after_file(self, tmp_path, monkeypatch):
        config_data = {"api_port": 8080}
        config_file = tmp_path / "controller.yml"
        config_file.write_text(yaml.dump(config_data))
        monkeypatch.setenv("BMT_API_PORT", "7777")
        cfg = load_config(path=str(config_file))
        assert cfg.api_port == 7777

    def test_empty_yaml_uses_defaults(self, tmp_path):
        config_file = tmp_path / "controller.yml"
        config_file.write_text("")
        cfg = load_config(path=str(config_file))
        assert cfg.api_port == 8080
        assert len(cfg.services) == 2  # auto-populated

    def test_default_services_when_none_in_yaml(self, tmp_path):
        config_file = tmp_path / "controller.yml"
        config_file.write_text("api_port: 8080\n")
        cfg = load_config(path=str(config_file))
        # Services should be default (ollama + chromadb)
        assert any(s.name == "ollama" for s in cfg.services)
