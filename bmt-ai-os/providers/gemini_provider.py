"""Google Gemini provider — cloud LLM backend via the Gemini REST API."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
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

_LOG = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_DEFAULT_MODEL = "gemini-2.0-flash"
_DEFAULT_EMBED_MODEL = "text-embedding-004"
_SECRETS_PATH = "/etc/bmt-ai-os/secrets/GOOGLE_API_KEY"

# Exponential back-off defaults for rate-limit (429) retries.
_MAX_RETRIES = 3
_INITIAL_BACKOFF_S = 1.0
_BACKOFF_MULTIPLIER = 2.0


def _resolve_api_key(api_key: str | None) -> str:
    """Return the API key from argument, env var, or secrets file."""
    if api_key:
        return api_key
    env_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if env_key:
        return env_key
    try:
        return Path(_SECRETS_PATH).read_text().strip()
    except (FileNotFoundError, PermissionError):
        pass
    return ""


class GeminiProvider(LLMProvider):
    """Provider that communicates with Google's Gemini REST API.

    Parameters
    ----------
    api_key:
        Gemini API key.  Falls back to ``GOOGLE_API_KEY`` env var, then
        ``/etc/bmt-ai-os/secrets/GOOGLE_API_KEY``.
    base_url:
        Root URL of the Gemini REST API.
    default_model:
        Model used when callers do not specify one.
    default_embed_model:
        Model used for embedding requests when not specified.
    timeout:
        Per-request timeout in seconds.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = _DEFAULT_BASE_URL,
        default_model: str = _DEFAULT_MODEL,
        default_embed_model: str = _DEFAULT_EMBED_MODEL,
        timeout: int = 60,
    ) -> None:
        self._api_key = _resolve_api_key(api_key)
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._default_embed_model = default_embed_model
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    # -- LLMProvider interface ------------------------------------------------

    @property
    def name(self) -> str:  # noqa: D401
        return "gemini"

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stream: bool = False,
    ) -> ChatResponse | AsyncGenerator[str, None]:
        self._require_api_key()
        model = model or self._default_model

        contents, system_instruction = self._convert_messages(messages)
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_instruction:
            payload["systemInstruction"] = system_instruction

        if stream:
            return self._stream_chat(payload, model)

        start = time.perf_counter()
        url = self._model_url(model, ":generateContent")
        data = await self._post(url, payload)
        latency = self._elapsed_ms(start)

        content = self._extract_text(data)
        usage = self._parse_usage(data)

        _LOG.info(
            "gemini chat model=%s prompt=%d completion=%d latency=%.1fms",
            model,
            usage.prompt_tokens,
            usage.completion_tokens,
            latency,
        )

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
        self._require_api_key()
        model = model or self._default_embed_model

        embeddings: list[list[float]] = []
        for text in texts:
            payload: dict[str, Any] = {
                "model": f"models/{model}",
                "content": {"parts": [{"text": text}]},
            }
            url = self._model_url(model, ":embedContent")
            data = await self._post(url, payload)
            embedding = data.get("embedding", {}).get("values")
            if embedding is None:
                raise ProviderError("Gemini returned no embedding values.")
            embeddings.append(embedding)

        _LOG.info("gemini embed model=%s texts=%d", model, len(texts))
        return embeddings

    async def list_models(self) -> list[ModelInfo]:
        self._require_api_key()
        url = f"{self._base_url}/models?key={self._api_key}"
        data = await self._get(url)
        models: list[ModelInfo] = []
        for m in data.get("models", []):
            name = m.get("name", "").removeprefix("models/")
            models.append(
                ModelInfo(
                    name=name,
                    size_bytes=0,
                    family=m.get("displayName", ""),
                )
            )
        return models

    async def health_check(self) -> ProviderHealth:
        start = time.perf_counter()
        try:
            await self.list_models()
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

    # -- Message conversion ---------------------------------------------------

    @staticmethod
    def _convert_messages(
        messages: list[ChatMessage],
    ) -> tuple[list[dict], dict | None]:
        """Convert ChatMessage list to Gemini ``contents`` and optional
        ``systemInstruction``.

        Gemini uses ``role: "user"`` and ``role: "model"`` (not "assistant"),
        and system messages go in a separate ``systemInstruction`` field.
        """
        contents: list[dict] = []
        system_parts: list[dict] = []

        for msg in messages:
            if msg.role == "system":
                system_parts.append({"text": msg.content})
            else:
                role = "model" if msg.role == "assistant" else "user"
                contents.append({
                    "role": role,
                    "parts": [{"text": msg.content}],
                })

        system_instruction = None
        if system_parts:
            system_instruction = {"parts": system_parts}

        return contents, system_instruction

    # -- Internal HTTP helpers ------------------------------------------------

    def _model_url(self, model: str, action: str) -> str:
        return f"{self._base_url}/models/{model}{action}?key={self._api_key}"

    def _require_api_key(self) -> None:
        if not self._api_key:
            raise ProviderError(
                "Gemini API key not configured. Set GOOGLE_API_KEY env var "
                "or write key to /etc/bmt-ai-os/secrets/GOOGLE_API_KEY."
            )

    async def _post(self, url: str, payload: dict) -> dict:
        backoff = _INITIAL_BACKOFF_S
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                async with aiohttp.ClientSession(timeout=self._timeout) as session:
                    async with session.post(url, json=payload) as resp:
                        if resp.status == 404:
                            raise ModelNotFoundError(
                                f"Model not found on Gemini API (404)."
                            )
                        if resp.status == 429:
                            body = await resp.text()
                            _LOG.warning(
                                "gemini rate limited (429), attempt %d/%d, "
                                "retrying in %.1fs: %s",
                                attempt + 1,
                                _MAX_RETRIES + 1,
                                backoff,
                                body[:200],
                            )
                            last_exc = ProviderError(
                                f"Gemini rate limited (429): {body[:200]}"
                            )
                            if attempt < _MAX_RETRIES:
                                await asyncio.sleep(backoff)
                                backoff *= _BACKOFF_MULTIPLIER
                                continue
                            raise last_exc
                        if resp.status != 200:
                            body = await resp.text()
                            raise ProviderError(
                                f"Gemini returned {resp.status}: {body[:500]}"
                            )
                        return await resp.json()
            except aiohttp.ServerTimeoutError as exc:
                raise ProviderTimeoutError(str(exc)) from exc
            except aiohttp.ClientError as exc:
                raise ProviderError(
                    f"Gemini connection error: {exc}"
                ) from exc

        # Should not reach here, but just in case:
        raise last_exc or ProviderError("Gemini request failed after retries.")

    async def _get(self, url: str) -> dict:
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise ProviderError(
                            f"Gemini returned {resp.status}: {body[:500]}"
                        )
                    return await resp.json()
        except aiohttp.ServerTimeoutError as exc:
            raise ProviderTimeoutError(str(exc)) from exc
        except aiohttp.ClientError as exc:
            raise ProviderError(f"Gemini connection error: {exc}") from exc

    async def _stream_chat(
        self,
        payload: dict,
        model: str,
    ) -> AsyncGenerator[str, None]:
        """Yield content chunks from Gemini's SSE streaming response."""
        url = self._model_url(model, ":streamGenerateContent") + "&alt=sse"
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise ProviderError(
                            f"Gemini returned {resp.status}: {body[:500]}"
                        )
                    async for line in resp.content:
                        decoded = line.decode("utf-8") if isinstance(line, bytes) else line
                        decoded = decoded.strip()
                        if not decoded or not decoded.startswith("data: "):
                            continue
                        json_str = decoded[len("data: "):]
                        if json_str == "[DONE]":
                            break
                        try:
                            data = json.loads(json_str)
                        except json.JSONDecodeError:
                            continue
                        chunk = self._extract_text(data)
                        if chunk:
                            yield chunk
        except aiohttp.ClientError as exc:
            raise ProviderError(f"Gemini stream error: {exc}") from exc

    # -- Response helpers -----------------------------------------------------

    @staticmethod
    def _extract_text(data: dict) -> str:
        """Pull the generated text from a Gemini response payload."""
        candidates = data.get("candidates", [])
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts)

    @staticmethod
    def _parse_usage(data: dict) -> TokenUsage:
        """Extract token counts from Gemini ``usageMetadata``."""
        meta = data.get("usageMetadata", {})
        prompt = meta.get("promptTokenCount", 0)
        completion = meta.get("candidatesTokenCount", 0)
        total = meta.get("totalTokenCount", prompt + completion)
        return TokenUsage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
        )

    def build_url(self, path: str) -> str:
        """Return the full URL for a given API *path* (useful for testing)."""
        return f"{self._base_url}{path}"
