"""Additional unit tests for bmt_ai_os.providers.base data classes.

Extends test_provider_base.py with extra coverage for ChatMessage,
ChatResponse, TokenUsage, ModelInfo, ProviderHealth, EmbedResponse,
exception hierarchy, and the _elapsed_ms helper.
"""

from __future__ import annotations

import time

import pytest

from bmt_ai_os.providers.base import (
    ChatMessage,
    ChatResponse,
    EmbedResponse,
    LLMProvider,
    ModelInfo,
    ModelNotFoundError,
    ProviderError,
    ProviderHealth,
    ProviderTimeoutError,
    TokenUsage,
)

# ---------------------------------------------------------------------------
# ChatMessage
# ---------------------------------------------------------------------------


class TestChatMessageExtra:
    def test_to_dict_user(self):
        msg = ChatMessage(role="user", content="Hello")
        assert msg.to_dict() == {"role": "user", "content": "Hello"}

    def test_to_dict_system(self):
        msg = ChatMessage(role="system", content="You are helpful.")
        assert msg.to_dict()["role"] == "system"

    def test_to_dict_assistant(self):
        msg = ChatMessage(role="assistant", content="I can help.")
        assert msg.to_dict()["role"] == "assistant"

    def test_frozen_immutable(self):
        msg = ChatMessage(role="user", content="test")
        with pytest.raises(Exception):
            msg.role = "admin"  # type: ignore

    def test_equality(self):
        a = ChatMessage(role="user", content="hi")
        b = ChatMessage(role="user", content="hi")
        assert a == b

    def test_inequality_different_role(self):
        a = ChatMessage(role="user", content="hi")
        b = ChatMessage(role="system", content="hi")
        assert a != b

    def test_empty_content(self):
        msg = ChatMessage(role="user", content="")
        assert msg.content == ""

    def test_multiline_content(self):
        msg = ChatMessage(role="user", content="line1\nline2\nline3")
        assert "line2" in msg.content

    def test_unicode_content(self):
        msg = ChatMessage(role="user", content="Hello 世界 🌍")
        d = msg.to_dict()
        assert d["content"] == "Hello 世界 🌍"


# ---------------------------------------------------------------------------
# TokenUsage
# ---------------------------------------------------------------------------


class TestTokenUsageExtra:
    def test_default_zeros(self):
        u = TokenUsage()
        assert u.prompt_tokens == 0
        assert u.completion_tokens == 0
        assert u.total_tokens == 0

    def test_full_construction(self):
        u = TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30)
        assert u.prompt_tokens == 10
        assert u.completion_tokens == 20
        assert u.total_tokens == 30

    def test_to_dict_all_keys(self):
        u = TokenUsage(prompt_tokens=5, completion_tokens=10, total_tokens=15)
        d = u.to_dict()
        assert set(d.keys()) == {"prompt_tokens", "completion_tokens", "total_tokens"}

    def test_frozen(self):
        u = TokenUsage(10, 20, 30)
        with pytest.raises(Exception):
            u.prompt_tokens = 99  # type: ignore

    def test_equality(self):
        a = TokenUsage(1, 2, 3)
        b = TokenUsage(1, 2, 3)
        assert a == b

    def test_hashable(self):
        u = TokenUsage(1, 2, 3)
        s = {u}
        assert u in s


# ---------------------------------------------------------------------------
# ChatResponse
# ---------------------------------------------------------------------------


class TestChatResponseExtra:
    def test_minimal_construction(self):
        resp = ChatResponse(content="hello", model="qwen2.5:7b")
        assert resp.content == "hello"
        assert resp.model == "qwen2.5:7b"
        assert resp.provider == ""
        assert resp.latency_ms == 0.0

    def test_full_construction(self):
        usage = TokenUsage(10, 20, 30)
        resp = ChatResponse(
            content="answer",
            model="qwen2.5:7b",
            provider="ollama",
            usage=usage,
            latency_ms=150.0,
        )
        assert resp.provider == "ollama"
        assert resp.usage.total_tokens == 30
        assert resp.latency_ms == 150.0

    def test_to_dict_contains_all_fields(self):
        resp = ChatResponse(content="answer", model="qwen2.5:7b", provider="ollama")
        d = resp.to_dict()
        for key in ["content", "model", "provider", "latency_ms"]:
            assert key in d

    def test_usage_defaults_to_empty(self):
        resp = ChatResponse(content="hi", model="m")
        assert resp.usage.total_tokens == 0

    def test_frozen(self):
        resp = ChatResponse(content="hi", model="m")
        with pytest.raises(Exception):
            resp.content = "changed"  # type: ignore

    def test_raw_defaults_empty_dict(self):
        resp = ChatResponse(content="hi", model="m")
        assert resp.raw == {}


# ---------------------------------------------------------------------------
# ModelInfo
# ---------------------------------------------------------------------------


class TestModelInfoExtra:
    def test_required_name(self):
        info = ModelInfo(name="qwen2.5:7b")
        assert info.name == "qwen2.5:7b"

    def test_optional_fields_default_empty(self):
        info = ModelInfo(name="test")
        assert info.size_bytes == 0
        assert info.quantization == ""
        assert info.family == ""

    def test_to_dict(self):
        info = ModelInfo(
            name="llama3:8b", size_bytes=5_000_000_000, quantization="Q4_K_M", family="llama"
        )
        d = info.to_dict()
        assert d["name"] == "llama3:8b"
        assert d["size_bytes"] == 5_000_000_000
        assert d["quantization"] == "Q4_K_M"
        assert d["family"] == "llama"

    def test_equality(self):
        a = ModelInfo(name="m", size_bytes=100)
        b = ModelInfo(name="m", size_bytes=100)
        assert a == b

    def test_frozen(self):
        info = ModelInfo(name="m")
        with pytest.raises(Exception):
            info.name = "changed"  # type: ignore


# ---------------------------------------------------------------------------
# ProviderHealth
# ---------------------------------------------------------------------------


class TestProviderHealthExtra:
    def test_healthy_no_error(self):
        h = ProviderHealth(healthy=True, latency_ms=5.0)
        assert h.healthy is True
        assert h.error is None

    def test_unhealthy_with_error(self):
        h = ProviderHealth(healthy=False, latency_ms=0.0, error="connection refused")
        assert h.healthy is False
        assert h.error == "connection refused"

    def test_to_dict_keys(self):
        h = ProviderHealth(healthy=True, latency_ms=10.0)
        d = h.to_dict()
        assert "healthy" in d
        assert "latency_ms" in d
        assert "error" in d

    def test_to_dict_unhealthy_values(self):
        h = ProviderHealth(healthy=False, latency_ms=0.5, error="timeout")
        d = h.to_dict()
        assert d["healthy"] is False
        assert d["error"] == "timeout"

    def test_latency_stored(self):
        h = ProviderHealth(healthy=True, latency_ms=42.7)
        assert h.latency_ms == 42.7


# ---------------------------------------------------------------------------
# EmbedResponse
# ---------------------------------------------------------------------------


class TestEmbedResponseExtra:
    def test_construction(self):
        er = EmbedResponse(embedding=[0.1, 0.2, 0.3], model="nomic-embed-text")
        assert er.embedding == [0.1, 0.2, 0.3]
        assert er.model == "nomic-embed-text"

    def test_optional_fields_default(self):
        er = EmbedResponse(embedding=[], model="m")
        assert er.input_tokens == 0
        assert er.latency_ms == 0.0

    def test_frozen(self):
        er = EmbedResponse(embedding=[0.1], model="m")
        with pytest.raises(Exception):
            er.model = "changed"  # type: ignore

    def test_empty_embedding(self):
        er = EmbedResponse(embedding=[], model="m")
        assert er.embedding == []

    def test_large_embedding(self):
        vec = [float(i) / 1000 for i in range(768)]
        er = EmbedResponse(embedding=vec, model="nomic")
        assert len(er.embedding) == 768


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class TestExceptionsExtra:
    def test_provider_error_is_exception(self):
        e = ProviderError("test")
        assert isinstance(e, Exception)

    def test_timeout_error_is_provider_error(self):
        e = ProviderTimeoutError("timed out")
        assert isinstance(e, ProviderError)

    def test_model_not_found_is_provider_error(self):
        e = ModelNotFoundError("model not found")
        assert isinstance(e, ProviderError)

    def test_can_catch_provider_error_via_parent(self):
        with pytest.raises(ProviderError):
            raise ProviderTimeoutError("timeout")

    def test_error_message_preserved(self):
        try:
            raise ProviderError("custom message")
        except ProviderError as e:
            assert "custom message" in str(e)

    def test_model_not_found_message(self):
        try:
            raise ModelNotFoundError("qwen2.5:7b not found")
        except ModelNotFoundError as e:
            assert "qwen2.5:7b" in str(e)

    def test_timeout_inherits_from_provider_error(self):
        assert issubclass(ProviderTimeoutError, ProviderError)

    def test_model_not_found_inherits_from_provider_error(self):
        assert issubclass(ModelNotFoundError, ProviderError)


# ---------------------------------------------------------------------------
# _elapsed_ms helper
# ---------------------------------------------------------------------------


class TestElapsedMs:
    def test_positive_elapsed(self):
        start = time.perf_counter()
        time.sleep(0.01)
        elapsed = LLMProvider._elapsed_ms(start)
        assert elapsed >= 5  # at least 5ms

    def test_returns_float(self):
        start = time.perf_counter()
        elapsed = LLMProvider._elapsed_ms(start)
        assert isinstance(elapsed, float)

    def test_small_but_non_negative(self):
        start = time.perf_counter()
        elapsed = LLMProvider._elapsed_ms(start)
        assert elapsed >= 0

    def test_increases_with_time(self):
        start = time.perf_counter()
        e1 = LLMProvider._elapsed_ms(start)
        time.sleep(0.005)
        e2 = LLMProvider._elapsed_ms(start)
        assert e2 > e1
