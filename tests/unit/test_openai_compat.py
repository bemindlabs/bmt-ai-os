"""Unit tests for OpenAI-compatible API endpoints.

Validates that the endpoints return correctly structured responses
matching the OpenAI API format expected by Cursor, Copilot, and Cody.
"""

from __future__ import annotations

import json
import unittest.mock
from unittest.mock import patch

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
