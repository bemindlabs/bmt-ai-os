"""Anthropic Claude provider — cloud LLM backend with tool use and streaming."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, AsyncGenerator

import aiohttp

from bmt_ai_os.providers.base import (
    ChatMessage,
    ChatResponse,
    LLMProvider,
    ModelInfo,
    ProviderError,
    ProviderHealth,
    ProviderTimeoutError,
    TokenUsage,
)

logger = logging.getLogger(__name__)

_API_BASE_URL = "https://api.anthropic.com"
_DEFAULT_MODEL = "claude-sonnet-4-20250514"
_API_VERSION = "2023-06-01"
_SECRETS_PATH = "/etc/bmt_ai_os/secrets/ANTHROPIC_API_KEY"

# Cost per million tokens (USD) — used for request logging.
_COST_PER_M_TOKENS: dict[str, dict[str, float]] = {
    "claude-opus-4-20250514": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-haiku-3.5-20241022": {"input": 0.80, "output": 4.0},
}

# Hardcoded model catalogue — Anthropic has no public list-models endpoint.
_CLAUDE_MODELS = [
    ModelInfo(name="claude-opus-4-20250514", family="claude"),
    ModelInfo(name="claude-sonnet-4-20250514", family="claude"),
    ModelInfo(name="claude-haiku-3.5-20241022", family="claude"),
]

_MAX_RETRIES = 3


class RateLimitError(ProviderError):
    """Raised when the Anthropic API returns 429 — rate limited."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class AnthropicProvider(LLMProvider):
    """Provider for the Anthropic Messages API (Claude).

    Parameters
    ----------
    base_url:
        Root URL of the Anthropic API.
    api_key:
        API key. Resolved in order: explicit value, ``ANTHROPIC_API_KEY`` env
        var, secrets file at ``/etc/bmt_ai_os/secrets/ANTHROPIC_API_KEY``.
    default_model:
        Model to use when callers do not specify one.
    timeout:
        Per-request timeout in seconds.
    """

    def __init__(
        self,
        *,
        base_url: str = _API_BASE_URL,
        api_key: str = "",
        default_model: str = _DEFAULT_MODEL,
        timeout: int = 60,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key or self._resolve_api_key()
        self._default_model = default_model
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    # -- LLMProvider interface ------------------------------------------------

    @property
    def name(self) -> str:  # noqa: D401
        return "anthropic"

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
        system_prompt, api_messages = self._convert_messages(messages)

        payload: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_prompt:
            payload["system"] = system_prompt

        if stream:
            payload["stream"] = True
            return self._stream_chat(payload, model)

        start = time.perf_counter()
        data = await self._post("/v1/messages", payload)
        latency = self._elapsed_ms(start)

        content = self._extract_text(data)
        usage = self._parse_usage(data)
        self._log_cost(model, usage)

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
        raise ProviderError(
            "Anthropic does not offer embeddings — "
            "use a local provider (Ollama) or another cloud provider for embeddings."
        )

    async def list_models(self) -> list[ModelInfo]:
        return list(_CLAUDE_MODELS)

    async def health_check(self) -> ProviderHealth:
        """Verify key validity with a minimal messages request."""
        start = time.perf_counter()
        try:
            await self._post(
                "/v1/messages",
                {
                    "model": self._default_model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                },
            )
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
    ) -> tuple[str, list[dict[str, str]]]:
        """Separate system prompt from user/assistant messages.

        Anthropic requires the system prompt as a top-level ``system`` field,
        not as a message with ``role: system``.

        Returns ``(system_prompt, api_messages)``.
        """
        system_parts: list[str] = []
        api_messages: list[dict[str, str]] = []
        for msg in messages:
            if msg.role == "system":
                system_parts.append(msg.content)
            else:
                api_messages.append({"role": msg.role, "content": msg.content})
        return "\n\n".join(system_parts), api_messages

    # -- Streaming ------------------------------------------------------------

    async def _stream_chat(
        self,
        payload: dict,
        model: str,
    ) -> AsyncGenerator[str, None]:
        """Yield content chunks from Anthropic's SSE streaming response."""
        url = f"{self._base_url}/v1/messages"
        headers = self._headers()
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status == 429:
                        retry_after = self._parse_retry_after(resp)
                        raise RateLimitError(
                            "Rate limited by Anthropic API",
                            retry_after=retry_after,
                        )
                    if resp.status != 200:
                        body = await resp.text()
                        raise ProviderError(f"Anthropic returned {resp.status}: {body}")
                    async for line in resp.content:
                        decoded = line.decode("utf-8", errors="replace").strip()
                        if not decoded or not decoded.startswith("data: "):
                            continue
                        json_str = decoded[len("data: ") :]
                        if json_str == "[DONE]":
                            break
                        try:
                            event = json.loads(json_str)
                        except json.JSONDecodeError:
                            continue
                        if event.get("type") == "content_block_delta":
                            delta = event.get("delta", {})
                            text = delta.get("text", "")
                            if text:
                                yield text
        except aiohttp.ClientError as exc:
            raise ProviderError(f"Anthropic stream error: {exc}") from exc

    # -- HTTP helpers ---------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "anthropic-version": _API_VERSION,
            "content-type": "application/json",
        }

    async def _post(self, path: str, payload: dict) -> dict:
        """POST with automatic retry on rate-limit (429)."""
        url = f"{self._base_url}{path}"
        headers = self._headers()
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                async with aiohttp.ClientSession(timeout=self._timeout) as session:
                    async with session.post(url, json=payload, headers=headers) as resp:
                        if resp.status == 429:
                            retry_after = self._parse_retry_after(resp)
                            last_exc = RateLimitError(
                                f"Rate limited (attempt {attempt + 1}/{_MAX_RETRIES})",
                                retry_after=retry_after,
                            )
                            wait = retry_after if retry_after else (2**attempt)
                            logger.warning(
                                "Anthropic 429 — retrying in %.1fs (attempt %d/%d)",
                                wait,
                                attempt + 1,
                                _MAX_RETRIES,
                            )
                            import asyncio

                            await asyncio.sleep(wait)
                            continue
                        if resp.status == 401:
                            raise ProviderError("Anthropic authentication failed — check API key")
                        if resp.status != 200:
                            body = await resp.text()
                            raise ProviderError(f"Anthropic returned {resp.status}: {body}")
                        return await resp.json()
            except aiohttp.ServerTimeoutError as exc:
                raise ProviderTimeoutError(str(exc)) from exc
            except aiohttp.ClientError as exc:
                raise ProviderError(f"Anthropic connection error: {exc}") from exc

        # All retries exhausted.
        raise last_exc or ProviderError("Anthropic request failed after retries")

    # -- Helpers --------------------------------------------------------------

    @staticmethod
    def _resolve_api_key() -> str:
        """Resolve API key from environment or secrets file."""
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if key:
            return key
        secrets_path = Path(_SECRETS_PATH)
        if secrets_path.is_file():
            return secrets_path.read_text().strip()
        return ""

    @staticmethod
    def _parse_retry_after(resp: aiohttp.ClientResponse) -> float | None:
        """Extract ``retry-after`` header value as seconds."""
        raw = resp.headers.get("retry-after")
        if raw is None:
            return None
        try:
            return float(raw)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _extract_text(data: dict) -> str:
        """Extract text content from an Anthropic Messages API response."""
        parts: list[str] = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)

    @staticmethod
    def _parse_usage(data: dict) -> TokenUsage:
        usage = data.get("usage", {})
        prompt = usage.get("input_tokens", 0)
        completion = usage.get("output_tokens", 0)
        return TokenUsage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
        )

    @staticmethod
    def _log_cost(model: str, usage: TokenUsage) -> None:
        """Log estimated cost for the request."""
        rates = _COST_PER_M_TOKENS.get(model)
        if not rates:
            logger.debug(
                "Anthropic request: %d input, %d output tokens (no cost data for %s)",
                usage.prompt_tokens,
                usage.completion_tokens,
                model,
            )
            return
        input_cost = (usage.prompt_tokens / 1_000_000) * rates["input"]
        output_cost = (usage.completion_tokens / 1_000_000) * rates["output"]
        total_cost = input_cost + output_cost
        logger.info(
            "Anthropic request: %d input, %d output tokens — est. $%.6f (model=%s)",
            usage.prompt_tokens,
            usage.completion_tokens,
            total_cost,
            model,
        )

    def build_url(self, path: str) -> str:
        """Return the full URL for a given API *path* (useful for testing)."""
        return f"{self._base_url}{path}"
