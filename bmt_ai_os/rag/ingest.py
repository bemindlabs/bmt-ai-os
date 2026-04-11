"""Main document ingestion pipeline.

Reads files from disk, chunks them using type-appropriate strategies,
generates embeddings via Ollama, and stores everything in ChromaDB.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Set

from .chunker import (
    Chunk,
    CodeChunker,
    MarkdownChunker,
    TextChunker,
    _guess_language,
)
from .config import RAGConfig
from .embeddings import OllamaEmbeddings
from .storage import ChromaStorage

logger = logging.getLogger(__name__)

# Extensions considered "code" for chunker selection
_CODE_EXTENSIONS: Set[str] = {
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".rs",
    ".go",
    ".java",
    ".sh",
    ".bash",
    ".zsh",
}


class DocumentIngester:
    """Orchestrates end-to-end document ingestion into ChromaDB."""

    def __init__(self, config: RAGConfig | None = None) -> None:
        self.config = config or RAGConfig.load()
        self._embeddings = OllamaEmbeddings(
            base_url=self.config.ollama_url,
            model=self.config.embedding_model,
            expected_dimensions=self.config.embedding_dimensions,
            max_retries=self.config.max_retries,
            retry_base_delay=self.config.retry_base_delay,
        )
        self._storage = ChromaStorage(
            url=self.config.chromadb_url,
            collection_name=self.config.collection_name,
        )
        self._text_chunker = TextChunker(self.config.chunk_size, self.config.chunk_overlap)
        self._md_chunker = MarkdownChunker(self.config.chunk_size, self.config.chunk_overlap)
        self._code_chunker = CodeChunker(self.config.chunk_size, self.config.chunk_overlap)

        # Track ingested file hashes for duplicate detection
        self._ingested_hashes: Set[str] = set()

        # Workspace root for path traversal checks.  Defaults to cwd so that
        # all ingested paths must live inside the process working directory.
        # Override via the BMT_RAG_WORKSPACE env var in production.
        workspace = os.environ.get("BMT_RAG_WORKSPACE", "")
        self._workspace_root: Path | None = Path(workspace).resolve() if workspace else None

    # ------------------------------------------------------------------
    # Path validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_path(path: Path, workspace_root: Path | None = None) -> None:
        """Raise ValueError if *path* contains a traversal attempt.

        Two checks are applied:
        1. The raw string must not contain ``..`` components — this catches
           obvious traversal strings like ``../../etc/passwd`` before any
           resolution.
        2. When *workspace_root* is set, the resolved absolute path must be
           inside (or equal to) the workspace root.

        Args:
            path: The candidate path to validate.
            workspace_root: Optional resolved absolute directory that all paths
                must reside within.  Pass ``None`` to skip the containment check.

        Raises:
            ValueError: When a traversal attempt is detected.
        """
        # Reject raw ".." path components
        parts = Path(path).parts
        if ".." in parts:
            raise ValueError(
                f"Path traversal detected: '{path}' contains '..' components. "
                "Absolute or resolved paths are required."
            )

        # Reject paths whose string representation contains ".." anywhere
        # (catches cases like "foo/../../bar" that might slip past parts check)
        raw = str(path)
        if ".." in raw:
            raise ValueError(f"Path traversal detected: '{path}' contains '..' sequence.")

        # Workspace containment check
        if workspace_root is not None:
            try:
                resolved = path.resolve()
            except OSError:
                # If we cannot resolve the path, reject it for safety
                raise ValueError(f"Cannot resolve path '{path}' for traversal check.")

            try:
                resolved.relative_to(workspace_root)
            except ValueError:
                raise ValueError(
                    f"Path '{path}' resolves to '{resolved}' which is outside the "
                    f"allowed workspace root '{workspace_root}'."
                )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest_file(self, path: str | Path) -> int:
        """Ingest a single file. Returns number of chunks stored."""
        path = Path(path)

        try:
            self._validate_path(path, getattr(self, "_workspace_root", None))
        except ValueError as exc:
            logger.error("Rejected path due to traversal check: %s", exc)
            return 0

        if not path.is_file():
            logger.warning("Skipping non-file path: %s", path)
            return 0

        if path.suffix not in self.config.supported_extensions:
            logger.info("Skipping unsupported extension: %s", path.suffix)
            return 0

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.error("Cannot read %s: %s", path, exc)
            return 0

        # Duplicate detection via content hash
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        if content_hash in self._ingested_hashes:
            logger.info("Skipping duplicate: %s", path)
            return 0

        chunks = self._chunk_file(content, str(path))
        if not chunks:
            return 0

        self._store_chunks(chunks, content_hash)
        self._ingested_hashes.add(content_hash)

        logger.info("Ingested %s (%d chunks)", path, len(chunks))
        return len(chunks)

    def ingest_directory(
        self,
        path: str | Path,
        recursive: bool = True,
        patterns: Optional[List[str]] = None,
    ) -> Dict[str, int]:
        """Ingest all matching files in a directory.

        Returns a dict mapping file paths to chunk counts, plus a
        special ``_errors`` key with the count of failed files.
        """
        path = Path(path)

        try:
            self._validate_path(path, getattr(self, "_workspace_root", None))
        except ValueError as exc:
            logger.error("Rejected directory due to traversal check: %s", exc)
            return {"_errors": 1}

        if not path.is_dir():
            logger.error("Not a directory: %s", path)
            return {"_errors": 1}

        if patterns is None:
            patterns = [f"*{ext}" for ext in self.config.supported_extensions]

        files: List[Path] = []
        for pattern in patterns:
            if recursive:
                files.extend(path.rglob(pattern))
            else:
                files.extend(path.glob(pattern))

        # Deduplicate and sort for deterministic order
        files = sorted(set(files))

        results: Dict[str, int] = {"_total": 0, "_errors": 0}
        for i, filepath in enumerate(files, 1):
            logger.info("Processing [%d/%d]: %s", i, len(files), filepath)
            try:
                count = self.ingest_file(filepath)
                results[str(filepath)] = count
                results["_total"] += count
            except Exception:
                logger.exception("Failed to ingest %s", filepath)
                results["_errors"] += 1

        logger.info(
            "Ingestion complete: %d files, %d chunks, %d errors",
            len(files),
            results["_total"],
            results["_errors"],
        )
        return results

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _chunk_file(self, content: str, source: str) -> List[Chunk]:
        """Choose the right chunker based on file type."""
        if source.endswith(".md"):
            return self._md_chunker.chunk(content, source)
        if any(source.endswith(ext) for ext in _CODE_EXTENSIONS):
            language = _guess_language(source)
            return self._code_chunker.chunk(content, source, language)
        return self._text_chunker.chunk(content, source)

    def _store_chunks(self, chunks: List[Chunk], content_hash: str) -> None:
        """Embed chunks and upsert into ChromaDB."""
        texts = [c.text for c in chunks]

        # Batch embed
        all_embeddings: List[List[float]] = []
        for start in range(0, len(texts), self.config.batch_size):
            batch = texts[start : start + self.config.batch_size]
            all_embeddings.extend(self._embeddings.embed(batch))

        ids: List[str] = []
        metadatas: List[Dict] = []
        for chunk in chunks:
            chunk_id = hashlib.sha256(
                f"{content_hash}:{chunk.chunk_index}:{chunk.start_char}".encode()
            ).hexdigest()[:24]
            ids.append(chunk_id)
            meta = {
                "source": chunk.source,
                "chunk_index": chunk.chunk_index,
                "start_char": chunk.start_char,
                "end_char": chunk.end_char,
                "content_hash": content_hash,
            }
            meta.update(chunk.metadata)
            metadatas.append(meta)

        self._storage.upsert_batch(
            ids=ids,
            embeddings=all_embeddings,
            documents=texts,
            metadatas=metadatas,
            batch_size=self.config.batch_size,
        )
