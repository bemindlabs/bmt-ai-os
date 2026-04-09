"""RAG pipeline configuration.

Loads settings from /etc/bmt-ai-os/rag.yml, environment variables,
or falls back to sensible defaults for ARM64 on-device operation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import yaml


_DEFAULT_CONFIG_PATH = Path("/etc/bmt-ai-os/rag.yml")


@dataclass
class RAGConfig:
    """Configuration for the RAG ingestion pipeline."""

    # Service endpoints
    chromadb_url: str = "http://localhost:8000"
    ollama_url: str = "http://localhost:11434"

    # Embedding
    embedding_model: str = "nomic-embed-text"
    embedding_dimensions: int = 768

    # Chunking
    chunk_size: int = 512
    chunk_overlap: int = 50

    # Collection
    collection_name: str = "bmt_documents"

    # Ingestion
    supported_extensions: List[str] = field(
        default_factory=lambda: [
            ".txt", ".md", ".py", ".js", ".ts", ".jsx", ".tsx",
            ".c", ".h", ".cpp", ".hpp", ".rs", ".go", ".java",
            ".sh", ".bash", ".zsh", ".yml", ".yaml", ".toml",
            ".json", ".cfg", ".conf", ".ini",
        ]
    )
    batch_size: int = 32
    max_retries: int = 3
    retry_base_delay: float = 1.0

    @classmethod
    def load(cls, path: Path | str | None = None) -> "RAGConfig":
        """Load configuration from YAML file and environment overrides.

        Resolution order (last wins):
        1. Dataclass defaults
        2. YAML file at *path* (or /etc/bmt-ai-os/rag.yml)
        3. Environment variables prefixed with ``BMT_RAG_``
        """
        cfg = cls()

        # --- YAML ----------------------------------------------------------
        config_path = Path(path) if path else _DEFAULT_CONFIG_PATH
        if config_path.is_file():
            with open(config_path) as fh:
                data = yaml.safe_load(fh) or {}
            for key, value in data.items():
                if hasattr(cfg, key):
                    setattr(cfg, key, value)

        # --- Environment overrides -----------------------------------------
        env_map = {
            "BMT_RAG_CHROMADB_URL": "chromadb_url",
            "BMT_RAG_OLLAMA_URL": "ollama_url",
            "BMT_RAG_EMBEDDING_MODEL": "embedding_model",
            "BMT_RAG_EMBEDDING_DIMENSIONS": "embedding_dimensions",
            "BMT_RAG_CHUNK_SIZE": "chunk_size",
            "BMT_RAG_CHUNK_OVERLAP": "chunk_overlap",
            "BMT_RAG_COLLECTION_NAME": "collection_name",
            "BMT_RAG_BATCH_SIZE": "batch_size",
            "BMT_RAG_MAX_RETRIES": "max_retries",
        }
        for env_key, attr in env_map.items():
            env_val = os.environ.get(env_key)
            if env_val is not None:
                current = getattr(cfg, attr)
                if isinstance(current, int):
                    setattr(cfg, attr, int(env_val))
                elif isinstance(current, float):
                    setattr(cfg, attr, float(env_val))
                else:
                    setattr(cfg, attr, env_val)

        return cfg
