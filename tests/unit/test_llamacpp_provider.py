"""Unit tests for the llama.cpp (llama-server) provider."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BMT_PKG = _REPO_ROOT / "bmt-ai-os"
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_BMT_PKG))

from providers.base import (
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
from providers.llamacpp import LlamaCppProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


def _mock_response(*, status: int = 200, json_data: dict | None = None,
                   text: str = ""):
    """Create a mock aiohttp response."""
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data or {})
    resp.text = AsyncMock(return_value=text)
    return resp


# ---------------------------------------------------------------------------
# Constructor / URL tests
# ---------------------------------------------------------------------------

class TestLlamaCppConstruction:

    def test_default_base_url(self):
        p = LlamaCppProvider()
        assert p.build_url("/health") == "http://localhost:8002/health"

    def test_custom_base_url(self):
        p = LlamaCppProvider(base_url="http://10.0.0.5:9999/")
        assert p.build_url("/v1/models") == "http://10.0.0.5:9999/v1/models"

    def test_trailing_slash_stripped(self):
        p = LlamaCppProvider(base_url="http://host:8002/")
        assert p._base_url == "http://host:8002"

    def test_default_model(self):
        p = LlamaCppProvider()
        assert p._default_model == "qwen2.5-coder-7b-instruct-q4_k_m.gguf"

    def test_custom_model(self):
        p = LlamaCppProvider(default_model="my-model.gguf")
        assert p._default_model == "my-model.gguf"

    def test_name_property(self):
        p = LlamaCppProvider()
        assert p.name == "llama-cpp"

    def test_is_llm_provider(self):
        p = LlamaCppProvider()
        assert isinstance(p, LLMProvider)

    def test_custom_n_ctx(self):
        p = LlamaCppProvider(n_ctx=8192)
        assert p._n_ctx == 8192

    def test_custom_n_threads(self):
        p = LlamaCppProvider(n_threads=8)
        assert p._n_threads == 8


# ---------------------------------------------------------------------------
# chat() — non-streaming
# ---------------------------------------------------------------------------

class TestLlamaCppChat:

    @pytest.fixture
    def provider(self):
        return LlamaCppProvider()

    def test_chat_returns_response(self, provider):
        mock_json = {
            "choices": [
                {"message": {"role": "assistant", "content": "Hello!"}}
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        }

        with patch.object(provider, "_post", new_callable=AsyncMock,
                          return_value=mock_json):
            msgs = [ChatMessage(role="user", content="Hi")]
            result = _run(provider.chat(msgs))

        assert isinstance(result, ChatResponse)
        assert result.content == "Hello!"
        assert result.provider == "llama-cpp"
        assert result.usage.prompt_tokens == 10
        assert result.usage.completion_tokens == 5
        assert result.usage.total_tokens == 15
        assert result.latency_ms >= 0

    def test_chat_uses_default_model(self, provider):
        mock_json = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {},
        }

        with patch.object(provider, "_post", new_callable=AsyncMock,
                          return_value=mock_json) as mock_post:
            msgs = [ChatMessage(role="user", content="test")]
            _run(provider.chat(msgs))

        call_args = mock_post.call_args
        payload = call_args[0][1]
        assert payload["model"] == "qwen2.5-coder-7b-instruct-q4_k_m.gguf"

    def test_chat_uses_custom_model(self, provider):
        mock_json = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {},
        }

        with patch.object(provider, "_post", new_callable=AsyncMock,
                          return_value=mock_json) as mock_post:
            msgs = [ChatMessage(role="user", content="test")]
            _run(provider.chat(msgs, model="custom.gguf"))

        call_args = mock_post.call_args
        payload = call_args[0][1]
        assert payload["model"] == "custom.gguf"

    def test_chat_empty_choices(self, provider):
        mock_json = {"choices": [], "usage": {}}

        with patch.object(provider, "_post", new_callable=AsyncMock,
                          return_value=mock_json):
            msgs = [ChatMessage(role="user", content="test")]
            result = _run(provider.chat(msgs))

        assert result.content == ""

    def test_chat_passes_temperature_and_max_tokens(self, provider):
        mock_json = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {},
        }

        with patch.object(provider, "_post", new_callable=AsyncMock,
                          return_value=mock_json) as mock_post:
            msgs = [ChatMessage(role="user", content="test")]
            _run(provider.chat(msgs, temperature=0.2, max_tokens=512))

        payload = mock_post.call_args[0][1]
        assert payload["temperature"] == 0.2
        assert payload["max_tokens"] == 512


# ---------------------------------------------------------------------------
# embed()
# ---------------------------------------------------------------------------

class TestLlamaCppEmbed:

    @pytest.fixture
    def provider(self):
        return LlamaCppProvider()

    def test_embed_returns_vectors(self, provider):
        mock_json = {
            "data": [
                {"index": 0, "embedding": [0.1, 0.2, 0.3]},
                {"index": 1, "embedding": [0.4, 0.5, 0.6]},
            ]
        }

        with patch.object(provider, "_post", new_callable=AsyncMock,
                          return_value=mock_json):
            result = _run(provider.embed(["hello", "world"]))

        assert len(result) == 2
        assert result[0] == [0.1, 0.2, 0.3]
        assert result[1] == [0.4, 0.5, 0.6]

    def test_embed_preserves_order(self, provider):
        # Data returned out of order — provider should sort by index.
        mock_json = {
            "data": [
                {"index": 1, "embedding": [0.4, 0.5]},
                {"index": 0, "embedding": [0.1, 0.2]},
            ]
        }

        with patch.object(provider, "_post", new_callable=AsyncMock,
                          return_value=mock_json):
            result = _run(provider.embed(["first", "second"]))

        assert result[0] == [0.1, 0.2]
        assert result[1] == [0.4, 0.5]

    def test_embed_empty_raises(self, provider):
        mock_json = {"data": []}

        with patch.object(provider, "_post", new_callable=AsyncMock,
                          return_value=mock_json):
            with pytest.raises(ProviderError, match="no embeddings"):
                _run(provider.embed(["test"]))


# ---------------------------------------------------------------------------
# list_models()
# ---------------------------------------------------------------------------

class TestLlamaCppListModels:

    @pytest.fixture
    def provider(self):
        return LlamaCppProvider()

    def test_list_models_returns_server_models(self, provider):
        mock_json = {
            "data": [
                {"id": "my-model.gguf", "object": "model"},
            ]
        }

        with patch.object(provider, "_get", new_callable=AsyncMock,
                          return_value=mock_json):
            result = _run(provider.list_models())

        assert len(result) == 1
        assert result[0].name == "my-model.gguf"
        assert isinstance(result[0], ModelInfo)

    def test_list_models_empty_falls_back(self, provider):
        mock_json = {"data": []}

        with patch.object(provider, "_get", new_callable=AsyncMock,
                          return_value=mock_json):
            result = _run(provider.list_models())

        assert len(result) == 1
        assert result[0].name == provider._default_model


# ---------------------------------------------------------------------------
# health_check()
# ---------------------------------------------------------------------------

class TestLlamaCppHealthCheck:

    @pytest.fixture
    def provider(self):
        return LlamaCppProvider()

    def test_healthy(self, provider):
        mock_json = {"status": "ok"}

        with patch.object(provider, "_get", new_callable=AsyncMock,
                          return_value=mock_json):
            result = _run(provider.health_check())

        assert isinstance(result, ProviderHealth)
        assert result.healthy is True
        assert result.error is None

    def test_unhealthy_status(self, provider):
        mock_json = {"status": "loading model"}

        with patch.object(provider, "_get", new_callable=AsyncMock,
                          return_value=mock_json):
            result = _run(provider.health_check())

        assert result.healthy is False
        assert "loading model" in result.error

    def test_connection_error(self, provider):
        with patch.object(provider, "_get", new_callable=AsyncMock,
                          side_effect=ProviderError("connection refused")):
            result = _run(provider.health_check())

        assert result.healthy is False
        assert "connection refused" in result.error


# ---------------------------------------------------------------------------
# HTTP error handling
# ---------------------------------------------------------------------------

class TestLlamaCppHTTPErrors:

    @pytest.fixture
    def provider(self):
        return LlamaCppProvider()

    def test_post_404_raises_model_not_found(self, provider):
        async def _fake_post(path, payload):
            raise ModelNotFoundError(f"Model not found: {payload.get('model')}")

        with patch.object(provider, "_post", side_effect=_fake_post):
            msgs = [ChatMessage(role="user", content="test")]
            with pytest.raises(ModelNotFoundError):
                _run(provider.chat(msgs))

    def test_post_500_raises_provider_error(self, provider):
        async def _fake_post(path, payload):
            raise ProviderError("llama-server returned 500: Internal Server Error")

        with patch.object(provider, "_post", side_effect=_fake_post):
            msgs = [ChatMessage(role="user", content="test")]
            with pytest.raises(ProviderError, match="llama-server returned 500"):
                _run(provider.chat(msgs))

    def test_get_error_in_health_check(self, provider):
        with patch.object(provider, "_get", new_callable=AsyncMock,
                          side_effect=ProviderError("connect refused")):
            result = _run(provider.health_check())
        assert result.healthy is False

    def test_timeout_raises_timeout_error(self, provider):
        async def _fake_post(path, payload):
            raise ProviderTimeoutError("request timed out")

        with patch.object(provider, "_post", side_effect=_fake_post):
            msgs = [ChatMessage(role="user", content="test")]
            with pytest.raises(ProviderTimeoutError):
                _run(provider.chat(msgs))


# ---------------------------------------------------------------------------
# Usage parsing
# ---------------------------------------------------------------------------

class TestUsageParsing:

    def test_parse_usage_complete(self):
        data = {
            "usage": {
                "prompt_tokens": 42,
                "completion_tokens": 18,
                "total_tokens": 60,
            }
        }
        usage = LlamaCppProvider._parse_usage(data)
        assert usage.prompt_tokens == 42
        assert usage.completion_tokens == 18
        assert usage.total_tokens == 60

    def test_parse_usage_missing(self):
        usage = LlamaCppProvider._parse_usage({})
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0
        assert usage.total_tokens == 0

    def test_parse_usage_calculates_total(self):
        data = {
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
            }
        }
        usage = LlamaCppProvider._parse_usage(data)
        assert usage.total_tokens == 15
