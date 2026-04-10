"""BMT AI OS -- Groq cloud LLM provider.

Groq provides the lowest-latency cloud inference (~200ms TTFT) using
custom LPU hardware.  Their API is OpenAI-compatible, so we reuse
:class:`OpenAICompatibleProvider` and only override class attributes.

Note: Groq does **not** support embeddings.  Calling :meth:`embed` raises
:class:`ProviderError`.
"""

from __future__ import annotations

from bmt_ai_os.providers.base import EmbedResponse, ProviderError
from bmt_ai_os.providers.openai_provider import OpenAICompatibleProvider

# Pricing as of 2026-Q2 (USD per million tokens)
_GROQ_PRICING: dict[str, tuple[float, float]] = {
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "llama-3.2-1b-preview": (0.04, 0.04),
    "llama-3.2-3b-preview": (0.06, 0.06),
    "llama-3.2-11b-vision-preview": (0.18, 0.18),
    "llama-3.2-90b-vision-preview": (0.90, 0.90),
    "mixtral-8x7b-32768": (0.24, 0.24),
    "gemma2-9b-it": (0.20, 0.20),
}


class GroqProvider(OpenAICompatibleProvider):
    """Groq cloud provider -- lowest latency cloud inference (~200ms TTFT).

    Groq runs models on custom LPU (Language Processing Unit) hardware,
    delivering extremely fast inference.  Useful as a low-latency cloud
    fallback when local providers are unavailable or overloaded.

    The API is fully OpenAI-compatible for chat completions, but Groq
    does **not** offer an embeddings endpoint.
    """

    name = "groq"
    base_url = "https://api.groq.com/openai/v1"
    default_model = "llama-3.3-70b-versatile"
    api_key_env_var = "GROQ_API_KEY"
    pricing = _GROQ_PRICING

    # Groq does NOT support embeddings ------------------------------------------

    async def embed(
        self,
        text: str | list[str],
        *,
        model: str | None = None,
    ) -> EmbedResponse | list[EmbedResponse]:
        """Raise :class:`ProviderError` -- Groq does not support embeddings."""
        raise ProviderError(
            f"Provider {self.name} does not support embeddings. "
            "Use a different provider (e.g. OpenAI, Mistral, or a local model) "
            "for embedding requests."
        )
