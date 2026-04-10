"""Configuration management for BMT AI OS Controller.

Loads settings from /etc/bmt_ai_os/controller.yml, then overrides
with environment variables prefixed BMT_.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_COMPOSE_FILE = "/opt/bmt_ai_os/ai-stack/docker-compose.yml"
_DEFAULT_CONFIG_PATHS = [
    Path("/etc/bmt_ai_os/controller.yml"),
    Path("controller.yml"),
]


@dataclass
class ServiceDef:
    """Definition of a managed AI-stack service."""

    name: str
    container_name: str
    health_url: str
    port: int


@dataclass
class ControllerConfig:
    """All controller settings with sensible defaults."""

    compose_file: str = _DEFAULT_COMPOSE_FILE
    health_interval: int = 30
    max_restarts: int = 3
    circuit_breaker_threshold: int = 5
    circuit_breaker_reset: int = 300
    api_port: int = 8080
    api_host: str = "0.0.0.0"
    log_level: str = "INFO"
    log_file: str = "/var/log/bmt-controller.log"
    health_timeout: int = 5
    health_history_size: int = 10
    services: list[ServiceDef] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.services:
            self.services = [
                ServiceDef(
                    name="ollama",
                    container_name="bmt-ollama",
                    health_url="http://localhost:11434/api/tags",
                    port=11434,
                ),
                ServiceDef(
                    name="chromadb",
                    container_name="bmt-chromadb",
                    health_url="http://localhost:8000/api/v1/heartbeat",
                    port=8000,
                ),
            ]


def _apply_env_overrides(cfg: ControllerConfig) -> None:
    """Override config fields from BMT_ environment variables."""
    env_map = {
        "BMT_COMPOSE_FILE": ("compose_file", str),
        "BMT_HEALTH_INTERVAL": ("health_interval", int),
        "BMT_MAX_RESTARTS": ("max_restarts", int),
        "BMT_CIRCUIT_BREAKER_THRESHOLD": ("circuit_breaker_threshold", int),
        "BMT_CIRCUIT_BREAKER_RESET": ("circuit_breaker_reset", int),
        "BMT_API_PORT": ("api_port", int),
        "BMT_API_HOST": ("api_host", str),
        "BMT_LOG_LEVEL": ("log_level", str),
        "BMT_LOG_FILE": ("log_file", str),
        "BMT_HEALTH_TIMEOUT": ("health_timeout", int),
    }
    for env_key, (attr, typ) in env_map.items():
        val = os.environ.get(env_key)
        if val is not None:
            setattr(cfg, attr, typ(val))


def _parse_services(raw: list[dict[str, Any]]) -> list[ServiceDef]:
    return [
        ServiceDef(
            name=s["name"],
            container_name=s["container_name"],
            health_url=s["health_url"],
            port=s["port"],
        )
        for s in raw
    ]


def load_config(path: str | None = None) -> ControllerConfig:
    """Load configuration from YAML file and environment overrides."""
    data: dict[str, Any] = {}

    if path:
        candidates = [Path(path)]
    else:
        candidates = _DEFAULT_CONFIG_PATHS

    for p in candidates:
        if p.is_file():
            with open(p) as f:
                data = yaml.safe_load(f) or {}
            break

    services_raw = data.pop("services", None)
    cfg = ControllerConfig(**{k: v for k, v in data.items() if hasattr(ControllerConfig, k)})
    if services_raw:
        cfg.services = _parse_services(services_raw)

    _apply_env_overrides(cfg)
    return cfg
