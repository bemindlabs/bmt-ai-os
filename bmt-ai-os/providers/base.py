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
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
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
