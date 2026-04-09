"""ChromaDB storage interface for RAG chunks.

Provides collection management, batch upsert, and a query interface
for retrieval-augmented generation.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings

logger = logging.getLogger(__name__)


class ChromaStorage:
    """Thin wrapper around the ChromaDB HTTP client."""

    def __init__(
        self,
        url: str = "http://localhost:8000",
        collection_name: str = "bmt_documents",
    ) -> None:
        host, port = self._parse_url(url)
        self._client = chromadb.HttpClient(
            host=host,
            port=port,
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection_name = collection_name
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------

    def list_collections(self) -> List[str]:
        """Return names of all collections."""
        return [c.name for c in self._client.list_collections()]

    def delete_collection(self, name: str | None = None) -> None:
        """Delete a collection by name (defaults to current)."""
        target = name or self._collection_name
        self._client.delete_collection(target)
        if target == self._collection_name:
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )

    @property
    def count(self) -> int:
        """Number of documents in the active collection."""
        return self._collection.count()

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def upsert(
        self,
        ids: List[str],
        embeddings: List[List[float]],
        documents: List[str],
        metadatas: List[Dict[str, Any]],
    ) -> None:
        """Batch upsert chunks into the collection."""
        self._collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

    def upsert_batch(
        self,
        ids: List[str],
        embeddings: List[List[float]],
        documents: List[str],
        metadatas: List[Dict[str, Any]],
        batch_size: int = 64,
    ) -> None:
        """Upsert in fixed-size batches for memory-constrained devices."""
        for start in range(0, len(ids), batch_size):
            end = start + batch_size
            self.upsert(
                ids=ids[start:end],
                embeddings=embeddings[start:end],
                documents=documents[start:end],
                metadatas=metadatas[start:end],
            )

    # ------------------------------------------------------------------
    # Query (for BMTOS-5b and beyond)
    # ------------------------------------------------------------------

    def query(
        self,
        query_embeddings: List[List[float]],
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Query the collection by embedding similarity."""
        kwargs: Dict[str, Any] = {
            "query_embeddings": query_embeddings,
            "n_results": n_results,
        }
        if where:
            kwargs["where"] = where
        return self._collection.query(**kwargs)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_url(url: str) -> tuple:
        """Extract host and port from an HTTP URL."""
        url = url.rstrip("/")
        if "://" in url:
            url = url.split("://", 1)[1]
        if ":" in url:
            host, port_str = url.rsplit(":", 1)
            return host, int(port_str)
        return url, 8000
