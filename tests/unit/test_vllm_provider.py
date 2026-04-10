"""Unit tests for the vLLM provider."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BMT_PKG = _REPO_ROOT / "bmt-ai-os"
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_BMT_PKG))

from bmt_ai_os.providers.base import (  # noqa: E402
    ChatMessage,
    ChatResponse,
    ModelInfo,
    ModelNotFoundError,
    ProviderError,
    ProviderHealth,
)
from bmt_ai_os.providers.vllm import VLLMProvider  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chat_response(content: str = "Hello!", model: str = "test-model") -> dict:
    """Return a realistic vLLM /v1/chat/completions response."""
    return {
        "id": "chatcmpl-abc123",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 8,
            "total_tokens": 20,
        },
    }


def _make_models_response(model_ids: list[str] | None = None) -> dict:
    """Return a realistic vLLM /v1/models response."""
    model_ids = model_ids or ["Qwen/Qwen2.5-Coder-7B-Instruct"]
    return {
        "object": "list",
        "data": [{"id": mid, "object": "model", "owned_by": "vllm"} for mid in model_ids],
    }


def _make_embeddings_response(
    embeddings: list[list[float]] | None = None,
) -> dict:
    """Return a realistic vLLM /v1/embeddings response."""
    embeddings = embeddings or [[0.1, 0.2, 0.3]]
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "index": i, "embedding": emb}
            for i, emb in enumerate(embeddings)
        ],
        "model": "test-model",
        "usage": {"prompt_tokens": 5, "total_tokens": 5},
    }


class _FakeResponse:
    """Minimal fake for aiohttp.ClientResponse."""

    def __init__(self, status: int, json_data: dict | None = None, text: str = ""):
        self.status = status
        self._json_data = json_data or {}
        self._text = text

    async def json(self) -> dict:
        return self._json_data

    async def text(self) -> str:
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class _FakeSession:
    """Minimal fake for aiohttp.ClientSession."""

    def __init__(self, response: _FakeResponse):
        self._response = response

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        return self._response

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        return self._response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------


class TestVLLMURLConstruction:
    def test_default_base_url(self):
        p = VLLMProvider()
        assert p.build_url("/v1/models") == "http://localhost:8001/v1/models"

    def test_custom_base_url(self):
        p = VLLMProvider(base_url="http://10.0.0.5:8001/")
        assert p.build_url("/v1/models") == "http://10.0.0.5:8001/v1/models"

    def test_default_model(self):
        p = VLLMProvider()
        assert p._default_model == "qwen2.5-coder-7b-instruct"

    def test_custom_model(self):
        p = VLLMProvider(default_model="llama3-8b")
        assert p._default_model == "llama3-8b"


# ---------------------------------------------------------------------------
# Provider name
# ---------------------------------------------------------------------------


class TestVLLMProviderName:
    def test_name_is_vllm(self):
        p = VLLMProvider()
        assert p.name == "vllm"


# ---------------------------------------------------------------------------
# Chat (non-streaming)
# ---------------------------------------------------------------------------


class TestVLLMChat:
    def test_chat_returns_response(self):
        provider = VLLMProvider()
        resp_data = _make_chat_response("Hi there")
        fake_resp = _FakeResponse(200, resp_data)
        fake_session = _FakeSession(fake_resp)

        with patch("aiohttp.ClientSession", return_value=fake_session):
            result = asyncio.run(
                provider.chat(
                    [ChatMessage(role="user", content="Hello")],
                    model="test-model",
                )
            )

        assert isinstance(result, ChatResponse)
        assert result.content == "Hi there"
        assert result.provider == "vllm"
        assert result.usage.prompt_tokens == 12
        assert result.usage.completion_tokens == 8
        assert result.usage.total_tokens == 20

    def test_chat_uses_default_model(self):
        provider = VLLMProvider(default_model="my-model")
        resp_data = _make_chat_response("ok")
        fake_resp = _FakeResponse(200, resp_data)
        fake_session = _FakeSession(fake_resp)

        with patch("aiohttp.ClientSession", return_value=fake_session):
            result = asyncio.run(provider.chat([ChatMessage(role="user", content="hi")]))

        assert result.model == "my-model"

    def test_chat_404_raises_model_not_found(self):
        provider = VLLMProvider()
        fake_resp = _FakeResponse(404, text="not found")
        fake_session = _FakeSession(fake_resp)

        with patch("aiohttp.ClientSession", return_value=fake_session):
            with pytest.raises(ModelNotFoundError):
                asyncio.run(provider.chat([ChatMessage(role="user", content="hi")]))

    def test_chat_500_raises_provider_error(self):
        provider = VLLMProvider()
        fake_resp = _FakeResponse(500, text="internal error")
        fake_session = _FakeSession(fake_resp)

        with patch("aiohttp.ClientSession", return_value=fake_session):
            with pytest.raises(ProviderError, match="vLLM returned 500"):
                asyncio.run(provider.chat([ChatMessage(role="user", content="hi")]))


# ---------------------------------------------------------------------------
# List models
# ---------------------------------------------------------------------------


class TestVLLMListModels:
    def test_list_models(self):
        provider = VLLMProvider()
        resp_data = _make_models_response(["model-a", "model-b"])
        fake_resp = _FakeResponse(200, resp_data)
        fake_session = _FakeSession(fake_resp)

        with patch("aiohttp.ClientSession", return_value=fake_session):
            models = asyncio.run(provider.list_models())

        assert len(models) == 2
        assert all(isinstance(m, ModelInfo) for m in models)
        assert models[0].name == "model-a"
        assert models[1].name == "model-b"


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


class TestVLLMHealthCheck:
    def test_healthy(self):
        provider = VLLMProvider()
        resp_data = _make_models_response()
        fake_resp = _FakeResponse(200, resp_data)
        fake_session = _FakeSession(fake_resp)

        with patch("aiohttp.ClientSession", return_value=fake_session):
            health = asyncio.run(provider.health_check())

        assert isinstance(health, ProviderHealth)
        assert health.healthy is True
        assert health.error is None

    def test_unhealthy_on_error(self):
        provider = VLLMProvider()
        fake_resp = _FakeResponse(503, text="unavailable")
        fake_session = _FakeSession(fake_resp)

        with patch("aiohttp.ClientSession", return_value=fake_session):
            health = asyncio.run(provider.health_check())

        assert health.healthy is False
        assert health.error is not None


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


class TestVLLMEmbed:
    def test_embed_via_vllm(self):
        provider = VLLMProvider()
        resp_data = _make_embeddings_response([[0.1, 0.2], [0.3, 0.4]])
        fake_resp = _FakeResponse(200, resp_data)
        fake_session = _FakeSession(fake_resp)

        with patch("aiohttp.ClientSession", return_value=fake_session):
            embeddings = asyncio.run(provider.embed(["hello", "world"]))

        assert len(embeddings) == 2
        assert embeddings[0] == [0.1, 0.2]
        assert embeddings[1] == [0.3, 0.4]

    def test_embed_falls_back_to_ollama(self):
        """When vLLM embed fails, should fall back to Ollama."""
        provider = VLLMProvider()

        call_count = 0

        class _FallbackSession:
            def post(self, url: str, **kwargs):
                nonlocal call_count
                call_count += 1
                if "/v1/embeddings" in url:
                    # vLLM fails
                    return _FakeResponse(400, text="not supported")
                # Ollama succeeds
                return _FakeResponse(
                    200,
                    {"embeddings": [[0.5, 0.6, 0.7]]},
                )

            def get(self, url: str, **kwargs):
                return _FakeResponse(200, {})

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        with patch("aiohttp.ClientSession", return_value=_FallbackSession()):
            embeddings = asyncio.run(provider.embed(["test"]))

        assert embeddings == [[0.5, 0.6, 0.7]]
        assert call_count == 2  # One vLLM attempt, one Ollama fallback

    def test_embed_no_results_raises(self):
        provider = VLLMProvider()
        resp_data = {"data": []}
        fake_resp = _FakeResponse(200, resp_data)
        _fake_session = _FakeSession(fake_resp)

        # Both vLLM and Ollama fail
        class _FailSession:
            def post(self, url: str, **kwargs):
                if "/v1/embeddings" in url:
                    return _FakeResponse(200, {"data": []})
                return _FakeResponse(200, {"embeddings": []})

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        with patch("aiohttp.ClientSession", return_value=_FailSession()):
            with pytest.raises(ProviderError):
                asyncio.run(provider.embed(["test"]))


# ---------------------------------------------------------------------------
# Token usage parsing
# ---------------------------------------------------------------------------


class TestVLLMTokenUsage:
    def test_parse_usage(self):
        data = {
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30,
            }
        }
        usage = VLLMProvider._parse_usage(data)
        assert usage.prompt_tokens == 10
        assert usage.completion_tokens == 20
        assert usage.total_tokens == 30

    def test_parse_usage_missing(self):
        usage = VLLMProvider._parse_usage({})
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0
        assert usage.total_tokens == 0


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


class TestVLLMRegistryIntegration:
    def test_register_and_retrieve(self):
        from bmt_ai_os.providers.registry import ProviderRegistry

        reg = ProviderRegistry()
        provider = VLLMProvider()
        reg.register("vllm", provider)
        assert reg.get("vllm") is provider
        assert reg.get("vllm").name == "vllm"
