"""Provider configuration — loaded from providers.yml."""

from __future__ import annotations

import pathlib
from dataclasses import dataclass, field
from typing import Any

import yaml

_DEFAULT_CONFIG_PATH = pathlib.Path(__file__).parent / "providers.yml"

# Providers that run on the local device vs. remote cloud APIs.
LOCAL_PROVIDERS = {"ollama", "vllm", "llama-cpp"}
CLOUD_PROVIDERS = {"openai", "anthropic"}

DEFAULT_LOCAL_TIMEOUT = 30.0  # seconds
DEFAULT_CLOUD_TIMEOUT = 15.0  # seconds


@dataclass
class ProviderSettings:
    """Per-provider configuration."""

    enabled: bool = True
    timeout: float | None = None  # None -> use default for local/cloud
    base_url: str | None = None
    api_key: str | None = None
    default_model: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def effective_timeout(self, provider_name: str) -> float:
        """Return configured timeout, or the default for local/cloud."""
        if self.timeout is not None:
            return self.timeout
        if provider_name in CLOUD_PROVIDERS:
            return DEFAULT_CLOUD_TIMEOUT
        return DEFAULT_LOCAL_TIMEOUT


@dataclass
class CircuitBreakerSettings:
    """Circuit-breaker knobs shared across providers."""

    failure_threshold: int = 3
    cooldown_seconds: float = 60.0
    half_open_max_requests: int = 1


@dataclass
class ProvidersConfig:
    """Top-level configuration for the provider layer."""

    fallback_chain: list[str] = field(default_factory=lambda: [
        "ollama", "vllm", "llama-cpp", "openai", "anthropic",
    ])
    providers: dict[str, ProviderSettings] = field(default_factory=dict)
    circuit_breaker: CircuitBreakerSettings = field(
        default_factory=CircuitBreakerSettings,
    )

    # ------------------------------------------------------------------ #
    # Factory
    # ------------------------------------------------------------------ #
    @classmethod
    def from_yaml(cls, path: pathlib.Path | str | None = None) -> "ProvidersConfig":
        """Load config from a YAML file.  Falls back to built-in defaults."""
        path = pathlib.Path(path) if path else _DEFAULT_CONFIG_PATH
        if not path.exists():
            return cls()

        with open(path) as fh:
            raw: dict[str, Any] = yaml.safe_load(fh) or {}

        fallback_chain = raw.get("fallback_chain", cls.__dataclass_fields__[
            "fallback_chain"
        ].default_factory())

        providers: dict[str, ProviderSettings] = {}
        for name, cfg in raw.get("providers", {}).items():
            if cfg is None:
                cfg = {}
            providers[name] = ProviderSettings(
                enabled=cfg.get("enabled", True),
                timeout=cfg.get("timeout"),
                base_url=cfg.get("base_url"),
                api_key=cfg.get("api_key"),
                default_model=cfg.get("default_model"),
                extra={
                    k: v
                    for k, v in cfg.items()
                    if k not in {
                        "enabled", "timeout", "base_url", "api_key", "default_model",
                    }
                },
            )

        cb_raw = raw.get("circuit_breaker", {}) or {}
        cb = CircuitBreakerSettings(
            failure_threshold=cb_raw.get("failure_threshold", 3),
            cooldown_seconds=cb_raw.get("cooldown_seconds", 60.0),
            half_open_max_requests=cb_raw.get("half_open_max_requests", 1),
        )

        return cls(
            fallback_chain=fallback_chain,
            providers=providers,
            circuit_breaker=cb,
        )

    def settings_for(self, provider_name: str) -> ProviderSettings:
        """Return settings for a provider, with defaults if not configured."""
        return self.providers.get(provider_name, ProviderSettings())
