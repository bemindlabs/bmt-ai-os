"""Unit tests for the OpenAI-compatible provider."""

from __future__ import annotations

from unittest import mock

import aiohttp
import pytest

from bmt_ai_os.providers.base import ChatMessage, ChatResponse, EmbedResponse
from bmt_ai_os.providers.openai_provider import (
    OpenAICompatibleProvider,
    OpenAIProvider,
    _RequestLog,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Remove API key env vars to ensure clean test state."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture
def provider() -> OpenAIProvider:
    return OpenAIProvider(api_key="sk-test-key-123", max_retries=0)


# ---------------------------------------------------------------------------
# API key loading
# ---------------------------------------------------------------------------


class TestAPIKeyResolution:
    """Test that API keys are resolved from env, file, and explicit."""

    def test_explicit_key(self):
        p = OpenAIProvider(api_key="sk-explicit")
        assert p._api_key == "sk-explicit"

    def test_env_var_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
        p = OpenAIProvider()
        assert p._api_key == "sk-from-env"

    def test_secrets_file_key(self, tmp_path, monkeypatch):
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        key_file = secrets_dir / "OPENAI_API_KEY"
        key_file.write_text("sk-from-file\n")

        with mock.patch("bmt_ai_os.providers.config._SECRETS_DIR", secrets_dir):
            p = OpenAIProvider()
            assert p._api_key == "sk-from-file"

    def test_explicit_overrides_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
        p = OpenAIProvider(api_key="sk-explicit")
        assert p._api_key == "sk-explicit"

    def test_no_key_returns_none(self):
        p = OpenAIProvider()
        assert p._api_key is None


# ---------------------------------------------------------------------------
# Request formatting
# ---------------------------------------------------------------------------


class TestRequestFormatting:
    """Verify payloads match OpenAI API expectations."""

    def test_chat_payload_format(self, provider):
        messages = [
            ChatMessage(role="system", content="You are helpful."),
            ChatMessage(role="user", content="Hello"),
        ]
        # Build the payload the same way chat() does internally
        payload = {
            "model": provider.default_model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": 0.7,
            "max_tokens": 4096,
        }
        assert payload["model"] == "gpt-4o-mini"
        assert len(payload["messages"]) == 2
        assert payload["messages"][0]["role"] == "system"
        assert payload["messages"][1]["content"] == "Hello"

    def test_embed_payload_format(self, provider):
        payload = {
            "model": provider.default_embed_model,
            "input": ["Some text to embed"],
        }
        assert payload["model"] == "text-embedding-3-small"
        assert isinstance(payload["input"], list)

    def test_headers_include_bearer_token(self, provider):
        headers = provider._headers()
        assert headers["Authorization"] == "Bearer sk-test-key-123"
        assert headers["Content-Type"] == "application/json"

    def test_headers_no_auth_without_key(self):
        p = OpenAIProvider()
        headers = p._headers()
        assert "Authorization" not in headers

    def test_url_construction(self, provider):
        assert provider._url("/chat/completions") == ("https://api.openai.com/v1/chat/completions")
        assert provider._url("/models") == "https://api.openai.com/v1/models"


# ---------------------------------------------------------------------------
# Rate limit retry logic
# ---------------------------------------------------------------------------


class TestRateLimitRetry:
    """Test exponential backoff on 429 and 5xx."""

    @pytest.mark.asyncio
    async def test_retry_on_429(self):
        """Provider retries on 429 and succeeds on subsequent attempt."""
        p = OpenAIProvider(api_key="sk-test", max_retries=2)

        call_count = 0

        async def mock_request(method, url, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = mock.AsyncMock(spec=aiohttp.ClientResponse)
            if call_count < 3:
                resp.status = 429
                resp.headers = {"Retry-After": "0.01"}
                resp.release = mock.AsyncMock()
            else:
                resp.status = 200
                resp.json = mock.AsyncMock(return_value={"data": []})
            return resp

        session = mock.AsyncMock(spec=aiohttp.ClientSession)
        session.closed = False
        session.request = mock_request
        p._session = session

        resp = await p._request_with_retry("GET", "/models")
        assert resp.status == 200
        assert call_count == 3
        await p.close()

    @pytest.mark.asyncio
    async def test_all_retries_exhausted(self):
        """ConnectionError raised when all retries fail."""
        p = OpenAIProvider(api_key="sk-test", max_retries=1)

        async def mock_request(method, url, **kwargs):
            resp = mock.AsyncMock(spec=aiohttp.ClientResponse)
            resp.status = 500
            resp.headers = {}
            resp.release = mock.AsyncMock()
            return resp

        session = mock.AsyncMock(spec=aiohttp.ClientSession)
        session.closed = False
        session.request = mock_request
        p._session = session
        p.retry_base_delay = 0.01

        with pytest.raises(ConnectionError, match="all 2 attempts failed"):
            await p._request_with_retry("GET", "/models")
        await p.close()

    @pytest.mark.asyncio
    async def test_retry_on_connection_error(self):
        """Provider retries on aiohttp.ClientError."""
        p = OpenAIProvider(api_key="sk-test", max_retries=1)
        p.retry_base_delay = 0.01

        call_count = 0

        async def mock_request(method, url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise aiohttp.ClientError("connection refused")
            resp = mock.AsyncMock(spec=aiohttp.ClientResponse)
            resp.status = 200
            resp.json = mock.AsyncMock(return_value={"data": []})
            return resp

        session = mock.AsyncMock(spec=aiohttp.ClientSession)
        session.closed = False
        session.request = mock_request
        p._session = session

        resp = await p._request_with_retry("GET", "/models")
        assert resp.status == 200
        assert call_count == 2
        await p.close()


# ---------------------------------------------------------------------------
# Cost tracking
# ---------------------------------------------------------------------------


class TestCostTracking:
    """Test per-request cost estimation and logging."""

    def test_cost_estimation_known_model(self, provider):
        # gpt-4o-mini: $0.15/M input, $0.60/M output
        cost = provider._estimate_cost("gpt-4o-mini", 1000, 500)
        expected = (1000 * 0.15 + 500 * 0.60) / 1_000_000
        assert abs(cost - expected) < 1e-10

    def test_cost_estimation_unknown_model(self, provider):
        cost = provider._estimate_cost("unknown-model", 1000, 500)
        assert cost == 0.0

    def test_request_logging(self, provider):
        provider._log_request("gpt-4o-mini", 100, 50, 150.0)
        assert len(provider.request_log) == 1
        entry = provider.request_log[0]
        assert entry.model == "gpt-4o-mini"
        assert entry.input_tokens == 100
        assert entry.output_tokens == 50
        assert entry.latency_ms == 150.0
        assert entry.estimated_cost_usd > 0

    def test_total_cost_accumulates(self, provider):
        provider._log_request("gpt-4o-mini", 1_000_000, 0, 100.0)
        provider._log_request("gpt-4o-mini", 0, 1_000_000, 100.0)
        total = provider.total_cost()
        expected = 0.15 + 0.60  # $0.15/M input + $0.60/M output
        assert abs(total - expected) < 1e-6

    def test_request_log_as_dict(self):
        entry = _RequestLog(
            model="gpt-4o",
            input_tokens=500,
            output_tokens=200,
            latency_ms=123.456,
            estimated_cost_usd=0.003250,
        )
        d = entry.as_dict()
        assert d["model"] == "gpt-4o"
        assert d["latency_ms"] == 123.5
        assert d["estimated_cost_usd"] == 0.00325


# ---------------------------------------------------------------------------
# Streaming response parsing
# ---------------------------------------------------------------------------


class TestStreamingParsing:
    """Test SSE stream parsing for chat completions."""

    @pytest.mark.asyncio
    async def test_stream_chat_parses_sse(self):
        """Verify _iter_sse yields content deltas from SSE lines."""
        p = OpenAIProvider(api_key="sk-test", max_retries=0)

        # Build a mock response with SSE content
        chunks = [
            b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n',
            b'data: {"choices":[{"delta":{"content":" world"}}]}\n\n',
            b"data: [DONE]\n\n",
        ]

        resp = mock.AsyncMock(spec=aiohttp.ClientResponse)
        resp.content = _async_iter(chunks)

        collected: list[str] = []
        async for token in p._iter_sse(resp, "gpt-4o-mini", p._now_ms()):
            collected.append(token)

        assert collected == ["Hello", " world"]
        await p.close()

    @pytest.mark.asyncio
    async def test_stream_ignores_empty_lines(self):
        p = OpenAIProvider(api_key="sk-test", max_retries=0)

        chunks = [
            b"\n",
            b": keep-alive\n",
            b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n',
            b"data: [DONE]\n\n",
        ]

        resp = mock.AsyncMock(spec=aiohttp.ClientResponse)
        resp.content = _async_iter(chunks)

        collected: list[str] = []
        async for token in p._iter_sse(resp, "gpt-4o-mini", p._now_ms()):
            collected.append(token)

        assert collected == ["ok"]
        await p.close()


# ---------------------------------------------------------------------------
# Non-stream chat and embed
# ---------------------------------------------------------------------------


class TestChatAndEmbed:
    """Integration-style tests using mocked HTTP responses."""

    @pytest.mark.asyncio
    async def test_chat_returns_response(self):
        p = OpenAIProvider(api_key="sk-test", max_retries=0)

        api_response = {
            "id": "chatcmpl-abc",
            "model": "gpt-4o-mini",
            "choices": [{"message": {"role": "assistant", "content": "Hi there!"}, "index": 0}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

        async def mock_request(method, url, **kwargs):
            resp = mock.AsyncMock(spec=aiohttp.ClientResponse)
            resp.status = 200
            resp.json = mock.AsyncMock(return_value=api_response)
            return resp

        session = mock.AsyncMock(spec=aiohttp.ClientSession)
        session.closed = False
        session.request = mock_request
        p._session = session

        result = await p.chat([ChatMessage(role="user", content="Hello")])
        assert isinstance(result, ChatResponse)
        assert result.content == "Hi there!"
        assert result.input_tokens == 10
        assert result.output_tokens == 5
        assert result.model == "gpt-4o-mini"
        assert len(p.request_log) == 1
        await p.close()

    @pytest.mark.asyncio
    async def test_embed_returns_single(self):
        p = OpenAIProvider(api_key="sk-test", max_retries=0)

        api_response = {
            "model": "text-embedding-3-small",
            "data": [{"embedding": [0.1, 0.2, 0.3], "index": 0}],
            "usage": {"prompt_tokens": 5, "total_tokens": 5},
        }

        async def mock_request(method, url, **kwargs):
            resp = mock.AsyncMock(spec=aiohttp.ClientResponse)
            resp.status = 200
            resp.json = mock.AsyncMock(return_value=api_response)
            return resp

        session = mock.AsyncMock(spec=aiohttp.ClientSession)
        session.closed = False
        session.request = mock_request
        p._session = session

        result = await p.embed("hello world")
        assert isinstance(result, EmbedResponse)
        assert result.embedding == [0.1, 0.2, 0.3]
        assert result.input_tokens == 5
        await p.close()

    @pytest.mark.asyncio
    async def test_embed_returns_list_for_multiple(self):
        p = OpenAIProvider(api_key="sk-test", max_retries=0)

        api_response = {
            "model": "text-embedding-3-small",
            "data": [
                {"embedding": [0.1], "index": 0},
                {"embedding": [0.2], "index": 1},
            ],
            "usage": {"prompt_tokens": 10, "total_tokens": 10},
        }

        async def mock_request(method, url, **kwargs):
            resp = mock.AsyncMock(spec=aiohttp.ClientResponse)
            resp.status = 200
            resp.json = mock.AsyncMock(return_value=api_response)
            return resp

        session = mock.AsyncMock(spec=aiohttp.ClientSession)
        session.closed = False
        session.request = mock_request
        p._session = session

        result = await p.embed(["hello", "world"])
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0].embedding == [0.1]
        assert result[1].embedding == [0.2]
        await p.close()


# ---------------------------------------------------------------------------
# Health check and list_models
# ---------------------------------------------------------------------------


class TestHealthAndModels:
    @pytest.mark.asyncio
    async def test_health_check_true(self):
        p = OpenAIProvider(api_key="sk-test", max_retries=0)

        async def mock_request(method, url, **kwargs):
            resp = mock.AsyncMock(spec=aiohttp.ClientResponse)
            resp.status = 200
            resp.release = mock.AsyncMock()
            return resp

        session = mock.AsyncMock(spec=aiohttp.ClientSession)
        session.closed = False
        session.request = mock_request
        p._session = session

        assert await p.health_check() is True
        await p.close()

    @pytest.mark.asyncio
    async def test_health_check_false_on_error(self):
        p = OpenAIProvider(api_key="sk-test", max_retries=0)

        async def mock_request(method, url, **kwargs):
            raise aiohttp.ClientError("offline")

        session = mock.AsyncMock(spec=aiohttp.ClientSession)
        session.closed = False
        session.request = mock_request
        p._session = session

        assert await p.health_check() is False
        await p.close()


# ---------------------------------------------------------------------------
# Subclassing contract
# ---------------------------------------------------------------------------


class TestSubclassing:
    """Verify OpenAICompatibleProvider is easily subclassable."""

    def test_minimal_subclass(self):
        class GroqProvider(OpenAICompatibleProvider):
            name = "groq"
            base_url = "https://api.groq.com/openai/v1"
            default_model = "llama-3.3-70b-versatile"
            api_key_env_var = "GROQ_API_KEY"

        p = GroqProvider(api_key="gsk-test")
        assert p.name == "groq"
        assert p.base_url == "https://api.groq.com/openai/v1"
        assert p._url("/chat/completions") == ("https://api.groq.com/openai/v1/chat/completions")
        assert p._api_key == "gsk-test"

    def test_provider_defaults(self):
        p = OpenAIProvider(api_key="sk-test")
        assert p.name == "openai"
        assert p.default_model == "gpt-4o-mini"
        assert p.default_embed_model == "text-embedding-3-small"
        assert "gpt-4o-mini" in p.pricing


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _async_iter:
    """Turn a list of bytes into an async iterable (for resp.content)."""

    def __init__(self, items: list[bytes]):
        self._items = items
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        if self._index >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._index]
        self._index += 1
        return item
