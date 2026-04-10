"""Document chunking strategies.

Provides text, Markdown, and source-code aware chunkers that split
documents into overlapping chunks while preserving semantic boundaries.

Token counting uses a simple whitespace-split heuristic (1 token ~ 1 word)
to avoid heavy tokeniser dependencies on ARM64.  This is intentionally
conservative — real sub-word tokenisers produce *more* tokens, so chunks
will stay within model context limits.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import List


@dataclass
class Chunk:
    """A single chunk of text with provenance metadata."""

    text: str
    source: str  # originating file path
    chunk_index: int
    start_char: int
    end_char: int
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _token_len(text: str) -> int:
    """Approximate token count (whitespace-split)."""
    return len(text.split())


def _merge_splits(
    pieces: List[str],
    chunk_size: int,
    overlap: int,
    source: str,
    base_offset: int = 0,
    extra_meta: dict | None = None,
) -> List[Chunk]:
    """Greedily merge *pieces* into chunks of roughly *chunk_size* tokens."""
    chunks: List[Chunk] = []
    current_pieces: List[str] = []
    current_tokens = 0
    char_cursor = base_offset

    def _flush(end_char: int) -> None:
        if not current_pieces:
            return
        text = "\n".join(current_pieces)
        meta = dict(extra_meta) if extra_meta else {}
        chunks.append(
            Chunk(
                text=text,
                source=source,
                chunk_index=len(chunks),
                start_char=char_cursor - sum(len(p) + 1 for p in current_pieces),
                end_char=end_char,
                metadata=meta,
            )
        )

    for piece in pieces:
        piece_tokens = _token_len(piece)
        if current_tokens + piece_tokens > chunk_size and current_pieces:
            _flush(char_cursor)
            # keep last N tokens worth of pieces for overlap
            overlap_pieces: List[str] = []
            overlap_tokens = 0
            for p in reversed(current_pieces):
                pt = _token_len(p)
                if overlap_tokens + pt > overlap:
                    break
                overlap_pieces.insert(0, p)
                overlap_tokens += pt
            current_pieces = overlap_pieces
            current_tokens = overlap_tokens

        current_pieces.append(piece)
        current_tokens += piece_tokens
        char_cursor += len(piece) + 1  # +1 for the join newline

    if current_pieces:
        _flush(char_cursor)

    return chunks


# ---------------------------------------------------------------------------
# TextChunker
# ---------------------------------------------------------------------------


class TextChunker:
    """Split plain text by paragraph/sentence boundaries with overlap."""

    def __init__(self, chunk_size: int = 512, overlap: int = 50) -> None:
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, text: str, source: str = "") -> List[Chunk]:
        paragraphs = re.split(r"\n\s*\n", text)
        pieces: List[str] = []
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            if _token_len(para) > self.chunk_size:
                sentences = re.split(r"(?<=[.!?])\s+", para)
                pieces.extend(s for s in sentences if s.strip())
            else:
                pieces.append(para)
        return _merge_splits(pieces, self.chunk_size, self.overlap, source)


# ---------------------------------------------------------------------------
# MarkdownChunker
# ---------------------------------------------------------------------------


class MarkdownChunker:
    """Split Markdown respecting heading boundaries and code fences."""

    def __init__(self, chunk_size: int = 512, overlap: int = 50) -> None:
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, text: str, source: str = "") -> List[Chunk]:
        sections = self._split_by_headings(text)
        all_chunks: List[Chunk] = []

        for heading, body in sections:
            section_text = f"{heading}\n{body}".strip() if heading else body.strip()
            if not section_text:
                continue
            if _token_len(section_text) <= self.chunk_size:
                all_chunks.append(
                    Chunk(
                        text=section_text,
                        source=source,
                        chunk_index=len(all_chunks),
                        start_char=0,
                        end_char=len(section_text),
                        metadata={"heading": heading.strip() if heading else ""},
                    )
                )
            else:
                sub = _merge_splits(
                    self._paragraph_split(body),
                    self.chunk_size,
                    self.overlap,
                    source,
                    extra_meta={"heading": heading.strip() if heading else ""},
                )
                for c in sub:
                    c.chunk_index = len(all_chunks)
                    if heading:
                        c.text = f"{heading.strip()}\n{c.text}"
                    all_chunks.append(c)

        return all_chunks

    @staticmethod
    def _split_by_headings(text: str) -> List[tuple]:
        """Return list of (heading_line, body) tuples."""
        parts: List[tuple] = []
        current_heading = ""
        current_body: List[str] = []

        for line in text.splitlines(keepends=True):
            if re.match(r"^#{1,6}\s", line):
                if current_heading or current_body:
                    parts.append((current_heading, "".join(current_body)))
                current_heading = line.rstrip("\n")
                current_body = []
            else:
                current_body.append(line)

        if current_heading or current_body:
            parts.append((current_heading, "".join(current_body)))
        return parts

    @staticmethod
    def _paragraph_split(text: str) -> List[str]:
        """Split text into paragraphs, keeping code fences intact."""
        blocks: List[str] = []
        current: List[str] = []
        in_fence = False

        for line in text.splitlines():
            if line.strip().startswith("```"):
                in_fence = not in_fence
            if not in_fence and line.strip() == "" and current:
                blocks.append("\n".join(current))
                current = []
            else:
                current.append(line)

        if current:
            blocks.append("\n".join(current))
        return blocks


# ---------------------------------------------------------------------------
# CodeChunker
# ---------------------------------------------------------------------------


class CodeChunker:
    """Split source code by top-level function/class definitions.

    For Python files, uses the ``ast`` module to find boundaries.
    For other languages, falls back to a simple regex heuristic that
    splits on lines starting with common definition keywords.
    """

    def __init__(self, chunk_size: int = 512, overlap: int = 50) -> None:
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, text: str, source: str = "", language: str = "") -> List[Chunk]:
        if language == "python" or source.endswith(".py"):
            return self._chunk_python(text, source)
        return self._chunk_generic(text, source, language)

    # -- Python AST-aware ---------------------------------------------------

    def _chunk_python(self, text: str, source: str) -> List[Chunk]:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return self._chunk_generic(text, source, "python")

        lines = text.splitlines(keepends=True)
        segments: List[str] = []
        prev_end = 0

        for node in ast.iter_child_nodes(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            start = node.lineno - 1
            end = node.end_lineno if node.end_lineno else start + 1

            # Capture any preamble (imports, module docstring, etc.)
            if start > prev_end:
                preamble = "".join(lines[prev_end:start]).strip()
                if preamble:
                    segments.append(preamble)

            segment = "".join(lines[start:end]).strip()
            if segment:
                segments.append(segment)
            prev_end = end

        # Trailing code after last definition
        if prev_end < len(lines):
            trailing = "".join(lines[prev_end:]).strip()
            if trailing:
                segments.append(trailing)

        if not segments:
            segments = [text]

        return _merge_splits(
            segments,
            self.chunk_size,
            self.overlap,
            source,
            extra_meta={"language": "python"},
        )

    # -- Generic fallback ---------------------------------------------------

    _DEFINITION_RE = re.compile(
        r"^(?:(?:pub(?:\(crate\))?\s+)?fn\s|"
        r"(?:export\s+)?(?:async\s+)?function\s|"
        r"(?:export\s+)?class\s|"
        r"def\s|"
        r"impl\s)",
    )

    def _chunk_generic(self, text: str, source: str, language: str = "") -> List[Chunk]:
        lines = text.splitlines(keepends=True)
        segments: List[str] = []
        current: List[str] = []

        for line in lines:
            if self._DEFINITION_RE.match(line.lstrip()) and current:
                segments.append("".join(current).strip())
                current = []
            current.append(line)

        if current:
            segments.append("".join(current).strip())

        segments = [s for s in segments if s]
        if not segments:
            segments = [text]

        return _merge_splits(
            segments,
            self.chunk_size,
            self.overlap,
            source,
            extra_meta={"language": language or _guess_language(source)},
        )


def _guess_language(path: str) -> str:
    """Guess programming language from file extension."""
    ext_map = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".jsx": "javascript",
        ".tsx": "typescript",
        ".c": "c",
        ".h": "c",
        ".cpp": "cpp",
        ".hpp": "cpp",
        ".rs": "rust",
        ".go": "go",
        ".java": "java",
        ".sh": "shell",
        ".bash": "shell",
        ".zsh": "shell",
    }
    for ext, lang in ext_map.items():
        if path.endswith(ext):
            return lang
    return ""
