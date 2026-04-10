"""Unit tests for the RAG document chunking module."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Import chunker directly to avoid pulling in heavy dependencies
# (chromadb, requests) that __init__.py would trigger.
_chunker_path = Path(__file__).resolve().parents[2] / "bmt-ai-os" / "rag" / "chunker.py"
_spec = importlib.util.spec_from_file_location("rag_chunker", _chunker_path)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["rag_chunker"] = _mod
_spec.loader.exec_module(_mod)

CodeChunker = _mod.CodeChunker
MarkdownChunker = _mod.MarkdownChunker
TextChunker = _mod.TextChunker
_guess_language = _mod._guess_language
_token_len = _mod._token_len


# ---------------------------------------------------------------------------
# TextChunker tests
# ---------------------------------------------------------------------------


class TestTextChunker:
    def test_single_short_paragraph(self):
        chunker = TextChunker(chunk_size=512, overlap=50)
        chunks = chunker.chunk("Hello world. This is a test.", source="test.txt")
        assert len(chunks) == 1
        assert "Hello world" in chunks[0].text
        assert chunks[0].source == "test.txt"

    def test_multiple_paragraphs(self):
        text = "First paragraph with some content.\n\nSecond paragraph with more content."
        chunker = TextChunker(chunk_size=512, overlap=50)
        chunks = chunker.chunk(text, source="doc.txt")
        assert len(chunks) >= 1
        # All content should be represented
        joined = " ".join(c.text for c in chunks)
        assert "First paragraph" in joined
        assert "Second paragraph" in joined

    def test_chunk_size_respected(self):
        # Build text that exceeds chunk_size tokens
        words = ["word"] * 200
        para = " ".join(words)
        text = f"{para}\n\n{para}\n\n{para}"
        chunker = TextChunker(chunk_size=100, overlap=10)
        chunks = chunker.chunk(text, source="big.txt")
        assert len(chunks) > 1
        for chunk in chunks:
            # Allow some tolerance (overlap + boundary)
            assert _token_len(chunk.text) <= 200

    def test_overlap_produces_shared_content(self):
        # Create enough content for 2+ chunks with overlap
        sentences = [f"Sentence number {i} with some extra words." for i in range(80)]
        text = " ".join(sentences)
        chunker = TextChunker(chunk_size=50, overlap=10)
        chunks = chunker.chunk(text, source="overlap.txt")
        if len(chunks) >= 2:
            # Overlap means the tail of chunk N appears at the start of chunk N+1
            last_words_0 = set(chunks[0].text.split()[-10:])
            first_words_1 = set(chunks[1].text.split()[:20])
            assert last_words_0 & first_words_1, "Expected overlap between consecutive chunks"

    def test_chunk_metadata_fields(self):
        chunker = TextChunker(chunk_size=512, overlap=50)
        chunks = chunker.chunk("Some text content.", source="/data/file.txt")
        chunk = chunks[0]
        assert chunk.source == "/data/file.txt"
        assert chunk.chunk_index == 0
        assert isinstance(chunk.start_char, int)
        assert isinstance(chunk.end_char, int)

    def test_empty_input(self):
        chunker = TextChunker()
        chunks = chunker.chunk("", source="empty.txt")
        assert chunks == []


# ---------------------------------------------------------------------------
# MarkdownChunker tests
# ---------------------------------------------------------------------------


class TestMarkdownChunker:
    def test_heading_aware_splitting(self):
        md = "# Title\n\nIntro text.\n\n## Section A\n\nContent A.\n\n## Section B\n\nContent B."
        chunker = MarkdownChunker(chunk_size=512, overlap=50)
        chunks = chunker.chunk(md, source="readme.md")
        assert len(chunks) >= 1
        # Heading metadata should be set
        for chunk in chunks:
            assert "heading" in chunk.metadata

    def test_code_fence_kept_intact(self):
        md = "# Guide\n\nSome text.\n\n```python\ndef foo():\n    return 42\n```\n\nMore text."
        chunker = MarkdownChunker(chunk_size=512, overlap=50)
        chunks = chunker.chunk(md, source="guide.md")
        # The code block should not be split across chunks
        code_chunks = [c for c in chunks if "def foo():" in c.text]
        assert len(code_chunks) >= 1
        for c in code_chunks:
            assert "return 42" in c.text

    def test_large_section_split(self):
        # A section that exceeds chunk_size should be sub-chunked
        long_body = "\n\n".join([f"Paragraph {i} " + "word " * 30 for i in range(20)])
        md = f"# Big Section\n\n{long_body}"
        chunker = MarkdownChunker(chunk_size=50, overlap=10)
        chunks = chunker.chunk(md, source="big.md")
        assert len(chunks) > 1

    def test_empty_markdown(self):
        chunker = MarkdownChunker()
        chunks = chunker.chunk("", source="empty.md")
        assert chunks == []


# ---------------------------------------------------------------------------
# CodeChunker tests
# ---------------------------------------------------------------------------


class TestCodeChunker:
    def test_python_function_splitting(self):
        code = (
            "import os\n\n"
            "def hello():\n"
            "    print('hello')\n\n"
            "def world():\n"
            "    print('world')\n\n"
            "class Foo:\n"
            "    def bar(self):\n"
            "        pass\n"
        )
        chunker = CodeChunker(chunk_size=512, overlap=0)
        chunks = chunker.chunk(code, source="app.py", language="python")
        assert len(chunks) >= 1
        joined = " ".join(c.text for c in chunks)
        assert "def hello" in joined
        assert "def world" in joined
        assert "class Foo" in joined

    def test_python_syntax_error_fallback(self):
        bad_code = "def broken(\n   return nope"
        chunker = CodeChunker(chunk_size=512, overlap=0)
        # Should not raise, falls back to generic chunking
        chunks = chunker.chunk(bad_code, source="bad.py", language="python")
        assert len(chunks) >= 1

    def test_generic_code_splitting(self):
        js_code = (
            "function greet() {\n  console.log('hi');\n}\n\n"
            "function farewell() {\n  console.log('bye');\n}\n"
        )
        chunker = CodeChunker(chunk_size=512, overlap=0)
        chunks = chunker.chunk(js_code, source="app.js", language="javascript")
        assert len(chunks) >= 1

    def test_language_metadata(self):
        chunker = CodeChunker(chunk_size=512, overlap=0)
        chunks = chunker.chunk("x = 1\n", source="script.py")
        assert chunks[0].metadata.get("language") == "python"


# ---------------------------------------------------------------------------
# Utility tests
# ---------------------------------------------------------------------------


class TestGuessLanguage:
    @pytest.mark.parametrize(
        "ext,expected",
        [
            (".py", "python"),
            (".js", "javascript"),
            (".ts", "typescript"),
            (".rs", "rust"),
            (".go", "go"),
            (".c", "c"),
            (".java", "java"),
        ],
    )
    def test_known_extensions(self, ext, expected):
        assert _guess_language(f"file{ext}") == expected

    def test_unknown_extension(self):
        assert _guess_language("file.xyz") == ""
