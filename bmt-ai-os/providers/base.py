"""BMT AI OS — LLM Provider abstract base class.

Every provider (Ollama, OpenAI, Groq, vLLM, ...) implements this interface
so the controller and RAG pipeline can swap backends transparently.
"""

from __future__ import annotations

import abc
import time
from dataclasses import asdict, dataclass, field
from typing import Any, AsyncGenerator, AsyncIterator

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ProviderError(Exception):
    """Base exception for provider-related errors."""


class ProviderTimeoutError(ProviderError):
    """Raised when a provider request exceeds the configured timeout."""


class ModelNotFoundError(ProviderError):
    """Raised when the requested model is not available on the provider."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChatMessage:
    """A single message in a chat conversation."""

    role: str  # "system" | "user" | "assistant"
    content: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class TokenUsage:
    """Token consumption for a single request."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ChatResponse:
    """Response returned by provider.chat()."""

    content: str
    model: str
    provider: str = ""
    usage: TokenUsage = field(default_factory=TokenUsage)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class EmbedResponse:
    """Result returned by provider.embed()."""

    embedding: list[float]
    model: str
    input_tokens: int = 0
    latency_ms: float = 0.0


@dataclass(frozen=True)
class ModelInfo:
    """Metadata about a model available on a provider."""

    name: str
    size_bytes: int = 0
    quantization: str = ""
    family: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ProviderHealth:
    """Result of a provider health check."""

    healthy: bool
    latency_ms: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Abstract provider
# ---------------------------------------------------------------------------


class LLMProvider(abc.ABC):
    """Abstract interface that every LLM backend must implement."""

    name: str = "base"

    @abc.abstractmethod
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
    ) -> ChatResponse | AsyncIterator[str] | AsyncGenerator[str, None]:
        """Send a chat completion request.

        When *stream* is True, returns an async iterator yielding content
        deltas (strings).  When False, returns a single ChatResponse.
        """

    @abc.abstractmethod
    async def embed(
        self,
        text: str | list[str],
        *,
        model: str | None = None,
    ) -> EmbedResponse | list[EmbedResponse]:
        """Generate embeddings for one or more texts."""

    @abc.abstractmethod
    async def list_models(self) -> list[ModelInfo] | list[dict[str, Any]]:
        """Return available models from the provider."""

    @abc.abstractmethod
    async def health_check(self) -> ProviderHealth | bool:
        """Check whether the provider backend is reachable and healthy."""

    # Utility ----------------------------------------------------------------

    @staticmethod
    def _elapsed_ms(start: float) -> float:
        """Milliseconds elapsed since *start* (``time.perf_counter``)."""
        return round((time.perf_counter() - start) * 1000, 2)

    @staticmethod
    def _now_ms() -> float:
        return time.monotonic() * 1000
