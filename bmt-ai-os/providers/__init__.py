"""BMT AI OS — LLM Provider Abstraction Layer.

Provides a unified interface for multiple LLM backends (Ollama, vLLM,
llama.cpp, OpenAI, Anthropic, etc.) with runtime switching and fallback
chain support.
"""

from providers.base import (
    ChatMessage,
    ChatResponse,
    LLMProvider,
    ModelInfo,
    ModelNotFoundError,
    ProviderError,
    ProviderHealth,
    ProviderTimeoutError,
    TokenUsage,
)
from providers.registry import ProviderRegistry, get_registry

__all__ = [
    "ChatMessage",
    "ChatResponse",
    "LLMProvider",
    "ModelInfo",
    "ModelNotFoundError",
    "ProviderError",
    "ProviderHealth",
    "ProviderTimeoutError",
    "TokenUsage",
    "ProviderRegistry",
    "get_registry",
]
