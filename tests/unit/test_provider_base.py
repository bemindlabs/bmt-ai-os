"""Unit tests for the LLM provider abstraction layer."""

from __future__ import annotations

import asyncio
import os

# We use direct imports from the package path rather than the installed
# package name so the tests work without ``pip install -e .``.
import sys
import textwrap
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BMT_PKG = _REPO_ROOT / "bmt-ai-os"
# Add both repo root and bmt-ai-os to path so imports resolve correctly.
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_BMT_PKG))

from bmt_ai_os.providers.base import (  # noqa: E402
    ChatMessage,
    ChatResponse,
    LLMProvider,
    ModelInfo,
    ModelNotFoundError,
    ProviderError,
    ProviderHealth,
    ProviderTimeoutError,
    TokenUsage,
)
from bmt_ai_os.providers.config import ProvidersConfig, ProviderSettings, load_config  # noqa: E402
from bmt_ai_os.providers.ollama import OllamaProvider  # noqa: E402
from bmt_ai_os.providers.registry import ProviderRegistry, reset_registry  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeProvider(LLMProvider):
    """Minimal concrete provider for testing the abstract interface."""

    def __init__(self, provider_name: str = "fake") -> None:
        self._name = provider_name

    @property
    def name(self) -> str:
        return self._name

    async def chat(self, messages, *, model=None, temperature=0.7, max_tokens=2048, stream=False):
        return ChatResponse(
            content="hello",
            model=model or "fake-model",
            provider=self.name,
            usage=TokenUsage(10, 5, 15),
            latency_ms=1.0,
        )

    async def embed(self, texts, *, model=None):
        return [[0.1, 0.2, 0.3] for _ in texts]

    async def list_models(self):
        return [ModelInfo(name="fake-model", size_bytes=100, family="fake")]

    async def health_check(self):
        return ProviderHealth(healthy=True, latency_ms=0.5)


# ---------------------------------------------------------------------------
# Data-class serialisation
# ---------------------------------------------------------------------------


class TestChatResponseSerialization:
    def test_to_dict_returns_plain_dict(self):
        usage = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        resp = ChatResponse(
            content="Hi",
            model="qwen2.5-coder:7b",
            provider="ollama",
            usage=usage,
            latency_ms=42.0,
        )
        d = resp.to_dict()

        assert isinstance(d, dict)
        assert d["content"] == "Hi"
        assert d["model"] == "qwen2.5-coder:7b"
        assert d["provider"] == "ollama"
        assert d["usage"]["total_tokens"] == 15
        assert d["latency_ms"] == 42.0

    def test_chat_message_to_dict(self):
        msg = ChatMessage(role="user", content="Hello")
        d = msg.to_dict()
        assert d == {"role": "user", "content": "Hello"}

    def test_model_info_to_dict(self):
        info = ModelInfo(name="m", size_bytes=1024, quantization="Q4_K_M", family="qwen")
        d = info.to_dict()
        assert d["quantization"] == "Q4_K_M"

    def test_provider_health_to_dict(self):
        h = ProviderHealth(healthy=False, latency_ms=100.0, error="timeout")
        d = h.to_dict()
        assert d["healthy"] is False
        assert d["error"] == "timeout"


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------


class TestProviderRegistry:
    def setup_method(self):
        reset_registry()

    def test_register_and_get(self):
        reg = ProviderRegistry()
        provider = FakeProvider("a")
        reg.register("a", provider)
        assert reg.get("a") is provider

    def test_get_unknown_raises(self):
        reg = ProviderRegistry()
        with pytest.raises(ProviderError, match="not registered"):
            reg.get("missing")

    def test_list_returns_names(self):
        reg = ProviderRegistry()
        reg.register("b", FakeProvider("b"))
        reg.register("a", FakeProvider("a"))
        assert set(reg.list()) == {"a", "b"}

    def test_first_registered_becomes_active(self):
        reg = ProviderRegistry()
        reg.register("first", FakeProvider("first"))
        reg.register("second", FakeProvider("second"))
        assert reg.active_name == "first"

    def test_set_active(self):
        reg = ProviderRegistry()
        reg.register("a", FakeProvider("a"))
        reg.register("b", FakeProvider("b"))
        reg.set_active("b")
        assert reg.get_active().name == "b"

    def test_set_active_unknown_raises(self):
        reg = ProviderRegistry()
        with pytest.raises(ProviderError, match="Cannot activate"):
            reg.set_active("ghost")

    def test_get_active_no_providers_raises(self):
        reg = ProviderRegistry()
        with pytest.raises(ProviderError, match="No provider"):
            reg.get_active()

    def test_unregister(self):
        reg = ProviderRegistry()
        reg.register("a", FakeProvider("a"))
        reg.unregister("a")
        assert reg.list() == []

    def test_health_check_all(self):
        reg = ProviderRegistry()
        reg.register("a", FakeProvider("a"))
        reg.register("b", FakeProvider("b"))
        results = asyncio.run(reg.health_check_all())
        assert results["a"].healthy is True
        assert results["b"].healthy is True


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class TestConfig:
    def test_load_from_yaml(self, tmp_path):
        cfg_file = tmp_path / "providers.yml"
        cfg_file.write_text(
            textwrap.dedent("""\
            active_provider: ollama
            fallback_chain: [ollama, vllm]
            providers:
              ollama:
                enabled: true
                base_url: http://localhost:11434
                default_model: qwen2.5-coder:7b-instruct-q4_K_M
                timeout: 30
              vllm:
                enabled: false
                base_url: http://localhost:8000
                default_model: qwen2.5-coder-7b-instruct
                timeout: 60
        """)
        )

        cfg = load_config(cfg_file)
        assert cfg.active_provider == "ollama"
        assert cfg.fallback_chain == ["ollama", "vllm"]
        assert cfg.providers["ollama"].enabled is True
        assert cfg.providers["vllm"].enabled is False
        assert cfg.providers["ollama"].timeout == 30

    def test_load_default_when_missing(self):
        cfg = load_config("/nonexistent/path/providers.yml")
        assert cfg.active_provider == "ollama"
        assert cfg.providers == {}

    def test_enabled_providers(self):
        cfg = ProvidersConfig(
            providers={
                "a": ProviderSettings(enabled=True),
                "b": ProviderSettings(enabled=False),
                "c": ProviderSettings(enabled=True),
            }
        )
        assert set(cfg.enabled_providers()) == {"a", "c"}

    def test_env_override(self, tmp_path):
        cfg_file = tmp_path / "custom.yml"
        cfg_file.write_text(
            textwrap.dedent("""\
            active_provider: vllm
            providers:
              vllm:
                enabled: true
                base_url: http://localhost:8000
        """)
        )

        os.environ["BMT_PROVIDERS_CONFIG"] = str(cfg_file)
        try:
            cfg = load_config()
            assert cfg.active_provider == "vllm"
        finally:
            del os.environ["BMT_PROVIDERS_CONFIG"]


# ---------------------------------------------------------------------------
# Ollama provider — URL construction
# ---------------------------------------------------------------------------


class TestOllamaURLConstruction:
    def test_default_base_url(self):
        p = OllamaProvider()
        assert p.build_url("/api/chat") == "http://localhost:11434/api/chat"

    def test_custom_base_url(self):
        p = OllamaProvider(base_url="http://10.0.0.5:11434/")
        # Trailing slash should be stripped.
        assert p.build_url("/api/tags") == "http://10.0.0.5:11434/api/tags"

    def test_default_model(self):
        p = OllamaProvider()
        assert p._default_model == "qwen2.5-coder:7b-instruct-q4_K_M"

    def test_custom_model(self):
        p = OllamaProvider(default_model="llama3:8b")
        assert p._default_model == "llama3:8b"


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class TestExceptions:
    def test_timeout_is_provider_error(self):
        assert issubclass(ProviderTimeoutError, ProviderError)

    def test_model_not_found_is_provider_error(self):
        assert issubclass(ModelNotFoundError, ProviderError)
