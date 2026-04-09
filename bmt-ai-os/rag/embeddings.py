"""Ollama embedding client with batching and retry logic.

Wraps the Ollama ``/api/embed`` endpoint to generate vector embeddings
for document chunks.  Includes exponential back-off for transient errors
and dimension validation.
"""

from __future__ import annotations

import logging
import time
from typing import List

import requests

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    """Raised when embedding generation fails after retries."""


class OllamaEmbeddings:
    """Generate embeddings via the Ollama HTTP API."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "nomic-embed-text",
        expected_dimensions: int = 768,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.expected_dimensions = expected_dimensions
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts.

        Uses the Ollama ``/api/embed`` endpoint which accepts multiple
        inputs in a single call for efficiency.

        Returns a list of embedding vectors (one per input text).

        Raises:
            EmbeddingError: if all retry attempts fail.
        """
        if not texts:
            return []

        url = f"{self.base_url}/api/embed"
        payload = {"model": self.model, "input": texts}

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.post(url, json=payload, timeout=self.timeout)
                resp.raise_for_status()
                data = resp.json()

                embeddings: List[List[float]] = data.get("embeddings", [])
                if len(embeddings) != len(texts):
                    raise EmbeddingError(
                        f"Expected {len(texts)} embeddings, got {len(embeddings)}"
                    )

                # Validate dimensions on first vector
                if embeddings and len(embeddings[0]) != self.expected_dimensions:
                    logger.warning(
                        "Embedding dimension mismatch: expected %d, got %d. "
                        "Updating expected_dimensions.",
                        self.expected_dimensions,
                        len(embeddings[0]),
                    )
                    self.expected_dimensions = len(embeddings[0])

                return embeddings

            except (requests.RequestException, KeyError, EmbeddingError) as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    delay = self.retry_base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        "Embedding attempt %d/%d failed (%s), retrying in %.1fs",
                        attempt, self.max_retries, exc, delay,
                    )
                    time.sleep(delay)

        raise EmbeddingError(
            f"Failed to generate embeddings after {self.max_retries} attempts"
        ) from last_exc

    def embed_single(self, text: str) -> List[float]:
        """Convenience wrapper for a single text input."""
        return self.embed([text])[0]
