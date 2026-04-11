"""Unit tests for bmt_ai_os.rag.ingest.DocumentIngester.

All external dependencies (OllamaEmbeddings, ChromaStorage, filesystem I/O)
are mocked so tests are fully offline.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from bmt_ai_os.rag.config import RAGConfig
from bmt_ai_os.rag.ingest import _CODE_EXTENSIONS, DocumentIngester

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ingester(tmp_path: Path) -> DocumentIngester:
    """Build a DocumentIngester with mocked embeddings and storage.

    DocumentIngester.__init__ references config attributes that extend
    beyond the current RAGConfig definition (e.g. embedding_dimensions,
    max_retries, retry_base_delay, supported_extensions) — bypass the
    constructor entirely via __new__ and wire up only what is needed.
    """
    from bmt_ai_os.rag.chunker import CodeChunker, MarkdownChunker, TextChunker

    cfg = RAGConfig(
        chromadb_url="http://localhost:8000",
        ollama_url="http://localhost:11434",
    )

    # Patch extra attributes that ingest.py expects but RAGConfig lacks.
    cfg.supported_extensions = {".txt", ".md", ".py", ".ts", ".rs", ".go"}
    cfg.batch_size = 10

    ingester = DocumentIngester.__new__(DocumentIngester)
    ingester.config = cfg

    mock_emb = MagicMock()
    mock_emb.embed.return_value = [[0.1, 0.2, 0.3]]
    ingester._embeddings = mock_emb

    mock_store = MagicMock()
    ingester._storage = mock_store

    ingester._text_chunker = TextChunker(cfg.chunk_size, cfg.chunk_overlap)
    ingester._md_chunker = MarkdownChunker(cfg.chunk_size, cfg.chunk_overlap)
    ingester._code_chunker = CodeChunker(cfg.chunk_size, cfg.chunk_overlap)
    ingester._ingested_hashes = set()

    return ingester


# ---------------------------------------------------------------------------
# _CODE_EXTENSIONS constant
# ---------------------------------------------------------------------------


class TestCodeExtensions:
    def test_contains_python(self):
        assert ".py" in _CODE_EXTENSIONS

    def test_contains_typescript(self):
        assert ".ts" in _CODE_EXTENSIONS

    def test_contains_rust(self):
        assert ".rs" in _CODE_EXTENSIONS

    def test_contains_go(self):
        assert ".go" in _CODE_EXTENSIONS


# ---------------------------------------------------------------------------
# _chunk_file dispatch
# ---------------------------------------------------------------------------


class TestChunkFileDispatch:
    def test_md_uses_markdown_chunker(self, tmp_path):
        ingester = _make_ingester(tmp_path)
        with patch.object(ingester._md_chunker, "chunk", return_value=[]) as mock_chunk:
            ingester._chunk_file("# Hello", "readme.md")
        mock_chunk.assert_called_once_with("# Hello", "readme.md")

    def test_py_uses_code_chunker(self, tmp_path):
        ingester = _make_ingester(tmp_path)
        with patch.object(ingester._code_chunker, "chunk", return_value=[]) as mock_chunk:
            ingester._chunk_file("def foo(): pass", "main.py")
        assert mock_chunk.called

    def test_txt_uses_text_chunker(self, tmp_path):
        ingester = _make_ingester(tmp_path)
        with patch.object(ingester._text_chunker, "chunk", return_value=[]) as mock_chunk:
            ingester._chunk_file("plain text content", "notes.txt")
        mock_chunk.assert_called_once()

    def test_rs_uses_code_chunker(self, tmp_path):
        ingester = _make_ingester(tmp_path)
        with patch.object(ingester._code_chunker, "chunk", return_value=[]) as mock_chunk:
            ingester._chunk_file("fn main() {}", "main.rs")
        assert mock_chunk.called


# ---------------------------------------------------------------------------
# ingest_file
# ---------------------------------------------------------------------------


class TestIngestFile:
    def test_skips_nonexistent_file(self, tmp_path):
        ingester = _make_ingester(tmp_path)
        count = ingester.ingest_file(tmp_path / "nonexistent.txt")
        assert count == 0

    def test_skips_unsupported_extension(self, tmp_path):
        f = tmp_path / "image.png"
        f.write_bytes(b"\x89PNG")
        ingester = _make_ingester(tmp_path)
        count = ingester.ingest_file(f)
        assert count == 0

    def test_ingests_txt_file(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("Hello world, this is a test document with enough content.")
        ingester = _make_ingester(tmp_path)

        from bmt_ai_os.rag.chunker import Chunk

        fake_chunks = [
            Chunk(text="Hello world", source=str(f), chunk_index=0, start_char=0, end_char=11)
        ]
        ingester._embeddings.embed.return_value = [[0.1, 0.2]]
        with patch.object(ingester, "_chunk_file", return_value=fake_chunks):
            with patch.object(ingester, "_store_chunks"):
                count = ingester.ingest_file(f)
        assert count == 1

    def test_skips_duplicate_content(self, tmp_path):
        f = tmp_path / "doc.txt"
        f.write_text("same content")
        ingester = _make_ingester(tmp_path)

        from bmt_ai_os.rag.chunker import Chunk

        fake_chunks = [
            Chunk(text="same content", source=str(f), chunk_index=0, start_char=0, end_char=12)
        ]
        with (
            patch.object(ingester, "_chunk_file", return_value=fake_chunks),
            patch.object(ingester, "_store_chunks") as mock_store,
        ):
            count1 = ingester.ingest_file(f)
            count2 = ingester.ingest_file(f)  # duplicate

        assert count1 == 1
        assert count2 == 0
        assert mock_store.call_count == 1

    def test_empty_chunks_returns_zero(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        ingester = _make_ingester(tmp_path)
        with patch.object(ingester, "_chunk_file", return_value=[]):
            count = ingester.ingest_file(f)
        assert count == 0

    def test_ingests_markdown_file(self, tmp_path):
        f = tmp_path / "readme.md"
        f.write_text("# Title\n\nSome markdown content here.")
        ingester = _make_ingester(tmp_path)

        from bmt_ai_os.rag.chunker import Chunk

        fake_chunks = [Chunk(text="Title", source=str(f), chunk_index=0, start_char=0, end_char=5)]
        with (
            patch.object(ingester, "_chunk_file", return_value=fake_chunks),
            patch.object(ingester, "_store_chunks"),
        ):
            count = ingester.ingest_file(f)
        assert count == 1

    def test_ingests_python_file(self, tmp_path):
        f = tmp_path / "main.py"
        f.write_text("def hello(): return 'world'")
        ingester = _make_ingester(tmp_path)

        from bmt_ai_os.rag.chunker import Chunk

        fake_chunks = [
            Chunk(text="def hello()", source=str(f), chunk_index=0, start_char=0, end_char=11)
        ]
        with (
            patch.object(ingester, "_chunk_file", return_value=fake_chunks),
            patch.object(ingester, "_store_chunks"),
        ):
            count = ingester.ingest_file(f)
        assert count == 1


# ---------------------------------------------------------------------------
# ingest_directory
# ---------------------------------------------------------------------------


class TestIngestDirectory:
    def test_returns_error_for_nonexistent_dir(self, tmp_path):
        ingester = _make_ingester(tmp_path)
        result = ingester.ingest_directory(tmp_path / "nonexistent")
        assert result.get("_errors") == 1

    def test_ingests_multiple_files(self, tmp_path):
        for name in ["a.txt", "b.txt", "c.txt"]:
            (tmp_path / name).write_text(f"Content of {name}")

        ingester = _make_ingester(tmp_path)

        def fake_ingest_file(path):
            return 1

        with patch.object(ingester, "ingest_file", side_effect=fake_ingest_file):
            result = ingester.ingest_directory(tmp_path, recursive=False)

        assert result["_total"] == 3
        assert result["_errors"] == 0

    def test_non_recursive_excludes_subdirs(self, tmp_path):
        subdir = tmp_path / "sub"
        subdir.mkdir()
        (tmp_path / "top.txt").write_text("top level")
        (subdir / "nested.txt").write_text("nested")

        ingester = _make_ingester(tmp_path)
        counts: list[int] = []

        def fake_ingest_file(path):
            counts.append(1)
            return 1

        with patch.object(ingester, "ingest_file", side_effect=fake_ingest_file):
            result = ingester.ingest_directory(tmp_path, recursive=False)

        assert result["_total"] == 1

    def test_recursive_includes_subdirs(self, tmp_path):
        subdir = tmp_path / "sub"
        subdir.mkdir()
        (tmp_path / "top.txt").write_text("top")
        (subdir / "nested.txt").write_text("nested")

        ingester = _make_ingester(tmp_path)

        with patch.object(ingester, "ingest_file", return_value=1):
            result = ingester.ingest_directory(tmp_path, recursive=True)

        assert result["_total"] == 2

    def test_tracks_errors(self, tmp_path):
        (tmp_path / "bad.txt").write_text("content")
        ingester = _make_ingester(tmp_path)

        def raise_on_file(_path):
            raise RuntimeError("embed failed")

        with patch.object(ingester, "ingest_file", side_effect=raise_on_file):
            result = ingester.ingest_directory(tmp_path)

        assert result["_errors"] == 1

    def test_custom_patterns(self, tmp_path):
        (tmp_path / "file.py").write_text("python")
        (tmp_path / "file.txt").write_text("text")
        ingester = _make_ingester(tmp_path)
        visited: list[str] = []

        def record(path):
            visited.append(str(path))
            return 1

        with patch.object(ingester, "ingest_file", side_effect=record):
            ingester.ingest_directory(tmp_path, patterns=["*.py"])

        assert all(p.endswith(".py") for p in visited)
