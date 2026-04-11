"""Unit tests for bmt_ai_os.rag.prompts.

Covers render_prompt, _format_context, and template constants.
"""

from __future__ import annotations

from bmt_ai_os.rag.prompts import (
    CODE_RAG_TEMPLATE,
    DEFAULT_RAG_TEMPLATE,
    DEFAULT_SYSTEM_PROMPT,
    _format_context,
    render_prompt,
)

# ---------------------------------------------------------------------------
# _format_context
# ---------------------------------------------------------------------------


class TestFormatContext:
    def test_empty_chunks_returns_empty_string(self):
        assert _format_context([]) == ""

    def test_single_chunk_numbered(self):
        chunks = [{"text": "Hello world", "filename": "test.md"}]
        result = _format_context(chunks)
        assert "[1]" in result
        assert "Hello world" in result
        assert "test.md" in result

    def test_multiple_chunks_numbered_sequentially(self):
        chunks = [
            {"text": "First", "filename": "a.md"},
            {"text": "Second", "filename": "b.py"},
            {"text": "Third", "filename": "c.txt"},
        ]
        result = _format_context(chunks)
        assert "[1]" in result
        assert "[2]" in result
        assert "[3]" in result

    def test_source_label_in_output(self):
        chunks = [{"text": "content", "filename": "readme.md"}]
        result = _format_context(chunks)
        assert "(source: readme.md)" in result

    def test_missing_filename_defaults_to_unknown(self):
        chunks = [{"text": "content"}]
        result = _format_context(chunks)
        assert "unknown" in result

    def test_missing_text_defaults_to_empty(self):
        chunks = [{"filename": "file.md"}]
        result = _format_context(chunks)
        assert "[1]" in result

    def test_chunks_separated_by_double_newlines(self):
        chunks = [
            {"text": "Chunk A", "filename": "a.md"},
            {"text": "Chunk B", "filename": "b.md"},
        ]
        result = _format_context(chunks)
        assert "\n\n" in result

    def test_preserves_text_content(self):
        text = "def hello(): return 'world'"
        chunks = [{"text": text, "filename": "main.py"}]
        result = _format_context(chunks)
        assert text in result

    def test_large_number_of_chunks(self):
        chunks = [{"text": f"chunk {i}", "filename": f"file{i}.txt"} for i in range(10)]
        result = _format_context(chunks)
        assert "[10]" in result
        assert "chunk 9" in result


# ---------------------------------------------------------------------------
# render_prompt — default template
# ---------------------------------------------------------------------------


class TestRenderPromptDefault:
    def test_question_in_output(self):
        result = render_prompt("What is ARM64?", [])
        assert "What is ARM64?" in result

    def test_default_system_prompt_included(self):
        result = render_prompt("q?", [])
        assert "retrieved context" in result.lower() or "following context" in result.lower()

    def test_context_included(self):
        chunks = [{"text": "ARM64 is a 64-bit instruction set.", "filename": "arch.md"}]
        result = render_prompt("What is ARM64?", chunks)
        assert "ARM64 is a 64-bit instruction set." in result

    def test_source_label_included(self):
        chunks = [{"text": "data", "filename": "source.md"}]
        result = render_prompt("q?", chunks)
        assert "source.md" in result

    def test_empty_chunks_renders_without_context(self):
        result = render_prompt("q?", [])
        assert "q?" in result
        assert "retrieved context" in result.lower() or "following context" in result.lower()

    def test_multiple_chunks_all_included(self):
        chunks = [
            {"text": "Alpha", "filename": "alpha.md"},
            {"text": "Beta", "filename": "beta.md"},
        ]
        result = render_prompt("q?", chunks)
        assert "Alpha" in result
        assert "Beta" in result

    def test_custom_system_prompt_overrides_default(self):
        result = render_prompt("q?", [], system_prompt="Custom instructions.")
        assert "Custom instructions." in result
        assert DEFAULT_SYSTEM_PROMPT not in result

    def test_default_template_used_when_not_code_mode(self):
        chunks = [{"text": "data", "filename": "f.md"}]
        result = render_prompt("q?", chunks, code_mode=False)
        assert "code-related question" not in result


# ---------------------------------------------------------------------------
# render_prompt — code mode
# ---------------------------------------------------------------------------


class TestRenderPromptCodeMode:
    def test_code_template_used(self):
        result = render_prompt("q?", [], code_mode=True)
        assert "code-related question" in result

    def test_code_template_mentions_fenced_code_blocks(self):
        result = render_prompt("q?", [], code_mode=True)
        assert "fenced code blocks" in result

    def test_question_still_included_in_code_mode(self):
        result = render_prompt("How does Python GIL work?", [], code_mode=True)
        assert "How does Python GIL work?" in result

    def test_context_included_in_code_mode(self):
        chunks = [{"text": "def foo(): pass", "filename": "main.py"}]
        result = render_prompt("Explain foo", chunks, code_mode=True)
        assert "def foo(): pass" in result

    def test_custom_system_prompt_in_code_mode(self):
        result = render_prompt("q?", [], code_mode=True, system_prompt="Be concise.")
        assert "Be concise." in result

    def test_default_system_prompt_included_in_code_mode(self):
        result = render_prompt("q?", [], code_mode=True)
        assert "retrieved context" in result.lower() or "following context" in result.lower()


# ---------------------------------------------------------------------------
# Template constants
# ---------------------------------------------------------------------------


class TestTemplateConstants:
    def test_default_system_prompt_not_empty(self):
        assert len(DEFAULT_SYSTEM_PROMPT) > 0

    def test_default_rag_template_contains_placeholders(self):
        assert "{system}" in DEFAULT_RAG_TEMPLATE
        assert "{context}" in DEFAULT_RAG_TEMPLATE
        assert "{question}" in DEFAULT_RAG_TEMPLATE

    def test_code_rag_template_contains_placeholders(self):
        assert "{system}" in CODE_RAG_TEMPLATE
        assert "{context}" in CODE_RAG_TEMPLATE
        assert "{question}" in CODE_RAG_TEMPLATE

    def test_code_template_differs_from_default(self):
        assert CODE_RAG_TEMPLATE != DEFAULT_RAG_TEMPLATE

    def test_default_system_prompt_mentions_context(self):
        assert "context" in DEFAULT_SYSTEM_PROMPT.lower()

    def test_default_system_prompt_mentions_sources(self):
        assert "source" in DEFAULT_SYSTEM_PROMPT.lower()
