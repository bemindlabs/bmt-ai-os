"""BMT AI OS — OpenAI-compatible LLM provider.

``OpenAICompatibleProvider`` is the reusable base for any service that
exposes the OpenAI Chat Completions / Embeddings / Models REST API
(OpenAI, Groq, Mistral, Together, etc.).

``OpenAIProvider`` is the concrete subclass for the OpenAI platform itself.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

import aiohttp

from bmt_ai_os.providers.base import (
    ChatMessage,
    ChatResponse,
    EmbedResponse,
    LLMProvider,
)
from bmt_ai_os.providers.config import get_provider_config, resolve_api_key

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cost tracking helpers
# ---------------------------------------------------------------------------

# Per-million-token pricing (USD).  Provider subclasses override this.
_DEFAULT_PRICING: dict[str, tuple[float, float]] = {}  # model -> (input, output)


class _RequestLog:
    """Lightweight per-request record for cost tracking."""

    __slots__ = ("model", "input_tokens", "output_tokens", "latency_ms", "estimated_cost_usd")

    def __init__(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        estimated_cost_usd: float,
    ) -> None:
        self.model = model
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.latency_ms = latency_ms
        self.estimated_cost_usd = estimated_cost_usd

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": round(self.latency_ms, 1),
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
        }


# ---------------------------------------------------------------------------
# OpenAI-compatible base provider
# ---------------------------------------------------------------------------


class OpenAICompatibleProvider(LLMProvider):
    """Base class for any OpenAI-compatible API endpoint.

    Subclasses only need to set:
      - ``name``
      - ``base_url``
      - ``default_model``
      - ``pricing`` (optional, for cost estimation)
      - ``api_key_env_var``
    """

    name: str = "openai_compatible"
    base_url: str = ""
    default_model: str = ""
    default_embed_model: str = ""
    api_key_env_var: str = ""
    pricing: dict[str, tuple[float, float]] = {}  # model -> ($/M input, $/M output)

    # Retry settings
    max_retries: int = 3
    retry_base_delay: float = 1.0  # seconds

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
        default_embed_model: str | None = None,
        timeout: float = 120.0,
        max_retries: int | None = None,
    ) -> None:
        # Allow overrides via constructor
        if base_url is not None:
            self.base_url = base_url
        if default_model is not None:
            self.default_model = default_model
        if default_embed_model is not None:
            self.default_embed_model = default_embed_model
        if max_retries is not None:
            self.max_retries = max_retries

        # Merge providers.yml config
        cfg = get_provider_config(self.name)
        if not self.base_url and cfg.get("base_url"):
            self.base_url = cfg["base_url"]
        if not self.default_model and cfg.get("default_model"):
            self.default_model = cfg["default_model"]

        # Resolve API key: explicit > env > secrets file
        self._api_key = resolve_api_key(
            key_name=self.api_key_env_var or f"{self.name.upper()}_API_KEY",
            env_var=self.api_key_env_var or None,
            explicit=api_key,
        )

        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None

        # Cost tracking
        self.request_log: list[_RequestLog] = []

    # -- Session management --------------------------------------------------

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    # -- Headers -------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    # -- URL helpers ---------------------------------------------------------

    def _url(self, path: str) -> str:
        base = self.base_url.rstrip("/")
        return f"{base}{path}"

    # -- Retry with exponential backoff -------------------------------------

    async def _request_with_retry(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> aiohttp.ClientResponse:
        """Perform an HTTP request with retry on 429 / 5xx."""
        session = await self._get_session()
        url = self._url(path)
        last_exc: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                resp = await session.request(
                    method,
                    url,
                    headers=self._headers(),
                    json=json_body,
                )
                if resp.status == 429 or resp.status >= 500:
                    retry_after = resp.headers.get("Retry-After")
                    delay = (
                        float(retry_after) if retry_after else self.retry_base_delay * (2**attempt)
                    )
                    logger.warning(
                        "Provider %s returned %d — retrying in %.1fs (attempt %d/%d)",
                        self.name,
                        resp.status,
                        delay,
                        attempt + 1,
                        self.max_retries,
                    )
                    await resp.release()
                    await asyncio.sleep(delay)
                    continue
                return resp
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_exc = exc
                delay = self.retry_base_delay * (2**attempt)
                logger.warning(
                    "Provider %s request error: %s — retrying in %.1fs",
                    self.name,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

        raise ConnectionError(
            f"Provider {self.name}: all {self.max_retries + 1} attempts failed"
        ) from last_exc

    # -- Cost estimation -----------------------------------------------------

    def _estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Return estimated cost in USD from the pricing table."""
        prices = self.pricing.get(model)
        if not prices:
            return 0.0
        cost_in, cost_out = prices  # per million tokens
        return (input_tokens * cost_in + output_tokens * cost_out) / 1_000_000

    def _log_request(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
    ) -> None:
        cost = self._estimate_cost(model, input_tokens, output_tokens)
        entry = _RequestLog(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            estimated_cost_usd=cost,
        )
        self.request_log.append(entry)
        logger.info(
            "Provider %s | model=%s tokens=%d+%d latency=%.0fms cost=$%.6f",
            self.name,
            model,
            input_tokens,
            output_tokens,
            latency_ms,
            cost,
        )

    def total_cost(self) -> float:
        """Cumulative estimated cost (USD) across all logged requests."""
        return sum(r.estimated_cost_usd for r in self.request_log)

    # -- Chat ----------------------------------------------------------------

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
    ) -> ChatResponse | AsyncIterator[str]:
        model = model or self.default_model
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if stream:
            return self._stream_chat(payload, model)
        return await self._non_stream_chat(payload, model)

    async def _non_stream_chat(self, payload: dict[str, Any], model: str) -> ChatResponse:
        t0 = self._now_ms()
        resp = await self._request_with_retry("POST", "/chat/completions", json_body=payload)

        if resp.status != 200:
            body = await resp.text()
            raise RuntimeError(f"Provider {self.name} chat error {resp.status}: {body}")

        data = await resp.json()
        latency = self._now_ms() - t0

        choice = data["choices"][0]
        usage = data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)

        self._log_request(model, input_tokens, output_tokens, latency)

        return ChatResponse(
            content=choice["message"]["content"],
            model=data.get("model", model),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency,
            raw=data,
        )

    async def _stream_chat(self, payload: dict[str, Any], model: str) -> AsyncIterator[str]:
        payload["stream"] = True
        t0 = self._now_ms()
        session = await self._get_session()
        url = self._url("/chat/completions")

        resp = await session.post(url, headers=self._headers(), json=payload)
        if resp.status != 200:
            body = await resp.text()
            raise RuntimeError(f"Provider {self.name} stream error {resp.status}: {body}")

        return self._iter_sse(resp, model, t0)

    async def _iter_sse(
        self,
        resp: aiohttp.ClientResponse,
        model: str,
        t0: float,
    ) -> AsyncIterator[str]:
        """Yield content deltas from an SSE stream."""
        total_output_tokens = 0
        async for line_bytes in resp.content:
            line = line_bytes.decode("utf-8").strip()
            if not line or not line.startswith("data: "):
                continue
            data_str = line[len("data: ") :]
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            delta = chunk.get("choices", [{}])[0].get("delta", {})
            content = delta.get("content")
            if content:
                total_output_tokens += 1  # approximate; real count from final chunk
                yield content

            # Check for usage in final chunk (some providers include it)
            usage = chunk.get("usage")
            if usage:
                self._log_request(
                    model,
                    usage.get("prompt_tokens", 0),
                    usage.get("completion_tokens", total_output_tokens),
                    self._now_ms() - t0,
                )

        latency = self._now_ms() - t0
        # If no usage was provided in the stream, log with estimated tokens
        if not any(r.latency_ms == latency for r in self.request_log):
            self._log_request(model, 0, total_output_tokens, latency)

    # -- Embeddings ----------------------------------------------------------

    async def embed(
        self,
        text: str | list[str],
        *,
        model: str | None = None,
    ) -> EmbedResponse | list[EmbedResponse]:
        model = model or self.default_embed_model or self.default_model
        inputs = [text] if isinstance(text, str) else text

        payload = {
            "model": model,
            "input": inputs,
        }

        t0 = self._now_ms()
        resp = await self._request_with_retry("POST", "/embeddings", json_body=payload)

        if resp.status != 200:
            body = await resp.text()
            raise RuntimeError(f"Provider {self.name} embed error {resp.status}: {body}")

        data = await resp.json()
        latency = self._now_ms() - t0
        usage = data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", usage.get("total_tokens", 0))

        self._log_request(model, input_tokens, 0, latency)

        results = [
            EmbedResponse(
                embedding=item["embedding"],
                model=data.get("model", model),
                input_tokens=input_tokens,
                latency_ms=latency,
            )
            for item in sorted(data["data"], key=lambda d: d["index"])
        ]

        return results[0] if isinstance(text, str) else results

    # -- List models ---------------------------------------------------------

    async def list_models(self) -> list[dict[str, Any]]:
        resp = await self._request_with_retry("GET", "/models")
        if resp.status != 200:
            body = await resp.text()
            raise RuntimeError(f"Provider {self.name} list_models error {resp.status}: {body}")
        data = await resp.json()
        return data.get("data", [])

    # -- Health check --------------------------------------------------------

    async def health_check(self) -> bool:
        try:
            resp = await self._request_with_retry("GET", "/models")
            ok = resp.status == 200
            await resp.release()
            return ok
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Concrete OpenAI provider
# ---------------------------------------------------------------------------

# Pricing as of 2026-Q2 (USD per million tokens)
_OPENAI_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "o3-mini": (1.10, 4.40),
    "text-embedding-3-small": (0.02, 0.0),
    "text-embedding-3-large": (0.13, 0.0),
}


class OpenAIProvider(OpenAICompatibleProvider):
    """OpenAI platform provider (api.openai.com)."""

    name = "openai"
    base_url = "https://api.openai.com/v1"
    default_model = "gpt-4o-mini"
    default_embed_model = "text-embedding-3-small"
    api_key_env_var = "OPENAI_API_KEY"
    pricing = _OPENAI_PRICING
