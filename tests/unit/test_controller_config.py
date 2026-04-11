"""Unit tests for bmt_ai_os.controller.config."""

from __future__ import annotations

import os
from unittest.mock import patch

from bmt_ai_os.controller.config import (
    ControllerConfig,
    ServiceDef,
    _apply_env_overrides,
    _parse_services,
    load_config,
)


class TestControllerConfigDefaults:
    def test_default_fields(self):
        cfg = ControllerConfig()
        assert cfg.api_port == 8080
        assert cfg.api_host == "0.0.0.0"
        assert cfg.log_level == "INFO"
        assert cfg.health_interval == 30
        assert cfg.max_restarts == 3

    def test_default_services_populated(self):
        cfg = ControllerConfig()
        names = [s.name for s in cfg.services]
        assert "ollama" in names
        assert "chromadb" in names

    def test_default_services_have_valid_urls(self):
        cfg = ControllerConfig()
        for svc in cfg.services:
            assert svc.health_url.startswith("http")
            assert svc.port > 0

    def test_custom_services_not_overridden(self):
        custom = [
            ServiceDef(
                name="custom",
                container_name="bmt-custom",
                health_url="http://localhost:9999/health",
                port=9999,
            )
        ]
        cfg = ControllerConfig(services=custom)
        assert len(cfg.services) == 1
        assert cfg.services[0].name == "custom"


class TestServiceDef:
    def test_construction(self):
        svc = ServiceDef(
            name="ollama",
            container_name="bmt-ollama",
            health_url="http://localhost:11434/api/tags",
            port=11434,
        )
        assert svc.name == "ollama"
        assert svc.port == 11434


class TestApplyEnvOverrides:
    def test_overrides_api_port(self):
        cfg = ControllerConfig()
        with patch.dict(os.environ, {"BMT_API_PORT": "9090"}):
            _apply_env_overrides(cfg)
        assert cfg.api_port == 9090

    def test_overrides_log_level(self):
        cfg = ControllerConfig()
        with patch.dict(os.environ, {"BMT_LOG_LEVEL": "DEBUG"}):
            _apply_env_overrides(cfg)
        assert cfg.log_level == "DEBUG"

    def test_overrides_health_interval(self):
        cfg = ControllerConfig()
        with patch.dict(os.environ, {"BMT_HEALTH_INTERVAL": "60"}):
            _apply_env_overrides(cfg)
        assert cfg.health_interval == 60

    def test_no_override_when_env_unset(self):
        cfg = ControllerConfig()
        env = {k: v for k, v in os.environ.items() if not k.startswith("BMT_")}
        with patch.dict(os.environ, env, clear=True):
            _apply_env_overrides(cfg)
        assert cfg.api_port == 8080


class TestParseServices:
    def test_parses_list(self):
        raw = [
            {
                "name": "svc1",
                "container_name": "bmt-svc1",
                "health_url": "http://localhost:1234/health",
                "port": 1234,
            }
        ]
        result = _parse_services(raw)
        assert len(result) == 1
        assert result[0].name == "svc1"
        assert result[0].port == 1234


class TestLoadConfig:
    def test_returns_default_when_no_file(self):
        with patch("bmt_ai_os.controller.config._DEFAULT_CONFIG_PATHS", []):
            cfg = load_config()
        assert isinstance(cfg, ControllerConfig)
        assert cfg.api_port == 8080

    def test_loads_from_yaml(self, tmp_path):
        yml = tmp_path / "controller.yml"
        yml.write_text("api_port: 9000\nlog_level: DEBUG\n")
        cfg = load_config(str(yml))
        assert cfg.api_port == 9000
        assert cfg.log_level == "DEBUG"

    def test_env_overrides_yaml(self, tmp_path):
        yml = tmp_path / "controller.yml"
        yml.write_text("api_port: 9000\n")
        with patch.dict(os.environ, {"BMT_API_PORT": "7777"}):
            cfg = load_config(str(yml))
        assert cfg.api_port == 7777

    def test_loads_services_from_yaml(self, tmp_path):
        yml = tmp_path / "controller.yml"
        yml.write_text(
            "services:\n"
            "  - name: myservice\n"
            "    container_name: bmt-myservice\n"
            "    health_url: http://localhost:5000/health\n"
            "    port: 5000\n"
        )
        cfg = load_config(str(yml))
        assert len(cfg.services) == 1
        assert cfg.services[0].name == "myservice"
