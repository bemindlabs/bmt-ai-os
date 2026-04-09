"""vLLM provider — high-throughput local LLM backend via OpenAI-compatible API."""

from __future__ import annotations

import json
import time
from typing import Any, AsyncGenerator

import aiohttp

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

_DEFAULT_BASE_URL = "http://localhost:8001"
_DEFAULT_MODEL = "qwen2.5-coder-7b-instruct"

# Ollama defaults used when falling back for embeddings.
_OLLAMA_BASE_URL = "http://localhost:11434"
_OLLAMA_EMBED_MODEL = "qwen2.5-coder:7b-instruct-q4_K_M"


class VLLMProvider(LLMProvider):
    """Provider that communicates with a local vLLM instance.

    vLLM exposes an OpenAI-compatible HTTP API, so this provider uses
    the ``/v1/chat/completions``, ``/v1/models``, and ``/v1/embeddings``
    endpoints directly.

    Parameters
    ----------
    base_url:
        Root URL of the vLLM HTTP API (default ``http://localhost:8001``).
    default_model:
        Model name used when callers do not specify one.
    timeout:
        Per-request timeout in seconds.
    ollama_base_url:
        Ollama URL used as embedding fallback when vLLM does not support
        ``/v1/embeddings``.
    ollama_embed_model:
        Model tag sent to Ollama for embedding requests.
    """

    def __init__(
        self,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        default_model: str = _DEFAULT_MODEL,
        timeout: int = 60,
        ollama_base_url: str = _OLLAMA_BASE_URL,
        ollama_embed_model: str = _OLLAMA_EMBED_MODEL,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._ollama_base_url = ollama_base_url.rstrip("/")
        self._ollama_embed_model = ollama_embed_model

    # -- LLMProvider interface ------------------------------------------------

    @property
    def name(self) -> str:  # noqa: D401
        return "vllm"

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
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

        if stream:
            return self._stream_chat(payload, model)

        start = time.perf_counter()
        data = await self._post("/v1/chat/completions", payload)
        latency = self._elapsed_ms(start)

        choices = data.get("choices", [])
        content = choices[0]["message"]["content"] if choices else ""
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
        """Return embeddings, falling back to Ollama if vLLM cannot serve them."""
        try:
            return await self._embed_vllm(texts, model=model)
        except ProviderError:
            return await self._embed_ollama_fallback(texts)

    async def list_models(self) -> list[ModelInfo]:
        data = await self._get("/v1/models")
        models: list[ModelInfo] = []
        for m in data.get("data", []):
            models.append(
                ModelInfo(
                    name=m.get("id", ""),
                    size_bytes=0,
                    quantization="",
                    family="",
                )
            )
        return models

    async def health_check(self) -> ProviderHealth:
        start = time.perf_counter()
        try:
            await self._get("/v1/models")
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

    # -- Embedding helpers ---------------------------------------------------

    async def _embed_vllm(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> list[list[float]]:
        """Request embeddings from vLLM's ``/v1/embeddings`` endpoint."""
        model = model or self._default_model
        payload: dict[str, Any] = {
            "model": model,
            "input": texts,
        }
        data = await self._post("/v1/embeddings", payload)
        results = data.get("data", [])
        if not results:
            raise ProviderError("vLLM returned no embeddings.")
        # Sort by index to guarantee ordering.
        results.sort(key=lambda r: r.get("index", 0))
        return [r["embedding"] for r in results]

    async def _embed_ollama_fallback(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        """Fall back to Ollama for embeddings when vLLM cannot serve them."""
        url = f"{self._ollama_base_url}/api/embed"
        payload: dict[str, Any] = {
            "model": self._ollama_embed_model,
            "input": texts,
        }
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise ProviderError(
                            f"Ollama embed fallback returned {resp.status}: {body}"
                        )
                    data = await resp.json()
        except aiohttp.ClientError as exc:
            raise ProviderError(
                f"Ollama embed fallback connection error: {exc}"
            ) from exc

        embeddings = data.get("embeddings", [])
        if not embeddings:
            raise ProviderError("Ollama embed fallback returned no embeddings.")
        return embeddings

    # -- Internal HTTP helpers -----------------------------------------------

    async def _post(self, path: str, payload: dict) -> dict:
        url = f"{self._base_url}{path}"
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 404:
                        raise ModelNotFoundError(
                            f"Model not found: {payload.get('model')}"
                        )
                    if resp.status != 200:
                        body = await resp.text()
                        raise ProviderError(
                            f"vLLM returned {resp.status}: {body}"
                        )
                    return await resp.json()
        except aiohttp.ServerTimeoutError as exc:
            raise ProviderTimeoutError(str(exc)) from exc
        except aiohttp.ClientError as exc:
            raise ProviderError(f"vLLM connection error: {exc}") from exc

    async def _get(self, path: str) -> dict:
        url = f"{self._base_url}{path}"
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise ProviderError(
                            f"vLLM returned {resp.status}: {body}"
                        )
                    return await resp.json()
        except aiohttp.ServerTimeoutError as exc:
            raise ProviderTimeoutError(str(exc)) from exc
        except aiohttp.ClientError as exc:
            raise ProviderError(f"vLLM connection error: {exc}") from exc

    async def _stream_chat(
        self,
        payload: dict,
        model: str,
    ) -> AsyncGenerator[str, None]:
        """Yield content chunks from vLLM's SSE streaming response."""
        url = f"{self._base_url}/v1/chat/completions"
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise ProviderError(
                            f"vLLM returned {resp.status}: {body}"
                        )
                    async for line in resp.content:
                        line = line.decode("utf-8").strip()
                        if not line or not line.startswith("data: "):
                            continue
                        raw = line[len("data: "):]
                        if raw == "[DONE]":
                            break
                        data = json.loads(raw)
                        delta = (
                            data.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content", "")
                        )
                        if delta:
                            yield delta
        except aiohttp.ClientError as exc:
            raise ProviderError(f"vLLM stream error: {exc}") from exc

    # -- Helpers --------------------------------------------------------------

    @staticmethod
    def _parse_usage(data: dict) -> TokenUsage:
        usage = data.get("usage", {})
        prompt = usage.get("prompt_tokens", 0)
        completion = usage.get("completion_tokens", 0)
        total = usage.get("total_tokens", prompt + completion)
        return TokenUsage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
        )

    def build_url(self, path: str) -> str:
        """Return the full URL for a given API *path* (useful for testing)."""
        return f"{self._base_url}{path}"
