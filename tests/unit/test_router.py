"""Unit tests for the provider router, circuit breaker, and metrics."""

from __future__ import annotations

import asyncio

import pytest
from bmt_ai_os.providers.base import (
    ChatMessage,
    ChatResponse,
    EmbedResponse,
    LLMProvider,
)
from bmt_ai_os.providers.circuit_breaker import CircuitState, ProviderCircuitBreaker
from bmt_ai_os.providers.config import ProvidersConfig, ProviderSettings
from bmt_ai_os.providers.metrics import ProviderMetrics
from bmt_ai_os.providers.registry import ProviderRegistry
from bmt_ai_os.providers.router import (
    AllProvidersFailedError,
    ProviderRouter,
)

# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #


class FakeProvider(LLMProvider):
    """A provider whose behaviour can be controlled per-test."""

    def __init__(
        self,
        name: str = "fake",
        *,
        chat_response: ChatResponse | None = None,
        embed_response: EmbedResponse | None = None,
        should_fail: bool = False,
        fail_error: Exception | None = None,
        latency: float = 0.0,
    ) -> None:
        self.name = name
        self._chat_response = chat_response or ChatResponse(
            content="hello",
            model="m",
            provider=name,
        )
        self._embed_response = embed_response or EmbedResponse(
            embeddings=[[0.1, 0.2]],
            model="m",
            provider=name,
        )
        self._should_fail = should_fail
        self._fail_error = fail_error or RuntimeError(f"{name} down")
        self._latency = latency
        self.call_count = 0

    async def chat(self, messages, model=None, **kwargs):
        self.call_count += 1
        if self._latency:
            await asyncio.sleep(self._latency)
        if self._should_fail:
            raise self._fail_error
        return self._chat_response

    async def embed(self, texts, model=None, **kwargs):
        self.call_count += 1
        if self._latency:
            await asyncio.sleep(self._latency)
        if self._should_fail:
            raise self._fail_error
        return self._embed_response

    async def list_models(self):
        return ["m"]

    async def health_check(self):
        return not self._should_fail


def _make_config(
    chain: list[str] | None = None,
    provider_overrides: dict[str, dict] | None = None,
    failure_threshold: int = 3,
    cooldown_seconds: float = 60.0,
) -> ProvidersConfig:
    from bmt_ai_os.providers.config import CircuitBreakerSettings

    chain = chain or ["a", "b", "c"]
    providers = {}
    for name in chain:
        overrides = (provider_overrides or {}).get(name, {})
        providers[name] = ProviderSettings(
            enabled=overrides.get("enabled", True),
            timeout=overrides.get("timeout", 5.0),
        )
    return ProvidersConfig(
        fallback_chain=chain,
        providers=providers,
        circuit_breaker=CircuitBreakerSettings(
            failure_threshold=failure_threshold,
            cooldown_seconds=cooldown_seconds,
        ),
    )


def _make_router(
    providers: dict[str, FakeProvider],
    config: ProvidersConfig | None = None,
) -> ProviderRouter:
    registry = ProviderRegistry()
    for name, prov in providers.items():
        registry.register(name, prov)
    config = config or _make_config(list(providers.keys()))
    return ProviderRouter(registry, config)


# ------------------------------------------------------------------ #
# Fallback chain ordering
# ------------------------------------------------------------------ #


class TestFallbackChain:
    @pytest.mark.asyncio
    async def test_uses_first_healthy_provider(self):
        providers = {
            "a": FakeProvider("a"),
            "b": FakeProvider("b"),
        }
        router = _make_router(providers)
        result = await router.chat([ChatMessage(role="user", content="hi")])

        assert result.provider_name == "a"
        assert providers["a"].call_count == 1
        assert providers["b"].call_count == 0

    @pytest.mark.asyncio
    async def test_falls_back_to_second_on_failure(self):
        providers = {
            "a": FakeProvider("a", should_fail=True),
            "b": FakeProvider("b"),
        }
        router = _make_router(providers)
        result = await router.chat([ChatMessage(role="user", content="hi")])

        assert result.provider_name == "b"
        assert len(result.attempts) == 2
        assert result.attempts[0].provider == "a"
        assert result.attempts[0].success is False
        assert result.attempts[1].provider == "b"
        assert result.attempts[1].success is True

    @pytest.mark.asyncio
    async def test_skips_disabled_provider(self):
        config = _make_config(
            ["a", "b"],
            provider_overrides={"a": {"enabled": False}},
        )
        providers = {
            "a": FakeProvider("a"),
            "b": FakeProvider("b"),
        }
        router = _make_router(providers, config)
        result = await router.chat([ChatMessage(role="user", content="hi")])

        assert result.provider_name == "b"
        assert providers["a"].call_count == 0

    @pytest.mark.asyncio
    async def test_embed_fallback(self):
        providers = {
            "a": FakeProvider("a", should_fail=True),
            "b": FakeProvider("b"),
        }
        router = _make_router(providers)
        result = await router.embed(["text"])

        assert result.provider_name == "b"
        assert isinstance(result.response, EmbedResponse)


# ------------------------------------------------------------------ #
# Circuit breaker state transitions
# ------------------------------------------------------------------ #


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_starts_closed(self):
        cb = ProviderCircuitBreaker(failure_threshold=3)
        assert cb.state is CircuitState.CLOSED
        assert cb.is_available()

    @pytest.mark.asyncio
    async def test_opens_after_threshold(self):
        cb = ProviderCircuitBreaker(failure_threshold=2, cooldown_seconds=100)
        await cb.record_failure()
        assert cb.state is CircuitState.CLOSED
        await cb.record_failure()
        assert cb.state is CircuitState.OPEN
        assert not cb.is_available()

    @pytest.mark.asyncio
    async def test_transitions_to_half_open_after_cooldown(self):
        cb = ProviderCircuitBreaker(failure_threshold=1, cooldown_seconds=0.0)
        await cb.record_failure()
        # With cooldown_seconds=0, accessing .state immediately transitions
        # OPEN -> HALF_OPEN because the cooldown has already elapsed.
        assert cb.state is CircuitState.HALF_OPEN
        assert cb.is_available()

    @pytest.mark.asyncio
    async def test_half_open_success_closes(self):
        cb = ProviderCircuitBreaker(failure_threshold=1, cooldown_seconds=0.0)
        await cb.record_failure()
        _ = cb.state  # trigger HALF_OPEN
        await cb.record_success()
        assert cb.state is CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens(self):
        cb = ProviderCircuitBreaker(
            failure_threshold=1,
            cooldown_seconds=300.0,
        )
        await cb.record_failure()
        assert cb._state is CircuitState.OPEN
        # Manually transition to HALF_OPEN (simulating cooldown expiry).
        cb._state = CircuitState.HALF_OPEN
        cb._half_open_attempts = 0
        await cb.record_failure()
        assert cb._state is CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_reset(self):
        cb = ProviderCircuitBreaker(failure_threshold=1)
        await cb.record_failure()
        assert cb.state is CircuitState.OPEN
        cb.reset()
        assert cb.state is CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_router_skips_open_circuit(self):
        """After enough failures the router should skip the broken provider."""
        config = _make_config(
            ["a", "b"],
            failure_threshold=1,
            cooldown_seconds=300,
        )
        providers = {
            "a": FakeProvider("a", should_fail=True),
            "b": FakeProvider("b"),
        }
        router = _make_router(providers, config)

        # First request: a fails, falls back to b.
        r1 = await router.chat([ChatMessage(role="user", content="1")])
        assert r1.provider_name == "b"

        # Second request: a should be skipped (circuit open), goes to b.
        r2 = await router.chat([ChatMessage(role="user", content="2")])
        assert r2.provider_name == "b"
        # Provider a was only called once (the first time).
        assert providers["a"].call_count == 1


# ------------------------------------------------------------------ #
# Timeout handling
# ------------------------------------------------------------------ #


class TestTimeout:
    @pytest.mark.asyncio
    async def test_timeout_triggers_fallback(self):
        config = _make_config(
            ["a", "b"],
            provider_overrides={
                "a": {"timeout": 0.05},
                "b": {"timeout": 5.0},
            },
        )
        providers = {
            "a": FakeProvider("a", latency=1.0),  # will timeout
            "b": FakeProvider("b"),
        }
        router = _make_router(providers, config)
        result = await router.chat([ChatMessage(role="user", content="hi")])

        assert result.provider_name == "b"
        assert result.attempts[0].provider == "a"
        assert result.attempts[0].success is False
        assert "TimeoutError" in (result.attempts[0].error or "")


# ------------------------------------------------------------------ #
# All providers failed
# ------------------------------------------------------------------ #


class TestAllFailed:
    @pytest.mark.asyncio
    async def test_raises_when_all_fail(self):
        providers = {
            "a": FakeProvider("a", should_fail=True),
            "b": FakeProvider("b", should_fail=True),
        }
        router = _make_router(providers)
        with pytest.raises(AllProvidersFailedError) as exc_info:
            await router.chat([ChatMessage(role="user", content="hi")])

        assert len(exc_info.value.attempts) == 2
        assert all(not a.success for a in exc_info.value.attempts)

    @pytest.mark.asyncio
    async def test_raises_when_no_providers(self):
        router = _make_router({})
        with pytest.raises(AllProvidersFailedError):
            await router.chat([ChatMessage(role="user", content="hi")])


# ------------------------------------------------------------------ #
# Metrics tracking
# ------------------------------------------------------------------ #


class TestMetrics:
    @pytest.mark.asyncio
    async def test_records_success(self):
        providers = {"a": FakeProvider("a")}
        router = _make_router(providers)
        await router.chat([ChatMessage(role="user", content="hi")])

        m = router.metrics.get_metrics()
        assert "a" in m
        assert m["a"]["successes"] == 1
        assert m["a"]["failures"] == 0

    @pytest.mark.asyncio
    async def test_records_failure_and_success(self):
        providers = {
            "a": FakeProvider("a", should_fail=True),
            "b": FakeProvider("b"),
        }
        router = _make_router(providers)
        await router.chat([ChatMessage(role="user", content="hi")])

        m = router.metrics.get_metrics()
        assert m["a"]["failures"] == 1
        assert m["b"]["successes"] == 1

    def test_metrics_reset(self):
        metrics = ProviderMetrics()
        metrics.record_success("a", 10.0)
        metrics.record_failure("b", 20.0)
        assert len(metrics.get_metrics()) == 2

        metrics.reset("a")
        assert "a" not in metrics.get_metrics()
        assert "b" in metrics.get_metrics()

        metrics.reset()
        assert len(metrics.get_metrics()) == 0

    def test_avg_latency(self):
        metrics = ProviderMetrics()
        metrics.record_success("a", 10.0)
        metrics.record_success("a", 20.0)
        m = metrics.get_metrics()
        assert m["a"]["avg_latency_ms"] == 15.0
