"""BMT AI OS — RAG Document Ingestion Pipeline.

Reads documents, chunks them, generates embeddings via Ollama,
and stores them in ChromaDB for retrieval-augmented generation.
"""

from .config import RAGConfig
from .ingest import DocumentIngester

__all__ = ["RAGConfig", "DocumentIngester"]
