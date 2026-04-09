"""Embedding generation via Ollama /api/embed endpoint."""

from __future__ import annotations

import logging

import requests

from .config import RAGConfig

logger = logging.getLogger(__name__)


class OllamaEmbeddings:
    """Generate embeddings using Ollama's ``/api/embed`` endpoint."""

    def __init__(self, config: RAGConfig) -> None:
        self.config = config
        self.base_url = config.ollama_url.rstrip("/")

    def embed(self, text: str) -> list[float]:
        """Return the embedding vector for *text*."""
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return embedding vectors for a batch of texts."""
        url = f"{self.base_url}/api/embed"
        payload = {"model": self.config.embedding_model, "input": texts}
        resp = requests.post(url, json=payload, timeout=self.config.embed_timeout)
        resp.raise_for_status()
        data = resp.json()
        return data["embeddings"]
