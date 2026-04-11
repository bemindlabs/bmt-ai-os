"""Unit tests for bmt_ai_os.providers.ollama.OllamaProvider.

All HTTP calls are intercepted with unittest.mock — no live Ollama required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bmt_ai_os.providers.base import (
    ChatMessage,
    ModelNotFoundError,
    ProviderError,
    ProviderTimeoutError,
    TokenUsage,
)
from bmt_ai_os.providers.ollama import OllamaProvider

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def provider() -> OllamaProvider:
    return OllamaProvider(base_url="http://localhost:11434", default_model="qwen2.5:7b", timeout=5)


@pytest.fixture()
def messages() -> list[ChatMessage]:
    return [ChatMessage(role="user", content="Hello")]


# ---------------------------------------------------------------------------
# Basic properties
# ---------------------------------------------------------------------------


class TestOllamaProviderProperties:
    def test_name(self, provider: OllamaProvider) -> None:
        assert provider.name == "ollama"

    def test_build_url(self, provider: OllamaProvider) -> None:
        assert provider.build_url("/api/tags") == "http://localhost:11434/api/tags"

    def test_trailing_slash_stripped(self) -> None:
        p = OllamaProvider(base_url="http://localhost:11434/")
        assert p.build_url("/api/tags") == "http://localhost:11434/api/tags"

    def test_default_model_fallback(self) -> None:
        p = OllamaProvider()
        assert "qwen" in p._default_model


# ---------------------------------------------------------------------------
# _parse_usage
# ---------------------------------------------------------------------------


class TestParseUsage:
    def test_normal(self) -> None:
        data = {"prompt_eval_count": 10, "eval_count": 20}
        usage = OllamaProvider._parse_usage(data)
        assert usage.prompt_tokens == 10
        assert usage.completion_tokens == 20
        assert usage.total_tokens == 30

    def test_missing_keys_defaults_to_zero(self) -> None:
        usage = OllamaProvider._parse_usage({})
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0
        assert usage.total_tokens == 0

    def test_returns_token_usage_instance(self) -> None:
        usage = OllamaProvider._parse_usage({"prompt_eval_count": 5, "eval_count": 3})
        assert isinstance(usage, TokenUsage)


# ---------------------------------------------------------------------------
# chat — non-streaming
# ---------------------------------------------------------------------------


class TestOllamaChatNonStreaming:
    @pytest.mark.asyncio
    async def test_successful_chat(
        self, provider: OllamaProvider, messages: list[ChatMessage]
    ) -> None:
        response_data = {
            "message": {"role": "assistant", "content": "Hello there!"},
            "prompt_eval_count": 5,
            "eval_count": 3,
        }
        with patch.object(provider, "_post", new=AsyncMock(return_value=response_data)):
            result = await provider.chat(messages)
        assert result.content == "Hello there!"
        assert result.provider == "ollama"
        assert result.model == "qwen2.5:7b"
        assert result.usage.total_tokens == 8

    @pytest.mark.asyncio
    async def test_uses_default_model_when_none(
        self, provider: OllamaProvider, messages: list[ChatMessage]
    ) -> None:
        response_data = {"message": {"content": "Hi"}, "prompt_eval_count": 1, "eval_count": 1}
        mock_fn = AsyncMock(return_value=response_data)
        with patch.object(provider, "_post", new=mock_fn) as mock_post:
            await provider.chat(messages, model=None)
        call_payload = mock_post.call_args[0][1]
        assert call_payload["model"] == "qwen2.5:7b"

    @pytest.mark.asyncio
    async def test_uses_explicit_model(
        self, provider: OllamaProvider, messages: list[ChatMessage]
    ) -> None:
        response_data = {"message": {"content": "Hi"}, "prompt_eval_count": 1, "eval_count": 1}
        mock_fn = AsyncMock(return_value=response_data)
        with patch.object(provider, "_post", new=mock_fn) as mock_post:
            await provider.chat(messages, model="llama3:8b")
        call_payload = mock_post.call_args[0][1]
        assert call_payload["model"] == "llama3:8b"

    @pytest.mark.asyncio
    async def test_temperature_passed_in_payload(
        self, provider: OllamaProvider, messages: list[ChatMessage]
    ) -> None:
        response_data = {"message": {"content": "ok"}, "prompt_eval_count": 0, "eval_count": 0}
        mock_fn = AsyncMock(return_value=response_data)
        with patch.object(provider, "_post", new=mock_fn) as mock_post:
            await provider.chat(messages, temperature=0.1)
        payload = mock_post.call_args[0][1]
        assert payload["options"]["temperature"] == 0.1

    @pytest.mark.asyncio
    async def test_empty_message_content(
        self, provider: OllamaProvider, messages: list[ChatMessage]
    ) -> None:
        response_data = {"message": {}, "prompt_eval_count": 0, "eval_count": 0}
        with patch.object(provider, "_post", new=AsyncMock(return_value=response_data)):
            result = await provider.chat(messages)
        assert result.content == ""

    @pytest.mark.asyncio
    async def test_stream_false_returns_chat_response(
        self, provider: OllamaProvider, messages: list[ChatMessage]
    ) -> None:
        from bmt_ai_os.providers.base import ChatResponse

        response_data = {"message": {"content": "ok"}, "prompt_eval_count": 1, "eval_count": 1}
        with patch.object(provider, "_post", new=AsyncMock(return_value=response_data)):
            result = await provider.chat(messages, stream=False)
        assert isinstance(result, ChatResponse)


# ---------------------------------------------------------------------------
# chat — streaming
# ---------------------------------------------------------------------------


class TestOllamaChatStreaming:
    @pytest.mark.asyncio
    async def test_stream_returns_generator(
        self, provider: OllamaProvider, messages: list[ChatMessage]
    ) -> None:
        import types

        async def fake_stream(payload, model):
            for chunk in ["Hello", " world"]:
                yield chunk

        with patch.object(provider, "_stream_chat", fake_stream):
            result = await provider.chat(messages, stream=True)
        assert hasattr(result, "__aiter__") or isinstance(result, types.AsyncGeneratorType)


# ---------------------------------------------------------------------------
# embed
# ---------------------------------------------------------------------------


class TestOllamaEmbed:
    @pytest.mark.asyncio
    async def test_embed_returns_vectors(self, provider: OllamaProvider) -> None:
        response_data = {"embeddings": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]}
        with patch.object(provider, "_post", new=AsyncMock(return_value=response_data)):
            result = await provider.embed(["text a", "text b"])
        assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]

    @pytest.mark.asyncio
    async def test_embed_raises_on_empty_response(self, provider: OllamaProvider) -> None:
        with patch.object(provider, "_post", new=AsyncMock(return_value={"embeddings": []})):
            with pytest.raises(ProviderError, match="no embeddings"):
                await provider.embed(["text"])

    @pytest.mark.asyncio
    async def test_embed_uses_default_model(self, provider: OllamaProvider) -> None:
        response_data = {"embeddings": [[0.1]]}
        mock_fn = AsyncMock(return_value=response_data)
        with patch.object(provider, "_post", new=mock_fn) as mock_post:
            await provider.embed(["text"], model=None)
        payload = mock_post.call_args[0][1]
        assert payload["model"] == "qwen2.5:7b"


# ---------------------------------------------------------------------------
# list_models
# ---------------------------------------------------------------------------


class TestOllamaListModels:
    @pytest.mark.asyncio
    async def test_list_models_parses_response(self, provider: OllamaProvider) -> None:
        response_data = {
            "models": [
                {
                    "name": "qwen2.5:7b",
                    "size": 4_000_000_000,
                    "details": {"quantization_level": "Q4_K_M", "family": "qwen"},
                },
                {
                    "name": "llama3:8b",
                    "size": 5_000_000_000,
                    "details": {"quantization_level": "Q5_K_M", "family": "llama"},
                },
            ]
        }
        with patch.object(provider, "_get", new=AsyncMock(return_value=response_data)):
            models = await provider.list_models()
        assert len(models) == 2
        assert models[0].name == "qwen2.5:7b"
        assert models[0].quantization == "Q4_K_M"
        assert models[0].family == "qwen"
        assert models[0].size_bytes == 4_000_000_000

    @pytest.mark.asyncio
    async def test_list_models_empty(self, provider: OllamaProvider) -> None:
        with patch.object(provider, "_get", new=AsyncMock(return_value={"models": []})):
            models = await provider.list_models()
        assert models == []

    @pytest.mark.asyncio
    async def test_list_models_missing_details(self, provider: OllamaProvider) -> None:
        response_data = {"models": [{"name": "simple:1b", "size": 1000}]}
        with patch.object(provider, "_get", new=AsyncMock(return_value=response_data)):
            models = await provider.list_models()
        assert models[0].quantization == ""
        assert models[0].family == ""


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


class TestOllamaHealthCheck:
    @pytest.mark.asyncio
    async def test_healthy_when_get_succeeds(self, provider: OllamaProvider) -> None:
        with patch.object(provider, "_get", new=AsyncMock(return_value={"models": []})):
            health = await provider.health_check()
        assert health.healthy is True
        assert health.latency_ms >= 0
        assert health.error is None

    @pytest.mark.asyncio
    async def test_unhealthy_when_get_raises(self, provider: OllamaProvider) -> None:
        err_mock = AsyncMock(side_effect=ProviderError("conn refused"))
        with patch.object(provider, "_get", new=err_mock):
            health = await provider.health_check()
        assert health.healthy is False
        assert "conn refused" in health.error

    @pytest.mark.asyncio
    async def test_timeout_returns_unhealthy(self, provider: OllamaProvider) -> None:
        with patch.object(
            provider, "_get", new=AsyncMock(side_effect=ProviderTimeoutError("timed out"))
        ):
            health = await provider.health_check()
        assert health.healthy is False


# ---------------------------------------------------------------------------
# _post error handling
# ---------------------------------------------------------------------------


class TestOllamaPostErrors:
    @pytest.mark.asyncio
    async def test_404_raises_model_not_found(self, provider: OllamaProvider) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 404
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(ModelNotFoundError):
                await provider._post("/api/chat", {"model": "missing:1b"})

    @pytest.mark.asyncio
    async def test_non_200_raises_provider_error(self, provider: OllamaProvider) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 500
        mock_resp.text = AsyncMock(return_value="Internal Server Error")
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(ProviderError, match="500"):
                await provider._post("/api/chat", {})
