"""Unit tests for the Google Gemini LLM provider."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BMT_PKG = _REPO_ROOT / "bmt-ai-os"
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_BMT_PKG))

from providers.base import (  # noqa: E402
    ChatMessage,
    ChatResponse,
    ModelNotFoundError,
    ProviderError,
    ProviderTimeoutError,
    TokenUsage,
)
from providers.gemini_provider import (  # noqa: E402
    GeminiProvider,
    _resolve_api_key,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


def _make_provider() -> GeminiProvider:
    return GeminiProvider(api_key="test-key-123")


def _mock_response(status: int = 200, json_data: dict | None = None, text: str = ""):
    """Create a mock aiohttp response."""
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data or {})
    resp.text = AsyncMock(return_value=text)
    return resp


def _patch_session_post(mock_resp):
    """Return a patch context that makes aiohttp.ClientSession().post() return mock_resp."""
    mock_session_cls = patch("aiohttp.ClientSession")

    class _Ctx:
        def __enter__(self):
            self._patcher = mock_session_cls
            mock_cls = self._patcher.__enter__()
            session_ctx = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=session_ctx)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            session_ctx.post = MagicMock(
                return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=mock_resp),
                    __aexit__=AsyncMock(return_value=False),
                )
            )
            self.session = session_ctx
            return self

        def __exit__(self, *args):
            self._patcher.__exit__(*args)

    return _Ctx()


def _patch_session_get(mock_resp):
    """Return a patch context that makes aiohttp.ClientSession().get() return mock_resp."""
    mock_session_cls = patch("aiohttp.ClientSession")

    class _Ctx:
        def __enter__(self):
            self._patcher = mock_session_cls
            mock_cls = self._patcher.__enter__()
            session_ctx = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=session_ctx)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            session_ctx.get = MagicMock(
                return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=mock_resp),
                    __aexit__=AsyncMock(return_value=False),
                )
            )
            self.session = session_ctx
            return self

        def __exit__(self, *args):
            self._patcher.__exit__(*args)

    return _Ctx()


# ---------------------------------------------------------------------------
# API key resolution
# ---------------------------------------------------------------------------


class TestApiKeyResolution:
    def test_explicit_key(self):
        assert _resolve_api_key("explicit") == "explicit"

    def test_env_var(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "from-env")
        assert _resolve_api_key(None) == "from-env"

    def test_secrets_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        secrets = tmp_path / "key"
        secrets.write_text("from-file\n")
        with patch("providers.gemini_provider._SECRETS_PATH", str(secrets)):
            assert _resolve_api_key(None) == "from-file"

    def test_no_key_returns_empty(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        with patch("providers.gemini_provider._SECRETS_PATH", "/nonexistent"):
            assert _resolve_api_key(None) == ""


# ---------------------------------------------------------------------------
# Constructor / properties
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_name(self):
        assert _make_provider().name == "gemini"

    def test_default_model(self):
        p = GeminiProvider(api_key="k")
        assert p._default_model == "gemini-2.0-flash"

    def test_custom_model(self):
        p = GeminiProvider(api_key="k", default_model="gemini-2.0-pro")
        assert p._default_model == "gemini-2.0-pro"

    def test_default_embed_model(self):
        p = GeminiProvider(api_key="k")
        assert p._default_embed_model == "text-embedding-004"

    def test_base_url_trailing_slash_stripped(self):
        p = GeminiProvider(api_key="k", base_url="https://example.com/v1/")
        assert p._base_url == "https://example.com/v1"

    def test_build_url(self):
        p = _make_provider()
        url = p.build_url("/models")
        assert url == "https://generativelanguage.googleapis.com/v1beta/models"

    def test_missing_key_raises(self):
        p = GeminiProvider(api_key="")
        with pytest.raises(ProviderError, match="API key not configured"):
            _run(p.chat([ChatMessage("user", "hi")]))


# ---------------------------------------------------------------------------
# Message conversion
# ---------------------------------------------------------------------------


class TestMessageConversion:
    def test_user_message(self):
        msgs = [ChatMessage("user", "Hello")]
        contents, sys_inst = GeminiProvider._convert_messages(msgs)
        assert len(contents) == 1
        assert contents[0]["role"] == "user"
        assert contents[0]["parts"] == [{"text": "Hello"}]
        assert sys_inst is None

    def test_assistant_becomes_model(self):
        msgs = [ChatMessage("assistant", "Hi there")]
        contents, _ = GeminiProvider._convert_messages(msgs)
        assert contents[0]["role"] == "model"

    def test_system_extracted(self):
        msgs = [
            ChatMessage("system", "You are helpful."),
            ChatMessage("user", "Hi"),
        ]
        contents, sys_inst = GeminiProvider._convert_messages(msgs)
        assert len(contents) == 1
        assert sys_inst == {"parts": [{"text": "You are helpful."}]}

    def test_multiple_system_messages(self):
        msgs = [
            ChatMessage("system", "Rule 1"),
            ChatMessage("system", "Rule 2"),
            ChatMessage("user", "Go"),
        ]
        contents, sys_inst = GeminiProvider._convert_messages(msgs)
        assert len(contents) == 1
        assert len(sys_inst["parts"]) == 2

    def test_conversation_order_preserved(self):
        msgs = [
            ChatMessage("user", "Q1"),
            ChatMessage("assistant", "A1"),
            ChatMessage("user", "Q2"),
        ]
        contents, _ = GeminiProvider._convert_messages(msgs)
        assert [c["role"] for c in contents] == ["user", "model", "user"]


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


class TestResponseHelpers:
    def test_extract_text(self):
        data = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Hello "}, {"text": "world"}],
                    },
                }
            ],
        }
        assert GeminiProvider._extract_text(data) == "Hello world"

    def test_extract_text_empty(self):
        assert GeminiProvider._extract_text({}) == ""
        assert GeminiProvider._extract_text({"candidates": []}) == ""

    def test_parse_usage(self):
        data = {
            "usageMetadata": {
                "promptTokenCount": 10,
                "candidatesTokenCount": 20,
                "totalTokenCount": 30,
            },
        }
        usage = GeminiProvider._parse_usage(data)
        assert usage == TokenUsage(10, 20, 30)

    def test_parse_usage_missing(self):
        usage = GeminiProvider._parse_usage({})
        assert usage == TokenUsage(0, 0, 0)


# ---------------------------------------------------------------------------
# Chat (mocked HTTP)
# ---------------------------------------------------------------------------


class TestChat:
    def test_chat_success(self):
        provider = _make_provider()
        json_data = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Hi there!"}]},
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 5,
                "candidatesTokenCount": 3,
                "totalTokenCount": 8,
            },
        }
        with _patch_session_post(_mock_response(json_data=json_data)):
            result = _run(provider.chat([ChatMessage("user", "Hello")]))

        assert isinstance(result, ChatResponse)
        assert result.content == "Hi there!"
        assert result.provider == "gemini"
        assert result.model == "gemini-2.0-flash"
        assert result.usage.prompt_tokens == 5
        assert result.usage.completion_tokens == 3
        assert result.usage.total_tokens == 8
        assert result.latency_ms > 0

    def test_chat_custom_model(self):
        provider = _make_provider()
        json_data = {
            "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
            "usageMetadata": {},
        }
        with _patch_session_post(_mock_response(json_data=json_data)):
            result = _run(
                provider.chat(
                    [ChatMessage("user", "Hello")],
                    model="gemini-2.0-pro",
                )
            )
        assert result.model == "gemini-2.0-pro"

    def test_chat_404_raises_model_not_found(self):
        provider = _make_provider()
        with _patch_session_post(_mock_response(status=404)):
            with pytest.raises(ModelNotFoundError):
                _run(provider.chat([ChatMessage("user", "Hello")]))

    def test_chat_500_raises_provider_error(self):
        provider = _make_provider()
        with _patch_session_post(_mock_response(status=500, text="Internal Server Error")):
            with pytest.raises(ProviderError, match="Gemini returned 500"):
                _run(provider.chat([ChatMessage("user", "Hello")]))


# ---------------------------------------------------------------------------
# Embed (mocked HTTP)
# ---------------------------------------------------------------------------


class TestEmbed:
    def test_embed_success(self):
        provider = _make_provider()
        json_data = {"embedding": {"values": [0.1, 0.2, 0.3]}}
        with _patch_session_post(_mock_response(json_data=json_data)):
            result = _run(provider.embed(["hello"]))
        assert len(result) == 1
        assert result[0] == [0.1, 0.2, 0.3]

    def test_embed_no_values_raises(self):
        provider = _make_provider()
        json_data = {"embedding": {}}
        with _patch_session_post(_mock_response(json_data=json_data)):
            with pytest.raises(ProviderError, match="no embedding"):
                _run(provider.embed(["hello"]))


# ---------------------------------------------------------------------------
# List models (mocked HTTP)
# ---------------------------------------------------------------------------


class TestListModels:
    def test_list_models(self):
        provider = _make_provider()
        json_data = {
            "models": [
                {"name": "models/gemini-2.0-flash", "displayName": "Gemini 2.0 Flash"},
                {"name": "models/gemini-2.0-pro", "displayName": "Gemini 2.0 Pro"},
            ],
        }
        with _patch_session_get(_mock_response(json_data=json_data)):
            models = _run(provider.list_models())

        assert len(models) == 2
        assert models[0].name == "gemini-2.0-flash"
        assert models[0].family == "Gemini 2.0 Flash"
        assert models[1].name == "gemini-2.0-pro"
        assert models[1].family == "Gemini 2.0 Pro"


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    def test_healthy(self):
        provider = _make_provider()
        with patch.object(provider, "list_models", new_callable=AsyncMock, return_value=[]):
            health = _run(provider.health_check())
        assert health.healthy is True
        assert health.error is None
        assert health.latency_ms >= 0

    def test_unhealthy(self):
        provider = _make_provider()
        with patch.object(
            provider,
            "list_models",
            new_callable=AsyncMock,
            side_effect=ProviderError("offline"),
        ):
            health = _run(provider.health_check())
        assert health.healthy is False
        assert "offline" in health.error


# ---------------------------------------------------------------------------
# Rate-limit retry
# ---------------------------------------------------------------------------


class TestRateLimitRetry:
    def test_429_retries_then_succeeds(self):
        """First call returns 429, second returns 200."""
        provider = _make_provider()
        resp_429 = _mock_response(status=429, text="rate limited")
        resp_200 = _mock_response(
            json_data={
                "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
                "usageMetadata": {},
            }
        )

        call_count = 0

        class FakePost:
            def __init__(self, *a, **kw):
                nonlocal call_count
                call_count += 1
                self._resp = resp_429 if call_count == 1 else resp_200

            async def __aenter__(self):
                return self._resp

            async def __aexit__(self, *a):
                pass

        with (
            patch("aiohttp.ClientSession") as mock_cls,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session_ctx = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=session_ctx)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            session_ctx.post = FakePost

            result = _run(provider.chat([ChatMessage("user", "hi")]))

        assert result.content == "ok"
        assert call_count == 2

    def test_429_exhausts_retries(self):
        """All attempts return 429 — should raise ProviderError."""
        provider = _make_provider()
        resp_429 = _mock_response(status=429, text="rate limited")

        class FakePost:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return resp_429

            async def __aexit__(self, *a):
                pass

        with (
            patch("aiohttp.ClientSession") as mock_cls,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            session_ctx = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=session_ctx)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            session_ctx.post = FakePost

            with pytest.raises(ProviderError, match="rate limited"):
                _run(provider.chat([ChatMessage("user", "hi")]))


# ---------------------------------------------------------------------------
# Connection errors
# ---------------------------------------------------------------------------


class TestConnectionErrors:
    def test_timeout_raises(self):
        provider = _make_provider()
        with patch("aiohttp.ClientSession") as mock_cls:
            session_ctx = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=session_ctx)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            session_ctx.post = MagicMock(side_effect=aiohttp.ServerTimeoutError())

            with pytest.raises(ProviderTimeoutError):
                _run(provider.chat([ChatMessage("user", "hi")]))

    def test_client_error_raises(self):
        provider = _make_provider()
        with patch("aiohttp.ClientSession") as mock_cls:
            session_ctx = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=session_ctx)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            session_ctx.post = MagicMock(
                side_effect=aiohttp.ClientConnectorError(
                    connection_key=MagicMock(), os_error=OSError("offline")
                )
            )

            with pytest.raises(ProviderError, match="connection error"):
                _run(provider.chat([ChatMessage("user", "hi")]))
