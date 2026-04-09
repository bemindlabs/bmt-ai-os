<<<<<<< HEAD
"""Abstract base classes and data models for the LLM provider layer."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import AsyncGenerator


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

    role: str  # "system", "user", "assistant"
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
    """Response returned by :meth:`LLMProvider.chat`."""

    content: str
    model: str
    provider: str
    usage: TokenUsage = field(default_factory=lambda: TokenUsage())
    latency_ms: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


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

class LLMProvider(ABC):
    """Abstract interface that every LLM backend must implement."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique provider identifier (e.g. ``'ollama'``, ``'vllm'``)."""

    @abstractmethod
=======
"""BMT AI OS — LLM Provider abstract base class.

Every provider (Ollama, OpenAI, Groq, vLLM, ...) implements this interface
so the controller and RAG pipeline can swap backends transparently.
"""

from __future__ import annotations

import abc
import dataclasses
import time
from typing import Any, AsyncIterator


@dataclasses.dataclass
class ChatMessage:
    """Single message in a conversation."""

    role: str  # "system" | "user" | "assistant"
    content: str


@dataclasses.dataclass
class ChatResponse:
    """Result returned by provider.chat()."""

    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    raw: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class EmbedResponse:
    """Result returned by provider.embed()."""

    embedding: list[float]
    model: str
    input_tokens: int = 0
    latency_ms: float = 0.0


class LLMProvider(abc.ABC):
    """Abstract base for all LLM providers."""

    name: str = "base"

    @abc.abstractmethod
>>>>>>> 89ca624 (feat(BMTOS-8a): implement cloud LLM provider: OpenAI)
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
<<<<<<< HEAD
        max_tokens: int = 2048,
        stream: bool = False,
    ) -> ChatResponse | AsyncGenerator[str, None]:
        """Send a chat completion request.

        When *stream* is ``False`` return a :class:`ChatResponse`.
        When *stream* is ``True`` return an async generator yielding content
        chunks as plain strings.
        """

    @abstractmethod
    async def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> list[list[float]]:
        """Return embedding vectors for *texts*."""

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        """Return models currently available on this provider."""

    @abstractmethod
    async def health_check(self) -> ProviderHealth:
        """Check whether the provider backend is reachable and healthy."""

    # Convenience ---------------------------------------------------------

    @staticmethod
    def _elapsed_ms(start: float) -> float:
        """Milliseconds elapsed since *start* (``time.perf_counter``)."""
        return round((time.perf_counter() - start) * 1000, 2)
=======
        max_tokens: int = 4096,
        stream: bool = False,
    ) -> ChatResponse | AsyncIterator[str]:
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
    async def list_models(self) -> list[dict[str, Any]]:
        """Return available models from the provider."""

    @abc.abstractmethod
    async def health_check(self) -> bool:
        """Return True if the provider endpoint is reachable."""

    # Utility ----------------------------------------------------------------

    @staticmethod
    def _now_ms() -> float:
        return time.monotonic() * 1000
>>>>>>> 89ca624 (feat(BMTOS-8a): implement cloud LLM provider: OpenAI)
