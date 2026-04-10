"""RAG query engine — end-to-end retrieval-augmented generation."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Generator

from .config import RAGConfig
from .llm import OllamaLLM
from .prompts import render_prompt
from .storage import ChromaStorage

logger = logging.getLogger(__name__)

# Maximum characters of chunk text kept in source attribution.
_CHUNK_PREVIEW_LEN = 200


@dataclass
class SourceAttribution:
    """Describes one retrieved chunk used to generate the answer."""

    filename: str
    chunk_text: str
    relevance_score: float
    position: int

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "chunk": self.chunk_text,
            "score": round(self.relevance_score, 4),
            "position": self.position,
        }


@dataclass
class RAGResponse:
    """Complete response from a RAG query."""

    answer: str
    sources: list[SourceAttribution] = field(default_factory=list)
    latency_ms: float = 0.0
    model_used: str = ""

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "sources": [s.to_dict() for s in self.sources],
            "latency_ms": round(self.latency_ms, 1),
            "model": self.model_used,
        }


class RAGQueryEngine:
    """Orchestrates the full RAG query flow.

    1. Embed the user question.
    2. Retrieve relevant chunks from ChromaDB.
    3. Format a prompt with the retrieved context.
    4. Call Ollama for augmented generation.
    5. Return a ``RAGResponse`` with source attribution.
    """

    def __init__(self, config: RAGConfig | None = None) -> None:
        self.config = config or RAGConfig()
        self.storage = ChromaStorage(self.config)
        self.llm = OllamaLLM(self.config)

    # ------------------------------------------------------------------
    # Synchronous query
    # ------------------------------------------------------------------

    def query(
        self,
        question: str,
        collection: str = "default",
        top_k: int | None = None,
        code_mode: bool = False,
    ) -> RAGResponse:
        """Run a full RAG query and return the augmented answer.

        Parameters
        ----------
        question:
            The user's natural-language question.
        collection:
            ChromaDB collection to search.
        top_k:
            Number of chunks to retrieve (defaults to ``config.top_k``).
        code_mode:
            Use the code-aware prompt template.
        """
        top_k = top_k if top_k is not None else self.config.top_k
        start = time.monotonic()

        # 1. Retrieve
        raw = self.storage.query(collection, question, top_k=top_k)
        chunks, sources = self._parse_results(raw)

        # 2. Build prompt
        prompt = render_prompt(question, chunks, code_mode=code_mode)

        # 3. Generate
        answer = self.llm.generate(prompt)

        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info("RAG query completed in %.0f ms", elapsed_ms)

        return RAGResponse(
            answer=answer,
            sources=sources,
            latency_ms=elapsed_ms,
            model_used=self.config.llm_model,
        )

    # ------------------------------------------------------------------
    # Streaming query
    # ------------------------------------------------------------------

    def query_stream(
        self,
        question: str,
        collection: str = "default",
        top_k: int | None = None,
        code_mode: bool = False,
    ) -> Generator[str | RAGResponse, None, None]:
        """Stream tokens from the LLM, then yield a final ``RAGResponse``.

        Yields
        ------
        str
            Individual tokens as they arrive from Ollama.
        RAGResponse
            A final metadata object (``answer`` is the full concatenated text).
        """
        top_k = top_k if top_k is not None else self.config.top_k
        start = time.monotonic()

        raw = self.storage.query(collection, question, top_k=top_k)
        chunks, sources = self._parse_results(raw)
        prompt = render_prompt(question, chunks, code_mode=code_mode)

        tokens: list[str] = []
        for token in self.llm.generate(prompt, stream=True):
            tokens.append(token)
            yield token

        elapsed_ms = (time.monotonic() - start) * 1000
        yield RAGResponse(
            answer="".join(tokens),
            sources=sources,
            latency_ms=elapsed_ms,
            model_used=self.config.llm_model,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_results(
        raw: dict,
    ) -> tuple[list[dict], list[SourceAttribution]]:
        """Convert raw ChromaDB response into chunk dicts and source objects."""
        chunks: list[dict] = []
        sources: list[SourceAttribution] = []

        # ChromaDB wraps results in outer lists (one per query embedding).
        ids = (raw.get("ids") or [[]])[0]
        documents = (raw.get("documents") or [[]])[0]
        metadatas = (raw.get("metadatas") or [[]])[0]
        distances = (raw.get("distances") or [[]])[0]

        for idx, (doc_id, text, meta, dist) in enumerate(zip(ids, documents, metadatas, distances)):
            meta = meta or {}
            filename = meta.get("filename", doc_id)
            chunks.append({"text": text, "filename": filename})
            sources.append(
                SourceAttribution(
                    filename=filename,
                    chunk_text=text[:_CHUNK_PREVIEW_LEN],
                    relevance_score=1.0 - dist,  # distance → similarity
                    position=idx,
                )
            )

        return chunks, sources
