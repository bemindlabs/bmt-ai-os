"""Ollama provider — reference LLM backend implementation."""

from __future__ import annotations

import json
import time
from typing import Any, AsyncGenerator

import aiohttp

from bmt_ai_os.providers.base import (
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

_DEFAULT_BASE_URL = "http://localhost:11434"
_DEFAULT_MODEL = "qwen2.5-coder:7b-instruct-q4_K_M"


class OllamaProvider(LLMProvider):
    """Provider that communicates with a local Ollama instance.

    Parameters
    ----------
    base_url:
        Root URL of the Ollama HTTP API (default ``http://localhost:11434``).
    default_model:
        Model tag used when callers do not specify one.
    timeout:
        Per-request timeout in seconds.
    """

    def __init__(
        self,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        default_model: str = _DEFAULT_MODEL,
        timeout: int = 30,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    # -- LLMProvider interface --------------------------------------------

    @property
    def name(self) -> str:  # noqa: D401
        return "ollama"

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stream: bool = False,
    ) -> ChatResponse | AsyncGenerator[str, None]:
        model = model or self._default_model
        payload: dict[str, Any] = {
            "model": model,
            "messages": [m.to_dict() for m in messages],
            "stream": stream,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        if stream:
            return self._stream_chat(payload, model)

        start = time.perf_counter()
        data = await self._post("/api/chat", payload)
        latency = self._elapsed_ms(start)

        content = data.get("message", {}).get("content", "")
        usage = self._parse_usage(data)

        return ChatResponse(
            content=content,
            model=model,
            provider=self.name,
            usage=usage,
            latency_ms=latency,
        )

    async def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> list[list[float]]:
        model = model or self._default_model
        payload: dict[str, Any] = {
            "model": model,
            "input": texts,
        }
        data = await self._post("/api/embed", payload)
        embeddings = data.get("embeddings", [])
        if not embeddings:
            raise ProviderError("Ollama returned no embeddings.")
        return embeddings

    async def list_models(self) -> list[ModelInfo]:
        data = await self._get("/api/tags")
        models: list[ModelInfo] = []
        for m in data.get("models", []):
            details = m.get("details", {})
            models.append(
                ModelInfo(
                    name=m.get("name", ""),
                    size_bytes=m.get("size", 0),
                    quantization=details.get("quantization_level", ""),
                    family=details.get("family", ""),
                )
            )
        return models

    async def health_check(self) -> ProviderHealth:
        start = time.perf_counter()
        try:
            await self._get("/api/tags")
            return ProviderHealth(
                healthy=True,
                latency_ms=self._elapsed_ms(start),
            )
        except Exception as exc:
            return ProviderHealth(
                healthy=False,
                latency_ms=self._elapsed_ms(start),
                error=str(exc),
            )

    # -- Internal HTTP helpers -------------------------------------------

    async def _post(self, path: str, payload: dict) -> dict:
        url = f"{self._base_url}{path}"
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 404:
                        raise ModelNotFoundError(f"Model not found: {payload.get('model')}")
                    if resp.status != 200:
                        body = await resp.text()
                        raise ProviderError(f"Ollama returned {resp.status}: {body}")
                    return await resp.json()
        except aiohttp.ServerTimeoutError as exc:
            raise ProviderTimeoutError(str(exc)) from exc
        except aiohttp.ClientError as exc:
            raise ProviderError(f"Ollama connection error: {exc}") from exc

    async def _get(self, path: str) -> dict:
        url = f"{self._base_url}{path}"
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise ProviderError(f"Ollama returned {resp.status}: {body}")
                    return await resp.json()
        except aiohttp.ServerTimeoutError as exc:
            raise ProviderTimeoutError(str(exc)) from exc
        except aiohttp.ClientError as exc:
            raise ProviderError(f"Ollama connection error: {exc}") from exc

    async def _stream_chat(
        self,
        payload: dict,
        model: str,
    ) -> AsyncGenerator[str, None]:
        """Yield content chunks from Ollama's NDJSON streaming response."""
        url = f"{self._base_url}/api/chat"
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise ProviderError(f"Ollama returned {resp.status}: {body}")
                    async for line in resp.content:
                        line = line.strip()
                        if not line:
                            continue
                        data = json.loads(line)
                        chunk = data.get("message", {}).get("content", "")
                        if chunk:
                            yield chunk
        except aiohttp.ClientError as exc:
            raise ProviderError(f"Ollama stream error: {exc}") from exc

    # -- Helpers ----------------------------------------------------------

    @staticmethod
    def _parse_usage(data: dict) -> TokenUsage:
        prompt = data.get("prompt_eval_count", 0)
        completion = data.get("eval_count", 0)
        return TokenUsage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
        )

    def build_url(self, path: str) -> str:
        """Return the full URL for a given API *path* (useful for testing)."""
        return f"{self._base_url}{path}"
