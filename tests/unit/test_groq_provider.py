"""Unit tests for the Groq cloud LLM provider."""

from __future__ import annotations

import asyncio
import os
from unittest.mock import patch

import pytest

from bmt_ai_os.providers.base import ProviderError
from bmt_ai_os.providers.groq_provider import _GROQ_PRICING, GroqProvider
from bmt_ai_os.providers.openai_provider import OpenAICompatibleProvider

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def provider():
    """Create a Groq provider with a dummy API key."""
    return GroqProvider(api_key="gsk-test-key-12345")


# ---------------------------------------------------------------------------
# Subclassing
# ---------------------------------------------------------------------------


class TestSubclassing:
    def test_inherits_openai_compatible(self):
        assert issubclass(GroqProvider, OpenAICompatibleProvider)

    def test_name(self, provider):
        assert provider.name == "groq"

    def test_default_model(self, provider):
        assert provider.default_model == "llama-3.3-70b-versatile"

    def test_has_pricing_table(self):
        assert len(_GROQ_PRICING) > 0
        assert "llama-3.3-70b-versatile" in _GROQ_PRICING


# ---------------------------------------------------------------------------
# URL and headers
# ---------------------------------------------------------------------------


class TestURLAndHeaders:
    def test_base_url(self, provider):
        assert provider.base_url == "https://api.groq.com/openai/v1"

    def test_chat_completions_url(self, provider):
        url = provider._url("/chat/completions")
        assert url == "https://api.groq.com/openai/v1/chat/completions"

    def test_models_url(self, provider):
        url = provider._url("/models")
        assert url == "https://api.groq.com/openai/v1/models"

    def test_headers_include_auth(self, provider):
        headers = provider._headers()
        assert headers["Authorization"] == "Bearer gsk-test-key-12345"
        assert headers["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# Embed raises ProviderError
# ---------------------------------------------------------------------------


class TestEmbed:
    def test_embed_raises_provider_error(self, provider):
        with pytest.raises(ProviderError, match="does not support embeddings"):
            asyncio.run(provider.embed("test text"))

    def test_embed_list_raises_provider_error(self, provider):
        with pytest.raises(ProviderError, match="does not support embeddings"):
            asyncio.run(provider.embed(["text one", "text two"]))

    def test_embed_error_suggests_alternatives(self, provider):
        with pytest.raises(ProviderError, match="OpenAI|Mistral|local"):
            asyncio.run(provider.embed("test"))


# ---------------------------------------------------------------------------
# API key loading
# ---------------------------------------------------------------------------


class TestAPIKeyLoading:
    def test_explicit_key(self):
        p = GroqProvider(api_key="explicit-groq-key")
        assert p._api_key == "explicit-groq-key"

    def test_env_var_key(self):
        os.environ["GROQ_API_KEY"] = "env-groq-key"
        try:
            p = GroqProvider()
            assert p._api_key == "env-groq-key"
        finally:
            del os.environ["GROQ_API_KEY"]

    def test_explicit_key_overrides_env(self):
        os.environ["GROQ_API_KEY"] = "env-groq-key"
        try:
            p = GroqProvider(api_key="explicit-groq-key")
            assert p._api_key == "explicit-groq-key"
        finally:
            del os.environ["GROQ_API_KEY"]

    def test_api_key_env_var_name(self):
        assert GroqProvider.api_key_env_var == "GROQ_API_KEY"

    def test_secrets_file_key(self, tmp_path):
        secrets_file = tmp_path / "GROQ_API_KEY"
        secrets_file.write_text("  file-groq-key  \n")
        os.environ.pop("GROQ_API_KEY", None)
        with patch(
            "bmt_ai_os.providers.config._SECRETS_DIR",
            tmp_path,
        ):
            p = GroqProvider()
            assert p._api_key == "file-groq-key"


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------


class TestCostEstimation:
    def test_cost_known_model(self, provider):
        cost = provider._estimate_cost("llama-3.3-70b-versatile", 1_000_000, 1_000_000)
        input_price, output_price = _GROQ_PRICING["llama-3.3-70b-versatile"]
        expected = input_price + output_price
        assert abs(cost - expected) < 0.01

    def test_cost_unknown_model(self, provider):
        cost = provider._estimate_cost("unknown-model", 1000, 1000)
        assert cost == 0.0


# ---------------------------------------------------------------------------
# Custom base_url override
# ---------------------------------------------------------------------------


class TestBaseURLOverride:
    def test_override_base_url(self):
        p = GroqProvider(api_key="key", base_url="https://custom.groq.example.com/v1")
        assert p.base_url == "https://custom.groq.example.com/v1"

    def test_override_default_model(self):
        p = GroqProvider(api_key="key", default_model="llama-3.1-8b-instant")
        assert p.default_model == "llama-3.1-8b-instant"
