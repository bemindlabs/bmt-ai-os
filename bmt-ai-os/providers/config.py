"""BMT AI OS — Provider configuration loader.

Configuration priority (highest wins):
  1. Explicit kwargs passed to the provider constructor
  2. Environment variables (e.g. OPENAI_API_KEY)
  3. Secrets file (/etc/bmt-ai-os/secrets/<KEY_NAME>)
  4. providers.yml defaults
"""

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
_SECRETS_DIR = Path("/etc/bmt-ai-os/secrets")


# ---------------------------------------------------------------------------
# Dataclass-based config (used by router, registry, tests)
# ---------------------------------------------------------------------------


@dataclass
class CircuitBreakerSettings:
    """Circuit breaker settings for provider failover."""

    failure_threshold: int = 3
    cooldown_seconds: float = 60.0
    half_open_max_requests: int = 1


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
    circuit_breaker: CircuitBreakerSettings = field(default_factory=CircuitBreakerSettings)

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


# ---------------------------------------------------------------------------
# File discovery and loading
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Dict-based helpers (used by individual providers)
# ---------------------------------------------------------------------------


def load_providers_config() -> dict[str, Any]:
    """Load providers.yml and return the full config dict."""
    config_path = _find_config_file()
    if config_path and config_path.exists():
        with open(config_path) as fh:
            return yaml.safe_load(fh) or {}
    return {}


def get_provider_config(provider_name: str) -> dict[str, Any]:
    """Return the config section for *provider_name*."""
    cfg = load_providers_config()
    return cfg.get("providers", {}).get(provider_name, {})


def resolve_api_key(
    *,
    key_name: str,
    env_var: str | None = None,
    explicit: str | None = None,
) -> str | None:
    """Resolve an API key using the priority chain.

    1. *explicit* value (passed directly)
    2. Environment variable (*env_var* or *key_name*)
    3. Secrets file at ``/etc/bmt-ai-os/secrets/<key_name>``
    4. providers.yml ``api_key`` field
    """
    if explicit:
        return explicit

    env_name = env_var or key_name
    value = os.environ.get(env_name)
    if value:
        return value

    secrets_file = _SECRETS_DIR / key_name
    if secrets_file.exists():
        return secrets_file.read_text().strip()

    return None
