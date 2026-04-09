"""Abstract base class for LLM providers."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatMessage:
    """A single chat message."""

    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class ChatResponse:
    """Response from a chat completion request."""

    content: str
    model: str
    provider: str
    usage: dict[str, int] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class EmbedResponse:
    """Response from an embedding request."""

    embeddings: list[list[float]]
    model: str
    provider: str


class LLMProvider(abc.ABC):
    """Abstract base for all LLM providers (Ollama, vLLM, llama.cpp, OpenAI, Anthropic)."""

    name: str = "base"

    @abc.abstractmethod
    async def chat(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Send a chat completion request."""
        ...

    @abc.abstractmethod
    async def embed(
        self,
        texts: list[str],
        model: str | None = None,
        **kwargs: Any,
    ) -> EmbedResponse:
        """Generate embeddings for the given texts."""
        ...

    @abc.abstractmethod
    async def list_models(self) -> list[str]:
        """Return available model names."""
        ...

    @abc.abstractmethod
    async def health_check(self) -> bool:
        """Return True if the provider is reachable and healthy."""
        ...
