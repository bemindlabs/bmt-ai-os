"""Provider router — tries providers in fallback-chain order with circuit
breaker, per-provider timeout, and request-level metrics.

Usage::

    config  = ProvidersConfig.from_yaml()
    registry = ProviderRegistry()
    # ... register providers ...
    router  = ProviderRouter(registry, config)

    result = await router.chat([ChatMessage(role="user", content="Hi")])
    print(result.provider_name, result.response.content)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from bmt_ai_os.providers.base import ChatMessage, ChatResponse, EmbedResponse
from bmt_ai_os.providers.circuit_breaker import (
    CircuitState,
    ProviderCircuitBreaker,
)
from bmt_ai_os.providers.config import ProvidersConfig
from bmt_ai_os.providers.metrics import ProviderMetrics
from bmt_ai_os.providers.registry import ProviderRegistry

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Data classes for routing results
# ------------------------------------------------------------------ #


@dataclass
class ProviderAttempt:
    """Record of a single attempt against one provider."""

    provider: str
    success: bool
    latency_ms: float
    error: str | None = None


@dataclass
class RoutingResult:
    """Wraps the final response together with routing metadata."""

    response: ChatResponse | EmbedResponse
    provider_name: str
    attempts: list[ProviderAttempt] = field(default_factory=list)


# ------------------------------------------------------------------ #
# Errors
# ------------------------------------------------------------------ #


class AllProvidersFailedError(Exception):
    """Raised when every provider in the fallback chain has failed."""

    def __init__(self, attempts: list[ProviderAttempt]) -> None:
        self.attempts = attempts
        details = "; ".join(f"{a.provider}: {a.error}" for a in attempts)
        super().__init__(f"All providers failed — {details}")


# ------------------------------------------------------------------ #
# Router
# ------------------------------------------------------------------ #


class ProviderRouter:
    """Route LLM requests through the fallback chain with circuit breaking."""

    def __init__(
        self,
        registry: ProviderRegistry,
        config: ProvidersConfig,
    ) -> None:
        self._registry = registry
        self._config = config
        self._metrics = ProviderMetrics()
        self._breakers: dict[str, ProviderCircuitBreaker] = {}

    # ------------------------------------------------------------------ #
    # Accessors
    # ------------------------------------------------------------------ #

    @property
    def metrics(self) -> ProviderMetrics:
        return self._metrics

    def get_circuit_breaker(self, provider: str) -> ProviderCircuitBreaker:
        if provider not in self._breakers:
            cb_cfg = self._config.circuit_breaker
            self._breakers[provider] = ProviderCircuitBreaker(
                failure_threshold=cb_cfg.failure_threshold,
                cooldown_seconds=cb_cfg.cooldown_seconds,
                half_open_max_requests=cb_cfg.half_open_max_requests,
            )
        return self._breakers[provider]

    # ------------------------------------------------------------------ #
    # Public routing methods
    # ------------------------------------------------------------------ #

    async def chat(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
        **kwargs: Any,
    ) -> RoutingResult:
        """Send a chat request through the fallback chain."""

        async def _call(provider_name: str) -> ChatResponse:
            provider = self._registry.get(provider_name)
            return await provider.chat(messages, model=model, **kwargs)

        return await self._route("chat", _call)

    async def embed(
        self,
        texts: list[str],
        model: str | None = None,
        **kwargs: Any,
    ) -> RoutingResult:
        """Send an embed request through the fallback chain."""

        async def _call(provider_name: str) -> EmbedResponse:
            provider = self._registry.get(provider_name)
            return await provider.embed(texts, model=model, **kwargs)

        return await self._route("embed", _call)

    # ------------------------------------------------------------------ #
    # Internal routing engine
    # ------------------------------------------------------------------ #

    async def _route(
        self,
        method: str,
        call_fn: Any,
    ) -> RoutingResult:
        """Try each provider in the fallback chain until one succeeds."""

        attempts: list[ProviderAttempt] = []
        registered = set(self._registry.list())

        for provider_name in self._config.fallback_chain:
            # Skip providers that are not registered.
            if provider_name not in registered:
                continue

            # Skip disabled providers.
            settings = self._config.get_provider_settings(provider_name)
            if settings is None or not settings.enabled:
                continue

            # Skip circuit-broken providers.
            breaker = self.get_circuit_breaker(provider_name)
            if not breaker.is_available():
                logger.debug(
                    "Skipping %s — circuit breaker %s",
                    provider_name,
                    breaker.state.value,
                )
                continue

            # Track half-open probe.
            if breaker.state is CircuitState.HALF_OPEN:
                await breaker.record_half_open_attempt()

            timeout = float(settings.timeout)
            t0 = time.monotonic()

            try:
                response = await asyncio.wait_for(
                    call_fn(provider_name),
                    timeout=timeout,
                )
                latency_ms = (time.monotonic() - t0) * 1000.0

                await breaker.record_success()
                self._metrics.record_success(provider_name, latency_ms)

                attempt = ProviderAttempt(
                    provider=provider_name,
                    success=True,
                    latency_ms=round(latency_ms, 2),
                )
                attempts.append(attempt)

                logger.info(
                    "Request served by %s (%s) in %.1f ms",
                    provider_name,
                    method,
                    latency_ms,
                )

                return RoutingResult(
                    response=response,
                    provider_name=provider_name,
                    attempts=attempts,
                )

            except Exception as exc:
                latency_ms = (time.monotonic() - t0) * 1000.0
                error_msg = f"{type(exc).__name__}: {exc}"

                await breaker.record_failure()
                self._metrics.record_failure(provider_name, latency_ms)

                attempt = ProviderAttempt(
                    provider=provider_name,
                    success=False,
                    latency_ms=round(latency_ms, 2),
                    error=error_msg,
                )
                attempts.append(attempt)

                logger.warning(
                    "Provider %s failed (%s): %s (%.1f ms)",
                    provider_name,
                    method,
                    error_msg,
                    latency_ms,
                )

        raise AllProvidersFailedError(attempts)
