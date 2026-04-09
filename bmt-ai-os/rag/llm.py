"""Ollama LLM interface for the RAG pipeline."""

from __future__ import annotations

import json
import logging
import time
from typing import Generator

import requests

from .config import RAGConfig

logger = logging.getLogger(__name__)


class OllamaLLM:
    """Thin wrapper around the Ollama ``/api/chat`` endpoint.

    Supports both synchronous (full response) and streaming generation.
    """

    def __init__(self, config: RAGConfig) -> None:
        self.config = config
        self.base_url = config.ollama_url.rstrip("/")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        stream: bool = False,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
    ) -> str | Generator[str, None, None]:
        """Generate a response from the LLM.

        Parameters
        ----------
        prompt:
            The fully rendered prompt (system + context + question).
        model:
            Override the configured model name.
        stream:
            If *True*, return a generator that yields tokens as they arrive.
        temperature, top_p, max_tokens:
            Override sampling parameters for this call.

        Returns
        -------
        str | Generator[str, None, None]
            Full text when *stream* is False; token generator otherwise.
        """
        model = model or self.config.llm_model
        temperature = temperature if temperature is not None else self.config.temperature
        top_p = top_p if top_p is not None else self.config.top_p
        max_tokens = max_tokens if max_tokens is not None else self.config.max_tokens

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": stream,
            "options": {
                "temperature": temperature,
                "top_p": top_p,
                "num_predict": max_tokens,
            },
        }

        if stream:
            return self._stream(payload)
        return self._complete(payload)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _complete(self, payload: dict) -> str:
        """Non-streaming completion."""
        start = time.monotonic()
        url = f"{self.base_url}/api/chat"
        resp = requests.post(url, json=payload, timeout=self.config.llm_timeout)
        resp.raise_for_status()
        elapsed_ms = (time.monotonic() - start) * 1000
        data = resp.json()
        text = data.get("message", {}).get("content", "")
        logger.info("LLM complete in %.0f ms  model=%s", elapsed_ms, payload["model"])
        return text

    def _stream(self, payload: dict) -> Generator[str, None, None]:
        """Streaming completion via Server-Sent Events (NDJSON)."""
        url = f"{self.base_url}/api/chat"
        start = time.monotonic()
        with requests.post(
            url, json=payload, stream=True, timeout=self.config.llm_timeout
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                chunk = json.loads(line)
                token = chunk.get("message", {}).get("content", "")
                if token:
                    yield token
                if chunk.get("done"):
                    break
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info("LLM stream in %.0f ms  model=%s", elapsed_ms, payload["model"])
