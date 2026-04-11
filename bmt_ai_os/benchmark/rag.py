"""RAG benchmark — measures end-to-end query latency (embed + retrieve + generate).

The benchmark seeds a temporary ChromaDB collection with synthetic documents,
runs a query against it, and records timings for each stage.  The collection is
cleaned up after each run so repeated runs do not accumulate stale data.

All timing uses ``time.perf_counter()`` for sub-millisecond resolution.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

_DEFAULT_OLLAMA_URL = "http://localhost:11434"
_DEFAULT_CHROMADB_URL = "http://localhost:8000"
_DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
_DEFAULT_LLM_MODEL = "qwen2.5:0.5b"

# Synthetic corpus: short documents covering BMT AI OS topics.
_SYNTHETIC_DOCS = [
    "BMT AI OS is an ARM64-first operating system designed for on-device AI inference.",
    "Ollama provides a local REST API for running large language models on ARM64 hardware.",
    "ChromaDB is an open-source vector database used for semantic search and RAG pipelines.",
    "The Qwen family of models delivers state-of-the-art coding performance in 2026.",
    "Retrieval-Augmented Generation (RAG) combines vector search with LLM generation.",
    "Apple Silicon chips offer the fastest CPU-based inference among ARM64 platforms.",
    "Jetson Orin Nano Super supports CUDA-accelerated inference for embedded AI workloads.",
    "The RK3588 SoC includes an NPU capable of accelerating INT8 neural network inference.",
    "Pi 5 with the Hailo AI HAT+ achieves up to 26 TOPS for edge AI applications.",
    "OpenRC manages service startup order on the BMT AI OS minimal Linux base.",
]

_BENCH_QUESTION = "What is BMT AI OS and which hardware platforms does it support?"


@dataclass
class RAGResult:
    """Results from a single RAG benchmark run."""

    model: str
    embedding_model: str
    embed_ms: float
    retrieve_ms: float
    generate_ms: float
    total_ms: float
    retrieved_docs: int

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "embedding_model": self.embedding_model,
            "embed_ms": round(self.embed_ms, 1),
            "retrieve_ms": round(self.retrieve_ms, 1),
            "generate_ms": round(self.generate_ms, 1),
            "total_ms": round(self.total_ms, 1),
            "retrieved_docs": self.retrieved_docs,
        }


def run(
    model: str = _DEFAULT_LLM_MODEL,
    embedding_model: str = _DEFAULT_EMBEDDING_MODEL,
    ollama_url: str = _DEFAULT_OLLAMA_URL,
    chromadb_url: str = _DEFAULT_CHROMADB_URL,
    top_k: int = 3,
    question: str = _BENCH_QUESTION,
) -> RAGResult:
    """Benchmark RAG query latency and return a :class:`RAGResult`.

    Parameters
    ----------
    model:
        Ollama LLM model tag for the generation step.
    embedding_model:
        Ollama model used to generate embeddings.
    ollama_url:
        Base URL of the Ollama service.
    chromadb_url:
        Base URL of the ChromaDB service.
    top_k:
        Number of chunks to retrieve from ChromaDB.
    question:
        Query text to benchmark.
    """
    ollama_base = ollama_url.rstrip("/")
    chroma_base = chromadb_url.rstrip("/")

    collection_name = f"bmt-bench-{uuid.uuid4().hex[:8]}"

    try:
        # Seed the collection.
        collection_id = _create_collection(chroma_base, collection_name)
        doc_embeddings = _embed_batch(ollama_base, embedding_model, _SYNTHETIC_DOCS)
        _upsert_docs(chroma_base, collection_id, _SYNTHETIC_DOCS, doc_embeddings)

        # --- Stage 1: embed query ---
        t0 = time.perf_counter()
        query_embedding = _embed_single(ollama_base, embedding_model, question)
        t1 = time.perf_counter()
        embed_ms = (t1 - t0) * 1000

        # --- Stage 2: retrieve from ChromaDB ---
        chunks = _retrieve(chroma_base, collection_id, query_embedding, top_k)
        t2 = time.perf_counter()
        retrieve_ms = (t2 - t1) * 1000

        # --- Stage 3: generate with Ollama ---
        context = "\n".join(f"- {c}" for c in chunks)
        prompt = (
            f"Context:\n{context}\n\n"
            f"Question: {question}\n\n"
            "Answer concisely based only on the context above."
        )
        _generate(ollama_base, model, prompt)
        t3 = time.perf_counter()
        generate_ms = (t3 - t2) * 1000
        total_ms = (t3 - t0) * 1000

    finally:
        _delete_collection(chroma_base, collection_name)

    return RAGResult(
        model=model,
        embedding_model=embedding_model,
        embed_ms=embed_ms,
        retrieve_ms=retrieve_ms,
        generate_ms=generate_ms,
        total_ms=total_ms,
        retrieved_docs=len(chunks),
    )


# ---------------------------------------------------------------------------
# Internal helpers — ChromaDB
# ---------------------------------------------------------------------------


def _create_collection(base_url: str, name: str) -> str:
    """Create a collection and return its id."""
    url = f"{base_url}/api/v1/collections"
    resp = requests.post(url, json={"name": name, "get_or_create": True}, timeout=10)
    resp.raise_for_status()
    return resp.json()["id"]


def _upsert_docs(
    base_url: str,
    collection_id: str,
    documents: list[str],
    embeddings: list[list[float]],
) -> None:
    """Upsert documents and their pre-computed embeddings into ChromaDB."""
    ids = [f"doc-{i}" for i in range(len(documents))]
    url = f"{base_url}/api/v1/collections/{collection_id}/upsert"
    payload = {"ids": ids, "documents": documents, "embeddings": embeddings}
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()


def _retrieve(
    base_url: str,
    collection_id: str,
    query_embedding: list[float],
    top_k: int,
) -> list[str]:
    """Query ChromaDB and return the top-k document strings."""
    url = f"{base_url}/api/v1/collections/{collection_id}/query"
    payload = {
        "query_embeddings": [query_embedding],
        "n_results": top_k,
        "include": ["documents"],
    }
    resp = requests.post(url, json=payload, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    # ChromaDB wraps results in outer lists (one per query).
    docs = (data.get("documents") or [[]])[0]
    return docs


def _delete_collection(base_url: str, name: str) -> None:
    """Delete a collection by name (best-effort; swallows errors)."""
    try:
        resp = requests.delete(f"{base_url}/api/v1/collections/{name}", timeout=5)
        resp.raise_for_status()
    except Exception:
        logger.debug("Could not delete benchmark collection %s", name)


# ---------------------------------------------------------------------------
# Internal helpers — Ollama embeddings
# ---------------------------------------------------------------------------


def _embed_single(base_url: str, model: str, text: str) -> list[float]:
    """Return the embedding vector for a single text."""
    return _embed_batch(base_url, model, [text])[0]


def _embed_batch(base_url: str, model: str, texts: list[str]) -> list[list[float]]:
    """Return embedding vectors for a list of texts."""
    url = f"{base_url}/api/embed"
    resp = requests.post(url, json={"model": model, "input": texts}, timeout=60)
    resp.raise_for_status()
    return resp.json()["embeddings"]


# ---------------------------------------------------------------------------
# Internal helpers — Ollama generation
# ---------------------------------------------------------------------------


def _generate(base_url: str, model: str, prompt: str) -> str:
    """Run a non-streaming generation and return the full response text."""
    url = f"{base_url}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 256},
    }
    resp = requests.post(url, json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json().get("response", "")
