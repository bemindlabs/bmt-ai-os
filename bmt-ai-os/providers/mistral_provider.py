"""BMT AI OS -- Mistral AI cloud LLM provider.

Mistral AI's API is OpenAI-compatible for both chat completions and
embeddings, so we reuse :class:`OpenAICompatibleProvider` and only
override class attributes plus the pricing table.
"""

from __future__ import annotations

from bmt_ai_os.providers.openai_provider import OpenAICompatibleProvider


# Pricing as of 2026-Q2 (USD per million tokens)
_MISTRAL_PRICING: dict[str, tuple[float, float]] = {
    "mistral-small-latest": (0.10, 0.30),
    "mistral-medium-latest": (2.70, 8.10),
    "mistral-large-latest": (2.00, 6.00),
    "codestral-latest": (0.30, 0.90),
    "open-mistral-nemo": (0.15, 0.15),
    "mistral-embed": (0.10, 0.0),
}


class MistralProvider(OpenAICompatibleProvider):
    """Mistral AI cloud provider.

    Mistral offers high-quality open-weight and proprietary models with
    an OpenAI-compatible API.  Both chat completions and embeddings are
    supported.

    Embeddings use the ``mistral-embed`` model by default via the
    standard ``/embeddings`` endpoint (same format as OpenAI).
    """

    name = "mistral"
    base_url = "https://api.mistral.ai/v1"
    default_model = "mistral-small-latest"
    default_embed_model = "mistral-embed"
    api_key_env_var = "MISTRAL_API_KEY"
    pricing = _MISTRAL_PRICING
