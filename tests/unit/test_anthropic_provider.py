"""Unit tests for the Anthropic Claude provider."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BMT_PKG = _REPO_ROOT / "bmt-ai-os"
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_BMT_PKG))

from providers.anthropic_provider import (  # noqa: E402
    _CLAUDE_MODELS,
    AnthropicProvider,
    RateLimitError,
)
from providers.base import (  # noqa: E402
    ChatMessage,
    ProviderError,
    TokenUsage,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def provider():
    """Create a provider with a dummy API key."""
    return AnthropicProvider(api_key="sk-ant-test-key")


@pytest.fixture
def sample_messages():
    return [
        ChatMessage(role="system", content="You are a helpful assistant."),
        ChatMessage(role="user", content="Hello"),
        ChatMessage(role="assistant", content="Hi there!"),
        ChatMessage(role="user", content="How are you?"),
    ]


# ---------------------------------------------------------------------------
# Provider basics
# ---------------------------------------------------------------------------


class TestProviderBasics:
    def test_name(self, provider):
        assert provider.name == "anthropic"

    def test_default_model(self, provider):
        assert provider._default_model == "claude-sonnet-4-20250514"

    def test_custom_model(self):
        p = AnthropicProvider(api_key="key", default_model="claude-opus-4-20250514")
        assert p._default_model == "claude-opus-4-20250514"

    def test_build_url(self, provider):
        assert provider.build_url("/v1/messages") == "https://api.anthropic.com/v1/messages"

    def test_custom_base_url(self):
        p = AnthropicProvider(api_key="key", base_url="https://custom.api.com/")
        assert p.build_url("/v1/messages") == "https://custom.api.com/v1/messages"


# ---------------------------------------------------------------------------
# Message format conversion
# ---------------------------------------------------------------------------


class TestMessageConversion:
    def test_system_prompt_extracted(self, sample_messages):
        system, api_msgs = AnthropicProvider._convert_messages(sample_messages)
        assert system == "You are a helpful assistant."
        assert all(m["role"] != "system" for m in api_msgs)

    def test_multiple_system_prompts_joined(self):
        messages = [
            ChatMessage(role="system", content="First rule."),
            ChatMessage(role="system", content="Second rule."),
            ChatMessage(role="user", content="Hi"),
        ]
        system, api_msgs = AnthropicProvider._convert_messages(messages)
        assert system == "First rule.\n\nSecond rule."
        assert len(api_msgs) == 1

    def test_no_system_prompt(self):
        messages = [ChatMessage(role="user", content="Hi")]
        system, api_msgs = AnthropicProvider._convert_messages(messages)
        assert system == ""
        assert api_msgs == [{"role": "user", "content": "Hi"}]

    def test_message_order_preserved(self, sample_messages):
        _, api_msgs = AnthropicProvider._convert_messages(sample_messages)
        assert len(api_msgs) == 3
        assert api_msgs[0]["role"] == "user"
        assert api_msgs[1]["role"] == "assistant"
        assert api_msgs[2]["role"] == "user"


# ---------------------------------------------------------------------------
# API key loading
# ---------------------------------------------------------------------------


class TestAPIKeyLoading:
    def test_explicit_key(self):
        p = AnthropicProvider(api_key="explicit-key")
        assert p._api_key == "explicit-key"

    def test_env_var_key(self):
        os.environ["ANTHROPIC_API_KEY"] = "env-key"
        try:
            p = AnthropicProvider()
            assert p._api_key == "env-key"
        finally:
            del os.environ["ANTHROPIC_API_KEY"]

    def test_secrets_file_key(self, tmp_path):
        secrets_file = tmp_path / "ANTHROPIC_API_KEY"
        secrets_file.write_text("  file-key  \n")
        with patch("providers.anthropic_provider._SECRETS_PATH", str(secrets_file)):
            # Clear env var so it falls through to file.
            os.environ.pop("ANTHROPIC_API_KEY", None)
            p = AnthropicProvider()
            assert p._api_key == "file-key"

    def test_no_key_available(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        with patch("providers.anthropic_provider._SECRETS_PATH", "/nonexistent/path"):
            p = AnthropicProvider()
            assert p._api_key == ""

    def test_explicit_key_overrides_env(self):
        os.environ["ANTHROPIC_API_KEY"] = "env-key"
        try:
            p = AnthropicProvider(api_key="explicit-key")
            assert p._api_key == "explicit-key"
        finally:
            del os.environ["ANTHROPIC_API_KEY"]


# ---------------------------------------------------------------------------
# Embed raises error
# ---------------------------------------------------------------------------


class TestEmbed:
    def test_embed_raises_provider_error(self, provider):
        with pytest.raises(ProviderError, match="does not offer embeddings"):
            asyncio.run(provider.embed(["test text"]))


# ---------------------------------------------------------------------------
# List models
# ---------------------------------------------------------------------------


class TestListModels:
    def test_returns_hardcoded_models(self, provider):
        models = asyncio.run(provider.list_models())
        assert len(models) == len(_CLAUDE_MODELS)
        names = {m.name for m in models}
        assert "claude-sonnet-4-20250514" in names
        assert "claude-opus-4-20250514" in names
        assert "claude-haiku-3.5-20241022" in names

    def test_returns_copy(self, provider):
        models1 = asyncio.run(provider.list_models())
        models2 = asyncio.run(provider.list_models())
        assert models1 is not models2


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


class TestResponseParsing:
    def test_extract_text_single_block(self):
        data = {"content": [{"type": "text", "text": "Hello world"}]}
        assert AnthropicProvider._extract_text(data) == "Hello world"

    def test_extract_text_multiple_blocks(self):
        data = {
            "content": [
                {"type": "text", "text": "Hello "},
                {"type": "tool_use", "id": "t1"},
                {"type": "text", "text": "world"},
            ]
        }
        assert AnthropicProvider._extract_text(data) == "Hello world"

    def test_extract_text_empty(self):
        assert AnthropicProvider._extract_text({"content": []}) == ""
        assert AnthropicProvider._extract_text({}) == ""

    def test_parse_usage(self):
        data = {"usage": {"input_tokens": 100, "output_tokens": 50}}
        usage = AnthropicProvider._parse_usage(data)
        assert usage.prompt_tokens == 100
        assert usage.completion_tokens == 50
        assert usage.total_tokens == 150

    def test_parse_usage_missing(self):
        usage = AnthropicProvider._parse_usage({})
        assert usage.total_tokens == 0


# ---------------------------------------------------------------------------
# Streaming event parsing
# ---------------------------------------------------------------------------


class TestStreamingParsing:
    def test_stream_yields_content_block_delta(self, provider):
        """Simulate SSE lines and verify only content_block_delta text is yielded."""
        sse_lines = [
            b"event: message_start\n",
            b'data: {"type":"message_start","message":{"id":"msg_1"}}\n',
            b"\n",
            b"event: content_block_delta\n",
            b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello"}}\n',
            b"\n",
            b"event: content_block_delta\n",
            b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":" world"}}\n',
            b"\n",
            b"event: message_stop\n",
            b'data: {"type":"message_stop"}\n',
            b"\n",
        ]

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.content = _async_iter(sse_lines)

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_session_ctx)

        mock_client_ctx = AsyncMock()
        mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

        async def _run():
            with patch("aiohttp.ClientSession", return_value=mock_client_ctx):
                payload = {
                    "model": "claude-sonnet-4-20250514",
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 100,
                    "stream": True,
                }
                chunks = []
                async for chunk in provider._stream_chat(payload, "claude-sonnet-4-20250514"):
                    chunks.append(chunk)
            return chunks

        assert asyncio.run(_run()) == ["Hello", " world"]

    def test_stream_handles_done_signal(self, provider):
        """Stream should stop on [DONE] signal."""
        sse_lines = [
            b'data: {"type":"content_block_delta","delta":{"text":"Hi"}}\n',
            b"data: [DONE]\n",
            b'data: {"type":"content_block_delta","delta":{"text":"ignored"}}\n',
        ]

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.content = _async_iter(sse_lines)

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_session_ctx)

        mock_client_ctx = AsyncMock()
        mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

        async def _run():
            with patch("aiohttp.ClientSession", return_value=mock_client_ctx):
                payload = {"model": "m", "messages": [], "max_tokens": 1, "stream": True}
                chunks = []
                async for chunk in provider._stream_chat(payload, "m"):
                    chunks.append(chunk)
            return chunks

        assert asyncio.run(_run()) == ["Hi"]


# ---------------------------------------------------------------------------
# Rate limit handling
# ---------------------------------------------------------------------------


class TestRateLimitHandling:
    def test_rate_limit_error_attributes(self):
        err = RateLimitError("rate limited", retry_after=5.0)
        assert err.retry_after == 5.0
        assert "rate limited" in str(err)

    def test_rate_limit_is_provider_error(self):
        assert issubclass(RateLimitError, ProviderError)

    def test_parse_retry_after_header(self):
        mock_resp = MagicMock()
        mock_resp.headers = {"retry-after": "3.5"}
        assert AnthropicProvider._parse_retry_after(mock_resp) == 3.5

    def test_parse_retry_after_missing(self):
        mock_resp = MagicMock()
        mock_resp.headers = {}
        assert AnthropicProvider._parse_retry_after(mock_resp) is None

    def test_parse_retry_after_invalid(self):
        mock_resp = MagicMock()
        mock_resp.headers = {"retry-after": "not-a-number"}
        assert AnthropicProvider._parse_retry_after(mock_resp) is None


# ---------------------------------------------------------------------------
# Cost logging
# ---------------------------------------------------------------------------


class TestCostLogging:
    def test_log_cost_known_model(self, caplog):
        import logging

        with caplog.at_level(logging.INFO, logger="providers.anthropic_provider"):
            usage = TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
            AnthropicProvider._log_cost("claude-sonnet-4-20250514", usage)
        assert "$" in caplog.text or "est." in caplog.text

    def test_log_cost_unknown_model(self, caplog):
        import logging

        with caplog.at_level(logging.DEBUG, logger="providers.anthropic_provider"):
            usage = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
            AnthropicProvider._log_cost("unknown-model", usage)
        assert "no cost data" in caplog.text


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------


class TestHeaders:
    def test_headers_include_required_fields(self, provider):
        headers = provider._headers()
        assert headers["x-api-key"] == "sk-ant-test-key"
        assert headers["anthropic-version"] == "2023-06-01"
        assert headers["content-type"] == "application/json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _aiter_from_list(items):
    for item in items:
        yield item


def _async_iter(items):
    """Create an async iterable from a list (for mocking resp.content)."""
    return _aiter_from_list(items)
