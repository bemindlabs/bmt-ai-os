"""Provider configuration — load settings from YAML."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Default search paths (highest priority first).
_CONFIG_SEARCH_PATHS = [
    Path("/etc/bmt-ai-os/providers.yml"),
    Path(__file__).resolve().parent / "providers.yml",
]

_ENV_CONFIG_PATH = "BMT_PROVIDERS_CONFIG"


@dataclass
class ProviderSettings:
    """Settings for a single LLM provider."""

    enabled: bool = False
    base_url: str = ""
    api_key: str = ""
    default_model: str = ""
    timeout: int = 30

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProviderSettings:
        return cls(
            enabled=data.get("enabled", False),
            base_url=data.get("base_url", ""),
            api_key=data.get("api_key", ""),
            default_model=data.get("default_model", ""),
            timeout=data.get("timeout", 30),
        )


@dataclass
class ProvidersConfig:
    """Top-level configuration for the provider layer."""

    active_provider: str = "ollama"
    fallback_chain: list[str] = field(default_factory=lambda: ["ollama"])
    providers: dict[str, ProviderSettings] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProvidersConfig:
        providers: dict[str, ProviderSettings] = {}
        for name, settings in data.get("providers", {}).items():
            providers[name] = ProviderSettings.from_dict(settings)
        return cls(
            active_provider=data.get("active_provider", "ollama"),
            fallback_chain=data.get("fallback_chain", ["ollama"]),
            providers=providers,
        )

    def get_provider_settings(self, name: str) -> ProviderSettings | None:
        """Return settings for *name*, or ``None`` if not configured."""
        return self.providers.get(name)

    def enabled_providers(self) -> list[str]:
        """Return names of providers that have ``enabled: true``."""
        return [n for n, s in self.providers.items() if s.enabled]


def _find_config_file() -> Path | None:
    """Locate the first existing config file."""
    env_path = os.environ.get(_ENV_CONFIG_PATH)
    if env_path:
        p = Path(env_path)
        if p.is_file():
            return p

    for path in _CONFIG_SEARCH_PATHS:
        if path.is_file():
            return path

    return None


def load_config(path: str | Path | None = None) -> ProvidersConfig:
    """Load provider configuration from *path* or auto-discover.

    Returns a default :class:`ProvidersConfig` if no file is found.
    """
    if path is not None:
        config_path = Path(path)
    else:
        config_path = _find_config_file()

    if config_path is None or not config_path.is_file():
        return ProvidersConfig()

    with open(config_path, "r") as fh:
        data = yaml.safe_load(fh) or {}

    return ProvidersConfig.from_dict(data)
