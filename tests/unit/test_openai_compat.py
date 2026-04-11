"""Unit tests for OpenAI-compatible API endpoints.

Validates that the endpoints return correctly structured responses
matching the OpenAI API format expected by Cursor, Copilot, and Cody.

Also covers BMTOS-86: tool_use / function-calling support.
"""

from __future__ import annotations

import json
import unittest.mock
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fake provider for testing
# ---------------------------------------------------------------------------


class _FakeChatResponse:
    def __init__(self, content: str = "Hello!", model: str = "qwen2.5-coder:7b"):
        self.content = content
        self.model = model
        self.input_tokens = 10
        self.output_tokens = 5


class _FakeEmbedResponse:
    def __init__(self):
        self.embedding = [0.1, 0.2, 0.3]
        self.model = "nomic-embed"
        self.input_tokens = 4


class _FakeProvider:
    name = "fake"

    async def chat(self, messages, *, model=None, temperature=0.7, max_tokens=4096, stream=False):
        if stream:

            async def _gen():
                for chunk in ["Hel", "lo", "!"]:
                    yield chunk

            return _gen()
        return _FakeChatResponse()

    async def embed(self, texts, *, model=None):
        return [_FakeEmbedResponse() for _ in (texts if isinstance(texts, list) else [texts])]

    async def list_models(self):
        return [{"name": "qwen2.5-coder:7b"}, {"name": "nomic-embed"}]


class _FakeRegistry:
    def get_active(self):
        return _FakeProvider()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app():
    """Create a FastAPI app with the openai-compat router wired up."""
    from controller.openai_compat import router

    test_app = FastAPI()
    test_app.include_router(router)
    return test_app


@pytest.fixture()
def client(app):
    with patch(
        "controller.openai_compat._get_provider_router",
        return_value=_FakeRegistry(),
    ):
        yield TestClient(app)


# ---------------------------------------------------------------------------
# /v1/chat/completions
# ---------------------------------------------------------------------------


class TestChatCompletions:
    def test_basic_chat(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "qwen2.5-coder:7b",
                "messages": [{"role": "user", "content": "Say hi"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["object"] == "chat.completion"
        assert data["id"].startswith("chatcmpl-")
        assert len(data["choices"]) == 1
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert data["choices"][0]["message"]["content"] == "Hello!"
        assert data["choices"][0]["finish_reason"] == "stop"
        assert "usage" in data
        assert data["usage"]["prompt_tokens"] == 10
        assert data["usage"]["completion_tokens"] == 5
        assert data["usage"]["total_tokens"] == 15

    def test_streaming_chat(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "qwen2.5-coder:7b",
                "messages": [{"role": "user", "content": "Say hi"}],
                "stream": True,
            },
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        lines = [line for line in resp.text.strip().split("\n") if line.startswith("data: ")]
        assert len(lines) >= 3  # initial + chunks + done

        # Last line is [DONE]
        assert lines[-1] == "data: [DONE]"

        # Check second-to-last is the finish chunk
        final = json.loads(lines[-2].removeprefix("data: "))
        assert final["choices"][0]["finish_reason"] == "stop"

        # Check a content chunk
        first_content = json.loads(lines[1].removeprefix("data: "))
        assert first_content["object"] == "chat.completion.chunk"
        assert "content" in first_content["choices"][0]["delta"]

    def test_missing_messages_returns_422(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test",
            },
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /v1/completions
# ---------------------------------------------------------------------------


class TestCompletions:
    def test_basic_completion(self, client):
        resp = client.post(
            "/v1/completions",
            json={
                "model": "qwen2.5-coder:7b",
                "prompt": "def hello():",
                "max_tokens": 100,
            },
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["object"] == "text_completion"
        assert data["id"].startswith("cmpl-")
        assert len(data["choices"]) == 1
        assert "text" in data["choices"][0]
        assert data["choices"][0]["finish_reason"] == "stop"

    def test_prompt_as_list(self, client):
        resp = client.post(
            "/v1/completions",
            json={
                "prompt": ["line1", "line2"],
            },
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /v1/embeddings
# ---------------------------------------------------------------------------


class TestEmbeddings:
    def test_single_embedding(self, client):
        resp = client.post(
            "/v1/embeddings",
            json={
                "input": "hello world",
                "model": "nomic-embed",
            },
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["object"] == "list"
        assert len(data["data"]) == 1
        assert data["data"][0]["object"] == "embedding"
        assert isinstance(data["data"][0]["embedding"], list)
        assert data["data"][0]["index"] == 0
        assert "usage" in data

    def test_batch_embedding(self, client):
        resp = client.post(
            "/v1/embeddings",
            json={
                "input": ["hello", "world"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data"]) == 2
        assert data["data"][1]["index"] == 1


# ---------------------------------------------------------------------------
# /v1/models
# ---------------------------------------------------------------------------


class TestListModels:
    def test_list_models(self, client):
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json()

        assert data["object"] == "list"
        assert len(data["data"]) == 2
        assert data["data"][0]["object"] == "model"
        assert data["data"][0]["id"] == "qwen2.5-coder:7b"
        assert data["data"][0]["owned_by"] == "bmt_ai_os"


# ---------------------------------------------------------------------------
# Service unavailable
# ---------------------------------------------------------------------------


class TestServiceUnavailable:
    def test_no_provider_returns_503(self, app):
        with patch(
            "controller.openai_compat._get_provider_router",
            return_value=None,
        ):
            c = TestClient(app)
            resp = c.post(
                "/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
            assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Middleware tests
# ---------------------------------------------------------------------------


class TestAPIKeyMiddleware:
    def test_no_key_configured_passes(self):
        """When BMT_API_KEY is unset, all requests pass through."""
        from controller.middleware import APIKeyMiddleware

        inner_app = FastAPI()

        @inner_app.get("/v1/models")
        async def models():
            return {"ok": True}

        inner_app.add_middleware(APIKeyMiddleware, api_key=None)
        c = TestClient(inner_app)
        resp = c.get("/v1/models")
        assert resp.status_code == 200

    def test_valid_key_passes(self):
        from controller.middleware import APIKeyMiddleware

        inner_app = FastAPI()

        @inner_app.get("/v1/models")
        async def models():
            return {"ok": True}

        inner_app.add_middleware(APIKeyMiddleware, api_key="secret123")
        c = TestClient(inner_app)
        resp = c.get("/v1/models", headers={"Authorization": "Bearer secret123"})
        assert resp.status_code == 200

    def test_invalid_key_rejected(self):
        from controller.middleware import APIKeyMiddleware

        inner_app = FastAPI()

        @inner_app.get("/v1/models")
        async def models():
            return {"ok": True}

        inner_app.add_middleware(APIKeyMiddleware, api_key="secret123")
        c = TestClient(inner_app)
        resp = c.get("/v1/models", headers={"Authorization": "Bearer wrong"})
        assert resp.status_code == 401
        assert "invalid_api_key" in resp.json()["error"]["code"]

    def test_healthz_exempt(self):
        from controller.middleware import APIKeyMiddleware

        inner_app = FastAPI()

        @inner_app.get("/healthz")
        async def healthz():
            return {"status": "ok"}

        inner_app.add_middleware(APIKeyMiddleware, api_key="secret123")
        c = TestClient(inner_app)
        resp = c.get("/healthz")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# RAG auto-injection (BMTOS-71)
# ---------------------------------------------------------------------------


class TestRagInjection:
    """Tests for _rag_enabled() and _inject_rag_context()."""

    def test_rag_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("BMT_RAG_ENABLED", raising=False)
        from bmt_ai_os.controller.openai_compat import _rag_enabled

        assert _rag_enabled() is False

    def test_rag_enabled_via_env_true(self, monkeypatch):
        monkeypatch.setenv("BMT_RAG_ENABLED", "true")
        from bmt_ai_os.controller.openai_compat import _rag_enabled

        assert _rag_enabled() is True

    def test_rag_enabled_via_env_1(self, monkeypatch):
        monkeypatch.setenv("BMT_RAG_ENABLED", "1")
        from bmt_ai_os.controller.openai_compat import _rag_enabled

        assert _rag_enabled() is True

    def test_rag_enabled_via_env_yes(self, monkeypatch):
        monkeypatch.setenv("BMT_RAG_ENABLED", "yes")
        from bmt_ai_os.controller.openai_compat import _rag_enabled

        assert _rag_enabled() is True

    def test_rag_disabled_via_env_false(self, monkeypatch):
        monkeypatch.setenv("BMT_RAG_ENABLED", "false")
        from bmt_ai_os.controller.openai_compat import _rag_enabled

        assert _rag_enabled() is False

    @pytest.mark.asyncio
    async def test_inject_rag_context_returns_original_on_storage_error(self):
        """When ChromaDB is unavailable, messages are returned unchanged."""
        from bmt_ai_os.controller.openai_compat import _inject_rag_context

        class _Msg:
            def __init__(self, role, content):
                self.role = role
                self.content = content

        original = [_Msg("user", "What is RAG?")]

        # Patch at source so lazy import inside _inject_rag_context is intercepted
        with patch(
            "bmt_ai_os.rag.storage.ChromaStorage",
            side_effect=Exception("connection refused"),
        ):
            result = await _inject_rag_context(original)

        assert result is original

    @pytest.mark.asyncio
    async def test_inject_rag_context_prepends_system_message(self):
        """When RAG returns results, a system message is prepended."""
        from bmt_ai_os.controller.openai_compat import _inject_rag_context

        class _Msg:
            def __init__(self, role, content):
                self.role = role
                self.content = content

        original = [_Msg("user", "Explain vector search")]

        fake_raw = {"documents": [["Vector search uses embeddings."]]}
        mock_storage = unittest.mock.MagicMock()
        mock_storage.query.return_value = fake_raw

        # Patch ChromaStorage at its source module
        with patch("bmt_ai_os.rag.storage.ChromaStorage", return_value=mock_storage):
            result = await _inject_rag_context(original)

        assert len(result) == 2
        assert result[0].role == "system"
        assert "Vector search uses embeddings" in result[0].content
        assert result[1] is original[0]

    @pytest.mark.asyncio
    async def test_inject_rag_context_no_user_message_unchanged(self):
        """When there's no user message, the list is returned unchanged."""
        from bmt_ai_os.controller.openai_compat import _inject_rag_context

        class _Msg:
            def __init__(self, role, content):
                self.role = role
                self.content = content

        original = [_Msg("system", "You are a helpful assistant.")]
        result = await _inject_rag_context(original)
        assert result is original

    @pytest.mark.asyncio
    async def test_inject_rag_context_empty_documents_unchanged(self):
        """When ChromaDB returns no documents, original messages are returned."""
        from bmt_ai_os.controller.openai_compat import _inject_rag_context

        class _Msg:
            def __init__(self, role, content):
                self.role = role
                self.content = content

        original = [_Msg("user", "anything")]
        mock_storage = unittest.mock.MagicMock()
        mock_storage.query.return_value = {"documents": [[]]}

        with patch("bmt_ai_os.rag.storage.ChromaStorage", return_value=mock_storage):
            result = await _inject_rag_context(original)

        assert result is original

    def test_chat_completions_with_rag_enabled_still_returns_200(self, app, monkeypatch):
        """RAG path is exercised but storage failure is non-breaking."""
        monkeypatch.setenv("BMT_RAG_ENABLED", "true")

        with (
            patch(
                "controller.openai_compat._get_provider_router",
                return_value=_FakeRegistry(),
            ),
            patch(
                "bmt_ai_os.rag.storage.ChromaStorage",
                side_effect=Exception("no chroma"),
            ),
        ):
            c = TestClient(app)
            resp = c.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "hi"}]},
            )

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# BMTOS-86: Tool / function-calling tests
# ---------------------------------------------------------------------------

SAMPLE_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the weather for a city",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "unit": {"type": "string"},
            },
            "required": ["city"],
        },
    },
}


def _make_tool_provider(*, supports_tools: bool = False, tool_calls_in_raw: list | None = None):
    """Return a mock LLMProvider with configurable tool support."""
    provider = MagicMock()
    provider.name = "mock-provider"
    provider.supports_tools = supports_tools

    raw: dict[str, Any] = {}
    if tool_calls_in_raw:
        raw["tool_calls"] = tool_calls_in_raw

    chat_response = MagicMock()
    chat_response.content = "some text"
    chat_response.model = "mock-model"
    chat_response.input_tokens = 10
    chat_response.output_tokens = 5
    chat_response.raw = raw
    chat_response.tool_calls = tool_calls_in_raw

    provider.chat = AsyncMock(return_value=chat_response)
    return provider


def _make_tool_registry(provider):
    registry = MagicMock()
    registry.get_active.return_value = provider
    return registry


class TestChatCompletionRequestModelTools:
    """Pydantic model accepts tools / tool_choice fields."""

    def test_basic_request_no_tools(self):
        from bmt_ai_os.controller.openai_compat import ChatCompletionRequest

        req = ChatCompletionRequest(messages=[{"role": "user", "content": "Hello"}])
        assert req.tools is None
        assert req.tool_choice is None

    def test_request_with_tools_list(self):
        from bmt_ai_os.controller.openai_compat import ChatCompletionRequest

        req = ChatCompletionRequest(
            messages=[{"role": "user", "content": "Weather?"}],
            tools=[SAMPLE_TOOL],
        )
        assert req.tools is not None
        assert len(req.tools) == 1
        assert req.tools[0].function.name == "get_weather"

    def test_request_with_tool_choice_string(self):
        from bmt_ai_os.controller.openai_compat import ChatCompletionRequest

        req = ChatCompletionRequest(
            messages=[{"role": "user", "content": "Hi"}],
            tools=[SAMPLE_TOOL],
            tool_choice="auto",
        )
        assert req.tool_choice == "auto"

    def test_request_with_tool_choice_dict(self):
        from bmt_ai_os.controller.openai_compat import ChatCompletionRequest

        req = ChatCompletionRequest(
            messages=[{"role": "user", "content": "Hi"}],
            tools=[SAMPLE_TOOL],
            tool_choice={"type": "function", "function": {"name": "get_weather"}},
        )
        assert isinstance(req.tool_choice, dict)

    def test_multiple_tools_accepted(self):
        from bmt_ai_os.controller.openai_compat import ChatCompletionRequest

        tool2 = {
            "type": "function",
            "function": {
                "name": "search",
                "description": "Search the web",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }
        req = ChatCompletionRequest(
            messages=[{"role": "user", "content": "Both"}],
            tools=[SAMPLE_TOOL, tool2],
        )
        assert len(req.tools) == 2


class TestProviderSupportsToolsHelper:
    def test_false_when_attr_missing(self):
        from bmt_ai_os.controller.openai_compat import _provider_supports_tools

        provider = MagicMock(spec=[])
        assert _provider_supports_tools(provider) is False

    def test_attribute_true(self):
        from bmt_ai_os.controller.openai_compat import _provider_supports_tools

        provider = MagicMock()
        provider.supports_tools = True
        assert _provider_supports_tools(provider) is True

    def test_attribute_false(self):
        from bmt_ai_os.controller.openai_compat import _provider_supports_tools

        provider = MagicMock()
        provider.supports_tools = False
        assert _provider_supports_tools(provider) is False

    def test_callable_returning_true(self):
        from bmt_ai_os.controller.openai_compat import _provider_supports_tools

        provider = MagicMock()
        provider.supports_tools = lambda: True
        assert _provider_supports_tools(provider) is True

    def test_callable_returning_false(self):
        from bmt_ai_os.controller.openai_compat import _provider_supports_tools

        provider = MagicMock()
        provider.supports_tools = lambda: False
        assert _provider_supports_tools(provider) is False


class TestToolsToSystemMessage:
    def test_contains_function_name(self):
        from bmt_ai_os.controller.openai_compat import Tool, _tools_to_system_message

        tools = [Tool(**SAMPLE_TOOL)]
        msg = _tools_to_system_message(tools)
        assert "get_weather" in msg

    def test_contains_json_format_hint(self):
        from bmt_ai_os.controller.openai_compat import Tool, _tools_to_system_message

        tools = [Tool(**SAMPLE_TOOL)]
        msg = _tools_to_system_message(tools)
        assert "json" in msg.lower()

    def test_contains_description(self):
        from bmt_ai_os.controller.openai_compat import Tool, _tools_to_system_message

        tools = [Tool(**SAMPLE_TOOL)]
        msg = _tools_to_system_message(tools)
        assert "Get the weather for a city" in msg

    def test_multiple_tools_all_listed(self):
        from bmt_ai_os.controller.openai_compat import Tool, _tools_to_system_message

        tool2 = {
            "type": "function",
            "function": {
                "name": "search_web",
                "description": "Search the internet",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }
        tools = [Tool(**SAMPLE_TOOL), Tool(**tool2)]
        msg = _tools_to_system_message(tools)
        assert "get_weather" in msg
        assert "search_web" in msg


class TestParseToolCallFromText:
    def test_valid_json_block_extracted(self):
        from bmt_ai_os.controller.openai_compat import _parse_tool_call_from_text

        text = '```json\n{"name": "get_weather", "arguments": {"city": "Paris"}}\n```'
        result = _parse_tool_call_from_text(text)
        assert result is not None
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "get_weather"
        args = json.loads(result[0]["function"]["arguments"])
        assert args["city"] == "Paris"

    def test_no_json_block_returns_none(self):
        from bmt_ai_os.controller.openai_compat import _parse_tool_call_from_text

        assert _parse_tool_call_from_text("Plain text with no code block.") is None

    def test_malformed_json_returns_none(self):
        from bmt_ai_os.controller.openai_compat import _parse_tool_call_from_text

        assert _parse_tool_call_from_text("```json\n{not valid json}\n```") is None

    def test_missing_name_returns_none(self):
        from bmt_ai_os.controller.openai_compat import _parse_tool_call_from_text

        assert _parse_tool_call_from_text('```json\n{"arguments": {"city": "Paris"}}\n```') is None

    def test_code_block_without_language_tag(self):
        from bmt_ai_os.controller.openai_compat import _parse_tool_call_from_text

        text = '```\n{"name": "search", "arguments": {"query": "test"}}\n```'
        result = _parse_tool_call_from_text(text)
        assert result is not None
        assert result[0]["function"]["name"] == "search"

    def test_tool_call_ids_are_unique(self):
        from bmt_ai_os.controller.openai_compat import _parse_tool_call_from_text

        text = '```json\n{"name": "fn", "arguments": {}}\n```'
        r1 = _parse_tool_call_from_text(text)
        r2 = _parse_tool_call_from_text(text)
        assert r1 is not None and r2 is not None
        assert r1[0]["id"] != r2[0]["id"]


class TestBuildChatResponseTools:
    def test_no_tool_calls_finish_reason_stop(self):
        from bmt_ai_os.controller.openai_compat import _build_chat_response

        resp = _build_chat_response("hello", "model-x")
        assert resp["choices"][0]["finish_reason"] == "stop"
        assert "tool_calls" not in resp["choices"][0]["message"]

    def test_with_tool_calls_finish_reason_tool_calls(self):
        from bmt_ai_os.controller.openai_compat import _build_chat_response

        tc = [{"id": "call_1", "type": "function", "function": {"name": "fn", "arguments": "{}"}}]
        resp = _build_chat_response("", "model-x", tool_calls=tc)
        assert resp["choices"][0]["finish_reason"] == "tool_calls"
        assert resp["choices"][0]["message"]["tool_calls"] == tc


class TestChatCompletionsEndpointWithTools:
    """Integration-style tests via the full FastAPI app."""

    def _get_client(self):
        from bmt_ai_os.controller.api import app as main_app

        return TestClient(main_app, raise_server_exceptions=True)

    def test_request_with_tools_accepted_fallback_provider(self, monkeypatch):
        """tools parameter accepted; fallback system-message path; response is 200."""
        monkeypatch.setenv("BMT_JWT_SECRET", "test-secret-key-for-openai-compat-32!")
        provider = _make_tool_provider(supports_tools=False)
        registry = _make_tool_registry(provider)

        with patch(
            "bmt_ai_os.controller.openai_compat._get_provider_router", return_value=registry
        ):
            client = self._get_client()
            resp = client.post(
                "/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "What is the weather in Paris?"}],
                    "tools": [SAMPLE_TOOL],
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "choices" in data
        assert data["choices"][0]["message"]["role"] == "assistant"

    def test_response_includes_tool_calls_from_native_provider(self, monkeypatch):
        """Provider supports tools natively and returns tool_calls in response."""
        monkeypatch.setenv("BMT_JWT_SECRET", "test-secret-key-for-openai-compat-32!")
        native_tc = [
            {
                "id": "call_abc123",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'},
            }
        ]
        provider = _make_tool_provider(supports_tools=True, tool_calls_in_raw=native_tc)
        registry = _make_tool_registry(provider)

        with patch(
            "bmt_ai_os.controller.openai_compat._get_provider_router", return_value=registry
        ):
            client = self._get_client()
            resp = client.post(
                "/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "Weather?"}],
                    "tools": [SAMPLE_TOOL],
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["choices"][0]["finish_reason"] == "tool_calls"
        tc = data["choices"][0]["message"]["tool_calls"]
        assert tc is not None
        assert tc[0]["function"]["name"] == "get_weather"

    def test_fallback_parses_tool_call_from_text_response(self, monkeypatch):
        """Non-tool provider emitting a JSON block gets parsed as a tool_call."""
        monkeypatch.setenv("BMT_JWT_SECRET", "test-secret-key-for-openai-compat-32!")
        provider = _make_tool_provider(supports_tools=False)
        chat_response = MagicMock()
        chat_response.content = (
            '```json\n{"name": "get_weather", "arguments": {"city": "Berlin"}}\n```'
        )
        chat_response.model = "mock-model"
        chat_response.input_tokens = 10
        chat_response.output_tokens = 20
        chat_response.raw = {}
        chat_response.tool_calls = None
        provider.chat = AsyncMock(return_value=chat_response)
        registry = _make_tool_registry(provider)

        with patch(
            "bmt_ai_os.controller.openai_compat._get_provider_router", return_value=registry
        ):
            client = self._get_client()
            resp = client.post(
                "/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "Weather in Berlin?"}],
                    "tools": [SAMPLE_TOOL],
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        tc = data["choices"][0]["message"].get("tool_calls")
        assert tc is not None
        assert tc[0]["function"]["name"] == "get_weather"

    def test_graceful_when_no_tool_call_in_plain_text(self, monkeypatch):
        """Provider without tools returning plain text — no tool_calls in response."""
        monkeypatch.setenv("BMT_JWT_SECRET", "test-secret-key-for-openai-compat-32!")
        provider = _make_tool_provider(supports_tools=False)
        registry = _make_tool_registry(provider)

        with patch(
            "bmt_ai_os.controller.openai_compat._get_provider_router", return_value=registry
        ):
            client = self._get_client()
            resp = client.post(
                "/v1/chat/completions",
                json={
                    "messages": [{"role": "user", "content": "Tell me a joke"}],
                    "tools": [SAMPLE_TOOL],
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "tool_calls" not in data["choices"][0]["message"]

    def test_no_tools_param_unaffected(self, monkeypatch):
        """Requests without tools are entirely unaffected."""
        monkeypatch.setenv("BMT_JWT_SECRET", "test-secret-key-for-openai-compat-32!")
        provider = _make_tool_provider(supports_tools=False)
        registry = _make_tool_registry(provider)

        with patch(
            "bmt_ai_os.controller.openai_compat._get_provider_router", return_value=registry
        ):
            client = self._get_client()
            resp = client.post(
                "/v1/chat/completions",
                json={"messages": [{"role": "user", "content": "Hello"}]},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["choices"][0]["finish_reason"] == "stop"
        assert "tool_calls" not in data["choices"][0]["message"]
