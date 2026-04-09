"""ChromaDB storage interface for the RAG pipeline."""

from __future__ import annotations

import logging
from typing import Any

import requests

from .config import RAGConfig
from .embeddings import OllamaEmbeddings

logger = logging.getLogger(__name__)


class ChromaStorage:
    """Interact with a ChromaDB instance over its REST API.

    Uses the v1 REST API so that no heavy native client library is needed on
    ARM64 targets.
    """

    def __init__(self, config: RAGConfig) -> None:
        self.config = config
        self.base_url = config.chromadb_url.rstrip("/")
        self.embeddings = OllamaEmbeddings(config)

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------

    def list_collections(self) -> list[dict[str, Any]]:
        """Return metadata for all collections."""
        resp = requests.get(
            f"{self.base_url}/api/v1/collections", timeout=10
        )
        resp.raise_for_status()
        return resp.json()

    def get_or_create_collection(self, name: str) -> str:
        """Ensure a collection exists and return its id."""
        url = f"{self.base_url}/api/v1/collections"
        payload = {"name": name, "get_or_create": True}
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()["id"]

    # ------------------------------------------------------------------
    # Upsert
    # ------------------------------------------------------------------

    def upsert(
        self,
        collection: str,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict] | None = None,
    ) -> None:
        """Batch-upsert documents with their embeddings."""
        col_id = self.get_or_create_collection(collection)
        vectors = self.embeddings.embed_batch(documents)
        url = f"{self.base_url}/api/v1/collections/{col_id}/upsert"
        payload: dict[str, Any] = {
            "ids": ids,
            "documents": documents,
            "embeddings": vectors,
        }
        if metadatas:
            payload["metadatas"] = metadatas
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        logger.info("Upserted %d chunks into collection %s", len(ids), collection)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query(
        self,
        collection: str,
        query_text: str,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """Query a collection and return top-k results.

        Returns the raw ChromaDB response dict with keys ``ids``,
        ``documents``, ``metadatas``, ``distances``.
        """
        col_id = self.get_or_create_collection(collection)
        query_embedding = self.embeddings.embed(query_text)
        url = f"{self.base_url}/api/v1/collections/{col_id}/query"
        payload = {
            "query_embeddings": [query_embedding],
            "n_results": top_k,
            "include": ["documents", "metadatas", "distances"],
        }
        resp = requests.post(url, json=payload, timeout=self.config.embed_timeout)
        resp.raise_for_status()
        return resp.json()
