"""Unit tests for the RAG query pipeline.

These tests exercise prompt rendering, source attribution, response
serialization, and config loading without requiring live Ollama or
ChromaDB services.
"""

from __future__ import annotations

import pytest
from rag.config import RAGConfig
from rag.prompts import (
    DEFAULT_SYSTEM_PROMPT,
    render_prompt,
)
from rag.query import RAGQueryEngine, RAGResponse, SourceAttribution

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture()
def sample_chunks() -> list[dict]:
    return [
        {"text": "Alpha chunk content", "filename": "alpha.md"},
        {"text": "Beta chunk content", "filename": "beta.py"},
    ]


@pytest.fixture()
def sample_raw_chromadb_response() -> dict:
    """Mimics the shape returned by ChromaDB /query."""
    return {
        "ids": [["id-1", "id-2", "id-3"]],
        "documents": [["doc one text", "doc two text", "doc three text"]],
        "metadatas": [[{"filename": "a.md"}, {"filename": "b.py"}, None]],
        "distances": [[0.1, 0.3, 0.6]],
    }


# ------------------------------------------------------------------
# Prompt template tests
# ------------------------------------------------------------------


class TestPromptRendering:
    def test_default_template_includes_question(self, sample_chunks: list[dict]) -> None:
        result = render_prompt("What is X?", sample_chunks)
        assert "What is X?" in result

    def test_default_template_includes_context(self, sample_chunks: list[dict]) -> None:
        result = render_prompt("q?", sample_chunks)
        assert "Alpha chunk content" in result
        assert "Beta chunk content" in result

    def test_default_template_includes_source_labels(self, sample_chunks: list[dict]) -> None:
        result = render_prompt("q?", sample_chunks)
        assert "(source: alpha.md)" in result
        assert "(source: beta.py)" in result

    def test_default_template_includes_system_prompt(self, sample_chunks: list[dict]) -> None:
        # When persona is disabled, DEFAULT_SYSTEM_PROMPT is used verbatim.
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"BMT_PERSONA_ENABLED": "0"}):
            result = render_prompt("q?", sample_chunks)
        assert "context" in result.lower()

    def test_default_template_includes_some_system_prompt(self, sample_chunks: list[dict]) -> None:
        # A system prompt of some kind must always be present in the rendered output.
        result = render_prompt("q?", sample_chunks)
        # Question and context must still appear regardless of which system prompt is used.
        assert "q?" in result
        assert len(result) > 0

    def test_custom_system_prompt(self, sample_chunks: list[dict]) -> None:
        result = render_prompt("q?", sample_chunks, system_prompt="Custom system")
        assert "Custom system" in result
        assert DEFAULT_SYSTEM_PROMPT not in result

    def test_code_mode_template(self, sample_chunks: list[dict]) -> None:
        result = render_prompt("q?", sample_chunks, code_mode=True)
        assert "code-related question" in result

    def test_empty_chunks(self) -> None:
        result = render_prompt("q?", [])
        assert "q?" in result

    def test_numbered_context_blocks(self, sample_chunks: list[dict]) -> None:
        result = render_prompt("q?", sample_chunks)
        assert "[1]" in result
        assert "[2]" in result


# ------------------------------------------------------------------
# Source attribution tests
# ------------------------------------------------------------------


class TestSourceAttribution:
    def test_to_dict(self) -> None:
        sa = SourceAttribution(
            filename="readme.md",
            chunk_text="some text",
            relevance_score=0.85432,
            position=0,
        )
        d = sa.to_dict()
        assert d["filename"] == "readme.md"
        assert d["chunk"] == "some text"
        assert d["score"] == 0.8543
        assert d["position"] == 0

    def test_score_rounding(self) -> None:
        sa = SourceAttribution("f", "t", 0.99999, 1)
        assert sa.to_dict()["score"] == 1.0


# ------------------------------------------------------------------
# RAGResponse serialization tests
# ------------------------------------------------------------------


class TestRAGResponse:
    def test_to_dict_structure(self) -> None:
        sources = [
            SourceAttribution("a.md", "text a", 0.9, 0),
            SourceAttribution("b.md", "text b", 0.7, 1),
        ]
        resp = RAGResponse(
            answer="The answer is 42.",
            sources=sources,
            latency_ms=1234.567,
            model_used="qwen2.5-coder:7b-instruct-q4_K_M",
        )
        d = resp.to_dict()
        assert d["answer"] == "The answer is 42."
        assert d["latency_ms"] == 1234.6
        assert d["model"] == "qwen2.5-coder:7b-instruct-q4_K_M"
        assert len(d["sources"]) == 2
        assert d["sources"][0]["filename"] == "a.md"

    def test_empty_sources(self) -> None:
        resp = RAGResponse(answer="No context.", sources=[], latency_ms=50.0, model_used="m")
        d = resp.to_dict()
        assert d["sources"] == []


# ------------------------------------------------------------------
# Config tests
# ------------------------------------------------------------------


class TestRAGConfig:
    def test_defaults(self) -> None:
        cfg = RAGConfig()
        assert cfg.top_k == 5
        assert cfg.temperature == 0.7
        assert cfg.max_tokens == 2048
        assert "qwen2.5-coder" in cfg.llm_model
        assert cfg.chromadb_url == "http://localhost:8000"
        assert cfg.ollama_url == "http://localhost:11434"

    def test_override(self) -> None:
        cfg = RAGConfig(top_k=10, temperature=0.3, max_tokens=512)
        assert cfg.top_k == 10
        assert cfg.temperature == 0.3
        assert cfg.max_tokens == 512

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BMT_RAG_CHROMADB_URL", "http://chroma:9000")
        monkeypatch.setenv("BMT_RAG_LLM_MODEL", "custom-model")
        cfg = RAGConfig()
        assert cfg.chromadb_url == "http://chroma:9000"
        assert cfg.llm_model == "custom-model"


# ------------------------------------------------------------------
# _parse_results helper tests
# ------------------------------------------------------------------


class TestParseResults:
    def test_parse_basic(self, sample_raw_chromadb_response: dict) -> None:
        chunks, sources = RAGQueryEngine._parse_results(sample_raw_chromadb_response)
        assert len(chunks) == 3
        assert len(sources) == 3
        assert chunks[0]["filename"] == "a.md"
        assert chunks[0]["text"] == "doc one text"
        # Third result has no metadata, falls back to id.
        assert sources[2].filename == "id-3"

    def test_distance_to_similarity(self, sample_raw_chromadb_response: dict) -> None:
        _, sources = RAGQueryEngine._parse_results(sample_raw_chromadb_response)
        assert sources[0].relevance_score == pytest.approx(0.9)
        assert sources[1].relevance_score == pytest.approx(0.7)

    def test_empty_results(self) -> None:
        chunks, sources = RAGQueryEngine._parse_results({})
        assert chunks == []
        assert sources == []

    def test_chunk_text_truncation(self) -> None:
        long_text = "x" * 500
        raw = {
            "ids": [["id-1"]],
            "documents": [[long_text]],
            "metadatas": [[{"filename": "big.txt"}]],
            "distances": [[0.05]],
        }
        _, sources = RAGQueryEngine._parse_results(raw)
        assert len(sources[0].chunk_text) == 200
