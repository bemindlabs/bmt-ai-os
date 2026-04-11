"""Unit tests for bmt_ai_os.providers.registry."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from bmt_ai_os.providers.base import ProviderError, ProviderHealth
from bmt_ai_os.providers.registry import ProviderRegistry, get_registry, reset_registry


def _make_provider(name: str = "test", healthy: bool = True) -> MagicMock:
    provider = MagicMock()
    provider.name = name
    provider.health_check = AsyncMock(
        return_value=ProviderHealth(healthy=healthy, latency_ms=5.0, error="")
    )
    return provider


class TestProviderRegistryRegister:
    def test_register_single_provider(self):
        reg = ProviderRegistry()
        p = _make_provider("ollama")
        reg.register("ollama", p)
        assert "ollama" in reg.list()

    def test_first_registered_becomes_active(self):
        reg = ProviderRegistry()
        reg.register("ollama", _make_provider("ollama"))
        assert reg.active_name == "ollama"

    def test_second_provider_does_not_change_active(self):
        reg = ProviderRegistry()
        reg.register("ollama", _make_provider("ollama"))
        reg.register("openai", _make_provider("openai"))
        assert reg.active_name == "ollama"

    def test_register_overwrites_existing(self):
        reg = ProviderRegistry()
        p1 = _make_provider("ollama")
        p2 = _make_provider("ollama")
        reg.register("ollama", p1)
        reg.register("ollama", p2)
        assert reg.get("ollama") is p2


class TestProviderRegistryUnregister:
    def test_unregister_removes_provider(self):
        reg = ProviderRegistry()
        reg.register("ollama", _make_provider())
        reg.unregister("ollama")
        assert "ollama" not in reg.list()

    def test_unregister_unknown_is_noop(self):
        reg = ProviderRegistry()
        reg.unregister("nonexistent")  # should not raise

    def test_unregister_active_switches_to_next(self):
        reg = ProviderRegistry()
        reg.register("ollama", _make_provider("ollama"))
        reg.register("openai", _make_provider("openai"))
        reg.unregister("ollama")
        assert reg.active_name == "openai"

    def test_unregister_last_provider_sets_active_none(self):
        reg = ProviderRegistry()
        reg.register("ollama", _make_provider())
        reg.unregister("ollama")
        assert reg.active_name is None


class TestProviderRegistryGet:
    def test_get_returns_registered_provider(self):
        reg = ProviderRegistry()
        p = _make_provider("ollama")
        reg.register("ollama", p)
        assert reg.get("ollama") is p

    def test_get_raises_for_unknown(self):
        reg = ProviderRegistry()
        with pytest.raises(ProviderError, match="not registered"):
            reg.get("nonexistent")

    def test_list_returns_all_names(self):
        reg = ProviderRegistry()
        reg.register("a", _make_provider("a"))
        reg.register("b", _make_provider("b"))
        names = reg.list()
        assert set(names) == {"a", "b"}


class TestProviderRegistryActive:
    def test_set_active_switches_provider(self):
        reg = ProviderRegistry()
        reg.register("ollama", _make_provider("ollama"))
        reg.register("openai", _make_provider("openai"))
        reg.set_active("openai")
        assert reg.active_name == "openai"

    def test_set_active_raises_for_unknown(self):
        reg = ProviderRegistry()
        with pytest.raises(ProviderError, match="unknown provider"):
            reg.set_active("nonexistent")

    def test_get_active_returns_correct_provider(self):
        reg = ProviderRegistry()
        p = _make_provider("ollama")
        reg.register("ollama", p)
        assert reg.get_active() is p

    def test_get_active_raises_when_none_registered(self):
        reg = ProviderRegistry()
        with pytest.raises(ProviderError, match="No provider"):
            reg.get_active()


class TestHealthCheckAll:
    def test_returns_empty_dict_when_no_providers(self):
        reg = ProviderRegistry()
        result = asyncio.run(reg.health_check_all())
        assert result == {}

    def test_returns_health_for_all_providers(self):
        reg = ProviderRegistry()
        reg.register("ollama", _make_provider("ollama", healthy=True))
        reg.register("openai", _make_provider("openai", healthy=False))
        result = asyncio.run(reg.health_check_all())
        assert "ollama" in result
        assert "openai" in result
        assert result["ollama"].healthy is True
        assert result["openai"].healthy is False

    def test_handles_provider_exception(self):
        reg = ProviderRegistry()
        p = MagicMock()
        p.health_check = AsyncMock(side_effect=RuntimeError("boom"))
        reg.register("bad", p)
        result = asyncio.run(reg.health_check_all())
        assert result["bad"].healthy is False
        assert "boom" in result["bad"].error


class TestSingletonHelpers:
    def test_get_registry_returns_same_instance(self):
        reset_registry()
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_reset_registry_creates_fresh_instance(self):
        r1 = get_registry()
        r1.register("ollama", _make_provider("ollama"))
        reset_registry()
        r2 = get_registry()
        assert r2.list() == []
