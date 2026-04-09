"""RAG pipeline configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class RAGConfig:
    """Configuration for the RAG pipeline.

    All values can be overridden via environment variables prefixed with
    ``BMT_RAG_`` (e.g. ``BMT_RAG_CHROMADB_URL``).
    """

    # Service endpoints
    chromadb_url: str = field(
        default_factory=lambda: os.getenv("BMT_RAG_CHROMADB_URL", "http://localhost:8000")
    )
    ollama_url: str = field(
        default_factory=lambda: os.getenv("BMT_RAG_OLLAMA_URL", "http://localhost:11434")
    )

    # Embedding settings
    embedding_model: str = field(
        default_factory=lambda: os.getenv("BMT_RAG_EMBEDDING_MODEL", "nomic-embed-text")
    )

    # Chunking settings
    chunk_size: int = 512
    chunk_overlap: int = 64

    # Query settings
    top_k: int = 5

    # LLM settings
    llm_model: str = field(
        default_factory=lambda: os.getenv(
            "BMT_RAG_LLM_MODEL", "qwen2.5-coder:7b-instruct-q4_K_M"
        )
    )
    temperature: float = 0.7
    top_p: float = 0.9
    max_tokens: int = 2048

    # Optional custom prompt template path
    prompt_template: str | None = None

    # Timeouts (seconds)
    llm_timeout: int = 120
    embed_timeout: int = 30
