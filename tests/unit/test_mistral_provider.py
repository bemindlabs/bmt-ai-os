"""Unit tests for the Mistral AI cloud LLM provider."""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, patch

import pytest

from bmt_ai_os.providers.base import EmbedResponse
from bmt_ai_os.providers.mistral_provider import _MISTRAL_PRICING, MistralProvider
from bmt_ai_os.providers.openai_provider import OpenAICompatibleProvider

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def provider():
    """Create a Mistral provider with a dummy API key."""
    return MistralProvider(api_key="ms-test-key-12345")


# ---------------------------------------------------------------------------
# Subclassing
# ---------------------------------------------------------------------------


class TestSubclassing:
    def test_inherits_openai_compatible(self):
        assert issubclass(MistralProvider, OpenAICompatibleProvider)

    def test_name(self, provider):
        assert provider.name == "mistral"

    def test_default_model(self, provider):
        assert provider.default_model == "mistral-small-latest"

    def test_default_embed_model(self, provider):
        assert provider.default_embed_model == "mistral-embed"

    def test_has_pricing_table(self):
        assert len(_MISTRAL_PRICING) > 0
        assert "mistral-small-latest" in _MISTRAL_PRICING
        assert "mistral-embed" in _MISTRAL_PRICING


# ---------------------------------------------------------------------------
# URL and headers
# ---------------------------------------------------------------------------


class TestURLAndHeaders:
    def test_base_url(self, provider):
        assert provider.base_url == "https://api.mistral.ai/v1"

    def test_chat_completions_url(self, provider):
        url = provider._url("/chat/completions")
        assert url == "https://api.mistral.ai/v1/chat/completions"

    def test_embeddings_url(self, provider):
        url = provider._url("/embeddings")
        assert url == "https://api.mistral.ai/v1/embeddings"

    def test_models_url(self, provider):
        url = provider._url("/models")
        assert url == "https://api.mistral.ai/v1/models"

    def test_headers_include_auth(self, provider):
        headers = provider._headers()
        assert headers["Authorization"] == "Bearer ms-test-key-12345"
        assert headers["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# Embed works (inherited from OpenAICompatibleProvider)
# ---------------------------------------------------------------------------


class TestEmbed:
    def test_embed_method_exists(self, provider):
        """Mistral inherits embed() from OpenAICompatibleProvider (not overridden)."""
        assert hasattr(provider, "embed")
        # The method should be the one from OpenAICompatibleProvider, not overridden
        assert provider.embed.__func__ is OpenAICompatibleProvider.embed

    def test_embed_uses_mistral_embed_model(self, provider):
        """Default embed model should be mistral-embed."""
        assert provider.default_embed_model == "mistral-embed"

    def test_embed_with_mock(self, provider):
        """Test embed() calls the correct endpoint with correct payload."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}],
                "model": "mistral-embed",
                "usage": {"prompt_tokens": 5, "total_tokens": 5},
            }
        )

        async def _run():
            with patch.object(
                provider,
                "_request_with_retry",
                return_value=mock_response,
            ) as mock_req:
                result = await provider.embed("Hello world")
                mock_req.assert_called_once_with(
                    "POST",
                    "/embeddings",
                    json_body={
                        "model": "mistral-embed",
                        "input": ["Hello world"],
                    },
                )
                assert isinstance(result, EmbedResponse)
                assert result.embedding == [0.1, 0.2, 0.3]
                assert result.model == "mistral-embed"

        asyncio.run(_run())

    def test_embed_batch_with_mock(self, provider):
        """Test embed() with multiple texts returns a list."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "data": [
                    {"index": 0, "embedding": [0.1, 0.2]},
                    {"index": 1, "embedding": [0.3, 0.4]},
                ],
                "model": "mistral-embed",
                "usage": {"prompt_tokens": 10, "total_tokens": 10},
            }
        )

        async def _run():
            with patch.object(provider, "_request_with_retry", return_value=mock_response):
                results = await provider.embed(["Hello", "World"])
                assert isinstance(results, list)
                assert len(results) == 2
                assert results[0].embedding == [0.1, 0.2]
                assert results[1].embedding == [0.3, 0.4]

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# API key loading
# ---------------------------------------------------------------------------


class TestAPIKeyLoading:
    def test_explicit_key(self):
        p = MistralProvider(api_key="explicit-mistral-key")
        assert p._api_key == "explicit-mistral-key"

    def test_env_var_key(self):
        os.environ["MISTRAL_API_KEY"] = "env-mistral-key"
        try:
            p = MistralProvider()
            assert p._api_key == "env-mistral-key"
        finally:
            del os.environ["MISTRAL_API_KEY"]

    def test_explicit_key_overrides_env(self):
        os.environ["MISTRAL_API_KEY"] = "env-mistral-key"
        try:
            p = MistralProvider(api_key="explicit-mistral-key")
            assert p._api_key == "explicit-mistral-key"
        finally:
            del os.environ["MISTRAL_API_KEY"]

    def test_api_key_env_var_name(self):
        assert MistralProvider.api_key_env_var == "MISTRAL_API_KEY"

    def test_secrets_file_key(self, tmp_path):
        secrets_file = tmp_path / "MISTRAL_API_KEY"
        secrets_file.write_text("  file-mistral-key  \n")
        os.environ.pop("MISTRAL_API_KEY", None)
        with patch(
            "bmt_ai_os.providers.config._SECRETS_DIR",
            tmp_path,
        ):
            p = MistralProvider()
            assert p._api_key == "file-mistral-key"


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------


class TestCostEstimation:
    def test_cost_known_model(self, provider):
        cost = provider._estimate_cost("mistral-small-latest", 1_000_000, 1_000_000)
        input_price, output_price = _MISTRAL_PRICING["mistral-small-latest"]
        expected = input_price + output_price
        assert abs(cost - expected) < 0.01

    def test_cost_embed_model(self, provider):
        cost = provider._estimate_cost("mistral-embed", 1_000_000, 0)
        input_price, _ = _MISTRAL_PRICING["mistral-embed"]
        assert abs(cost - input_price) < 0.01

    def test_cost_unknown_model(self, provider):
        cost = provider._estimate_cost("unknown-model", 1000, 1000)
        assert cost == 0.0


# ---------------------------------------------------------------------------
# Custom overrides
# ---------------------------------------------------------------------------


class TestOverrides:
    def test_override_base_url(self):
        p = MistralProvider(api_key="key", base_url="https://custom.mistral.example.com/v1")
        assert p.base_url == "https://custom.mistral.example.com/v1"

    def test_override_default_model(self):
        p = MistralProvider(api_key="key", default_model="mistral-large-latest")
        assert p.default_model == "mistral-large-latest"

    def test_override_embed_model(self):
        p = MistralProvider(api_key="key", default_embed_model="custom-embed")
        assert p.default_embed_model == "custom-embed"
