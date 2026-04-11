"""Unit tests for bmt_ai_os.providers.registry.

Covers:
- ProviderRegistry: register, unregister, get, list, set_active, get_active
- Active-provider auto-selection on first registration
- health_check_all with concurrent providers
- Singleton get_registry / reset_registry
"""

from __future__ import annotations

import asyncio

import pytest

from bmt_ai_os.providers.base import (
    ChatResponse,
    LLMProvider,
    ProviderError,
    ProviderHealth,
    TokenUsage,
)
from bmt_ai_os.providers.registry import (
    ProviderRegistry,
    get_registry,
    reset_registry,
)

# ---------------------------------------------------------------------------
# Minimal fake provider
# ---------------------------------------------------------------------------


class _Fake(LLMProvider):
    def __init__(self, name: str = "fake", *, healthy: bool = True) -> None:
        self._name = name
        self._healthy = healthy

    @property
    def name(self) -> str:
        return self._name

    async def chat(self, messages, **kwargs):
        return ChatResponse(
            content="ok",
            model="fake",
            provider=self._name,
            usage=TokenUsage(0, 0, 0),
            latency_ms=0.0,
        )

    async def embed(self, text, **kwargs):
        return []

    async def list_models(self):
        return []

    async def health_check(self) -> ProviderHealth:
        if not self._healthy:
            return ProviderHealth(healthy=False, latency_ms=0.0, error="down")
        return ProviderHealth(healthy=True, latency_ms=1.0)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegisterUnregister:
    def test_register_single_becomes_active(self):
        reg = ProviderRegistry()
        p = _Fake("p1")
        reg.register("p1", p)
        assert reg.active_name == "p1"
        assert reg.get("p1") is p

    def test_second_registration_does_not_change_active(self):
        reg = ProviderRegistry()
        reg.register("p1", _Fake("p1"))
        reg.register("p2", _Fake("p2"))
        assert reg.active_name == "p1"

    def test_list_returns_all_names(self):
        reg = ProviderRegistry()
        reg.register("a", _Fake("a"))
        reg.register("b", _Fake("b"))
        assert sorted(reg.list()) == ["a", "b"]

    def test_unregister_removes_provider(self):
        reg = ProviderRegistry()
        reg.register("p", _Fake("p"))
        reg.unregister("p")
        assert "p" not in reg.list()

    def test_unregister_active_switches_to_next(self):
        reg = ProviderRegistry()
        reg.register("first", _Fake("first"))
        reg.register("second", _Fake("second"))
        reg.unregister("first")
        assert reg.active_name == "second"

    def test_unregister_last_active_becomes_none(self):
        reg = ProviderRegistry()
        reg.register("only", _Fake("only"))
        reg.unregister("only")
        assert reg.active_name is None

    def test_unregister_nonexistent_is_noop(self):
        reg = ProviderRegistry()
        reg.register("p", _Fake("p"))
        reg.unregister("does-not-exist")
        assert "p" in reg.list()

    def test_overwrite_registration(self):
        reg = ProviderRegistry()
        p1 = _Fake("p")
        p2 = _Fake("p")
        reg.register("p", p1)
        reg.register("p", p2)
        assert reg.get("p") is p2


# ---------------------------------------------------------------------------
# Lookup errors
# ---------------------------------------------------------------------------


class TestGet:
    def test_get_unknown_raises_provider_error(self):
        reg = ProviderRegistry()
        with pytest.raises(ProviderError, match="not registered"):
            reg.get("ghost")

    def test_error_message_includes_available(self):
        reg = ProviderRegistry()
        reg.register("ollama", _Fake("ollama"))
        with pytest.raises(ProviderError, match="ollama"):
            reg.get("openai")

    def test_error_message_none_available(self):
        reg = ProviderRegistry()
        with pytest.raises(ProviderError, match=r"\(none\)"):
            reg.get("any")


# ---------------------------------------------------------------------------
# Active provider
# ---------------------------------------------------------------------------


class TestActiveProvider:
    def test_get_active_returns_registered_instance(self):
        reg = ProviderRegistry()
        p = _Fake("p")
        reg.register("p", p)
        assert reg.get_active() is p

    def test_get_active_no_providers_raises(self):
        reg = ProviderRegistry()
        with pytest.raises(ProviderError, match="No provider"):
            reg.get_active()

    def test_set_active_switches(self):
        reg = ProviderRegistry()
        reg.register("a", _Fake("a"))
        reg.register("b", _Fake("b"))
        reg.set_active("b")
        assert reg.active_name == "b"
        assert reg.get_active().name == "b"

    def test_set_active_unknown_raises(self):
        reg = ProviderRegistry()
        reg.register("a", _Fake("a"))
        with pytest.raises(ProviderError, match="unknown provider"):
            reg.set_active("ghost")

    def test_set_active_error_includes_registered_names(self):
        reg = ProviderRegistry()
        reg.register("ollama", _Fake("ollama"))
        with pytest.raises(ProviderError, match="ollama"):
            reg.set_active("openai")


# ---------------------------------------------------------------------------
# health_check_all
# ---------------------------------------------------------------------------


class TestHealthCheckAll:
    def test_empty_registry_returns_empty_dict(self):
        reg = ProviderRegistry()
        result = asyncio.run(reg.health_check_all())
        assert result == {}

    def test_healthy_and_unhealthy_providers(self):
        reg = ProviderRegistry()
        reg.register("good", _Fake("good", healthy=True))
        reg.register("bad", _Fake("bad", healthy=False))
        result = asyncio.run(reg.health_check_all())
        assert result["good"].healthy is True
        assert result["bad"].healthy is False

    def test_exception_during_health_check_is_caught(self):
        class BrokenProvider(_Fake):
            async def embed(self, text, **kwargs):
                return []

            async def list_models(self):
                return []

            async def health_check(self):
                raise RuntimeError("boom")

        reg = ProviderRegistry()
        reg.register("broken", BrokenProvider("broken"))
        result = asyncio.run(reg.health_check_all())
        assert result["broken"].healthy is False
        assert "boom" in result["broken"].error

    def test_all_providers_checked(self):
        reg = ProviderRegistry()
        for name in ["a", "b", "c"]:
            reg.register(name, _Fake(name))
        result = asyncio.run(reg.health_check_all())
        assert set(result.keys()) == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def setup_method(self):
        reset_registry()

    def teardown_method(self):
        reset_registry()

    def test_get_registry_returns_same_instance(self):
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_reset_registry_creates_fresh_instance(self):
        r1 = get_registry()
        r1.register("p", _Fake("p"))
        reset_registry()
        r2 = get_registry()
        assert r2 is not r1
        assert r2.list() == []

    def test_get_registry_after_reset_is_fresh(self):
        get_registry().register("x", _Fake("x"))
        reset_registry()
        assert get_registry().list() == []
