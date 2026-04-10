"""llama.cpp provider — lightweight local inference via llama-server.

llama-server exposes an OpenAI-compatible HTTP API, making this provider
simpler than the Ollama one.  Key difference: llama-server loads exactly
one model at a time; model switching requires a container/process restart.

ARM64 optimizations (NEON/SVE, KleidiAI) are compile-time flags on the
server binary — the provider talks plain HTTP and is acceleration-agnostic.
"""

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

_DEFAULT_BASE_URL = "http://localhost:8002"
_DEFAULT_MODEL = "qwen2.5-coder-7b-instruct-q4_k_m.gguf"


class LlamaCppProvider(LLMProvider):
    """Provider that communicates with a local llama-server instance.

    Parameters
    ----------
    base_url:
        Root URL of the llama-server HTTP API (default ``http://localhost:8002``).
    default_model:
        Model identifier returned in responses.  Because llama-server loads
        a single GGUF file at startup, this is informational only.
    timeout:
        Per-request timeout in seconds.
    n_ctx:
        Context size hint passed to /v1/chat/completions when the server
        supports it.  Defaults to ``4096``.
    n_threads:
        Thread count hint.  Defaults to ``None`` (server decides).
    """

    def __init__(
        self,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        default_model: str = _DEFAULT_MODEL,
        timeout: int = 30,
        n_ctx: int = 4096,
        n_threads: int | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._n_ctx = n_ctx
        self._n_threads = n_threads

    # -- LLMProvider interface ------------------------------------------------

    @property
    def name(self) -> str:  # noqa: D401
        return "llama-cpp"

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
        model = model or self._default_model
        payload: dict[str, Any] = {
            "model": model,
            "input": texts,
        }
        data = await self._post("/v1/embeddings", payload)
        embeddings_data = data.get("data", [])
        if not embeddings_data:
            raise ProviderError("llama-server returned no embeddings.")
        # Sort by index to guarantee order matches input.
        embeddings_data.sort(key=lambda x: x.get("index", 0))
        return [item["embedding"] for item in embeddings_data]

    async def list_models(self) -> list[ModelInfo]:
        data = await self._get("/v1/models")
        models: list[ModelInfo] = []
        for m in data.get("data", []):
            models.append(
                ModelInfo(
                    name=m.get("id", self._default_model),
                    size_bytes=0,
                    quantization="Q4_K_M",
                    family="",
                )
            )
        # llama-server may return an empty list; fall back to the loaded model.
        if not models:
            models.append(
                ModelInfo(
                    name=self._default_model,
                    size_bytes=0,
                    quantization="Q4_K_M",
                    family="",
                )
            )
        return models

    async def health_check(self) -> ProviderHealth:
        start = time.perf_counter()
        try:
            data = await self._get("/health")
            status = data.get("status", "")
            healthy = status == "ok"
            return ProviderHealth(
                healthy=healthy,
                latency_ms=self._elapsed_ms(start),
                error=None if healthy else f"status={status}",
            )
        except Exception as exc:
            return ProviderHealth(
                healthy=False,
                latency_ms=self._elapsed_ms(start),
                error=str(exc),
            )

    # -- Internal HTTP helpers ------------------------------------------------

    async def _post(self, path: str, payload: dict) -> dict:
        url = f"{self._base_url}{path}"
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 404:
                        raise ModelNotFoundError(f"Model not found: {payload.get('model')}")
                    if resp.status != 200:
                        body = await resp.text()
                        raise ProviderError(f"llama-server returned {resp.status}: {body}")
                    return await resp.json()
        except aiohttp.ServerTimeoutError as exc:
            raise ProviderTimeoutError(str(exc)) from exc
        except aiohttp.ClientError as exc:
            raise ProviderError(f"llama-server connection error: {exc}") from exc

    async def _get(self, path: str) -> dict:
        url = f"{self._base_url}{path}"
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise ProviderError(f"llama-server returned {resp.status}: {body}")
                    return await resp.json()
        except aiohttp.ServerTimeoutError as exc:
            raise ProviderTimeoutError(str(exc)) from exc
        except aiohttp.ClientError as exc:
            raise ProviderError(f"llama-server connection error: {exc}") from exc

    async def _stream_chat(
        self,
        payload: dict,
        model: str,
    ) -> AsyncGenerator[str, None]:
        """Yield content chunks from llama-server SSE streaming response.

        llama-server streams OpenAI-compatible ``data: {...}`` SSE lines,
        terminated by ``data: [DONE]``.
        """
        url = f"{self._base_url}/v1/chat/completions"
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise ProviderError(f"llama-server returned {resp.status}: {body}")
                    async for raw_line in resp.content:
                        line = raw_line.decode("utf-8").strip()
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[len("data: ") :]
                        if data_str == "[DONE]":
                            break
                        data = json.loads(data_str)
                        delta = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if delta:
                            yield delta
        except aiohttp.ClientError as exc:
            raise ProviderError(f"llama-server stream error: {exc}") from exc

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
