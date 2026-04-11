"""Extra unit tests for controller.config edge cases and ControllerConfig.

Extends test_controller_config.py with additional coverage.
"""

from __future__ import annotations

import pytest
import yaml

from bmt_ai_os.controller.config import (
    ControllerConfig,
    ServiceDef,
    _apply_env_overrides,
    load_config,
)

# ---------------------------------------------------------------------------
# ControllerConfig field coverage
# ---------------------------------------------------------------------------


class TestControllerConfigFields:
    def test_log_file_default(self):
        cfg = ControllerConfig()
        assert cfg.log_file == "/var/log/bmt-controller.log"

    def test_compose_file_default(self):
        cfg = ControllerConfig()
        assert "/opt/bmt_ai_os/ai-stack" in cfg.compose_file

    def test_health_history_size_default(self):
        cfg = ControllerConfig()
        assert cfg.health_history_size == 10

    def test_services_are_list(self):
        cfg = ControllerConfig()
        assert isinstance(cfg.services, list)

    def test_services_are_service_def_instances(self):
        cfg = ControllerConfig()
        assert all(isinstance(s, ServiceDef) for s in cfg.services)

    def test_at_least_two_default_services(self):
        cfg = ControllerConfig()
        assert len(cfg.services) >= 2

    def test_chromadb_service_has_correct_url(self):
        cfg = ControllerConfig()
        chromadb = next(s for s in cfg.services if s.name == "chromadb")
        assert "8000" in chromadb.health_url

    def test_ollama_service_has_correct_url(self):
        cfg = ControllerConfig()
        ollama = next(s for s in cfg.services if s.name == "ollama")
        assert "11434" in ollama.health_url


# ---------------------------------------------------------------------------
# Environment override coverage
# ---------------------------------------------------------------------------


class TestEnvOverridesCoverage:
    def test_override_circuit_breaker_threshold(self, monkeypatch):
        monkeypatch.setenv("BMT_CIRCUIT_BREAKER_THRESHOLD", "10")
        cfg = ControllerConfig()
        _apply_env_overrides(cfg)
        assert cfg.circuit_breaker_threshold == 10

    def test_override_circuit_breaker_reset(self, monkeypatch):
        monkeypatch.setenv("BMT_CIRCUIT_BREAKER_RESET", "600")
        cfg = ControllerConfig()
        _apply_env_overrides(cfg)
        assert cfg.circuit_breaker_reset == 600

    def test_override_health_timeout(self, monkeypatch):
        monkeypatch.setenv("BMT_HEALTH_TIMEOUT", "15")
        cfg = ControllerConfig()
        _apply_env_overrides(cfg)
        assert cfg.health_timeout == 15

    def test_override_log_file(self, monkeypatch):
        monkeypatch.setenv("BMT_LOG_FILE", "/tmp/test.log")
        cfg = ControllerConfig()
        _apply_env_overrides(cfg)
        assert cfg.log_file == "/tmp/test.log"

    def test_invalid_int_env_raises(self, monkeypatch):
        monkeypatch.setenv("BMT_API_PORT", "not-a-number")
        cfg = ControllerConfig()
        with pytest.raises(ValueError):
            _apply_env_overrides(cfg)


# ---------------------------------------------------------------------------
# load_config edge cases
# ---------------------------------------------------------------------------


class TestLoadConfigEdgeCases:
    def test_all_fields_loadable(self, tmp_path):
        config_data = {
            "api_port": 9000,
            "api_host": "0.0.0.0",
            "log_level": "WARNING",
            "health_interval": 15,
            "max_restarts": 5,
            "circuit_breaker_threshold": 8,
            "circuit_breaker_reset": 120,
            "health_timeout": 3,
        }
        config_file = tmp_path / "controller.yml"
        config_file.write_text(yaml.dump(config_data))
        cfg = load_config(path=str(config_file))
        assert cfg.api_port == 9000
        assert cfg.log_level == "WARNING"
        assert cfg.health_interval == 15
        assert cfg.max_restarts == 5

    def test_multiple_custom_services(self, tmp_path):
        config_data = {
            "services": [
                {
                    "name": "svc1",
                    "container_name": "c1",
                    "health_url": "http://svc1/health",
                    "port": 1001,
                },
                {
                    "name": "svc2",
                    "container_name": "c2",
                    "health_url": "http://svc2/health",
                    "port": 1002,
                },
                {
                    "name": "svc3",
                    "container_name": "c3",
                    "health_url": "http://svc3/health",
                    "port": 1003,
                },
            ]
        }
        config_file = tmp_path / "controller.yml"
        config_file.write_text(yaml.dump(config_data))
        cfg = load_config(path=str(config_file))
        assert len(cfg.services) == 3
        names = [s.name for s in cfg.services]
        assert "svc1" in names
        assert "svc3" in names

    def test_compose_file_overridable(self, tmp_path, monkeypatch):
        # Clear BMT_COMPOSE_FILE so the env-override does not shadow the YAML value
        monkeypatch.delenv("BMT_COMPOSE_FILE", raising=False)
        config_data = {"compose_file": "/custom/docker-compose.yml"}
        config_file = tmp_path / "controller.yml"
        config_file.write_text(yaml.dump(config_data))
        cfg = load_config(path=str(config_file))
        assert cfg.compose_file == "/custom/docker-compose.yml"
