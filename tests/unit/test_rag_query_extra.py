"""Additional unit tests for bmt_ai_os.rag.query.RAGQueryEngine.

Covers query() and query_stream() with mocked storage and LLM.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from bmt_ai_os.rag.config import RAGConfig
from bmt_ai_os.rag.query import RAGQueryEngine, RAGResponse

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine() -> RAGQueryEngine:
    """RAGQueryEngine with mocked storage and LLM."""
    cfg = RAGConfig()
    with (
        patch("bmt_ai_os.rag.query.ChromaStorage") as mock_storage_cls,
        patch("bmt_ai_os.rag.query.OllamaLLM") as mock_llm_cls,
    ):
        mock_storage = MagicMock()
        mock_storage.query.return_value = {
            "ids": [["id-1", "id-2"]],
            "documents": [["doc one", "doc two"]],
            "metadatas": [[{"filename": "a.md"}, {"filename": "b.py"}]],
            "distances": [[0.1, 0.3]],
        }
        mock_storage_cls.return_value = mock_storage

        mock_llm = MagicMock()
        mock_llm.generate.return_value = "The answer is 42."
        mock_llm_cls.return_value = mock_llm

        eng = RAGQueryEngine(config=cfg)
        eng.storage = mock_storage
        eng.llm = mock_llm
    return eng


# ---------------------------------------------------------------------------
# query()
# ---------------------------------------------------------------------------


class TestRAGQueryEngine:
    def test_query_returns_rag_response(self, engine: RAGQueryEngine) -> None:
        result = engine.query("What is 42?")
        assert isinstance(result, RAGResponse)

    def test_query_answer_from_llm(self, engine: RAGQueryEngine) -> None:
        result = engine.query("What is 42?")
        assert result.answer == "The answer is 42."

    def test_query_sources_populated(self, engine: RAGQueryEngine) -> None:
        result = engine.query("What is 42?")
        assert len(result.sources) == 2

    def test_query_model_used_from_config(self, engine: RAGQueryEngine) -> None:
        result = engine.query("q?")
        assert result.model_used == engine.config.llm_model

    def test_query_latency_positive(self, engine: RAGQueryEngine) -> None:
        result = engine.query("q?")
        assert result.latency_ms >= 0

    def test_query_passes_top_k_to_storage(self, engine: RAGQueryEngine) -> None:
        engine.query("q?", top_k=3)
        engine.storage.query.assert_called_once()
        call_kwargs = engine.storage.query.call_args
        assert call_kwargs[1]["top_k"] == 3 or call_kwargs[0][2] == 3

    def test_query_uses_config_top_k_by_default(self, engine: RAGQueryEngine) -> None:
        engine.query("q?")
        engine.storage.query.assert_called()

    def test_query_code_mode(self, engine: RAGQueryEngine) -> None:
        result = engine.query("q?", code_mode=True)
        assert isinstance(result, RAGResponse)

    def test_query_empty_results(self, engine: RAGQueryEngine) -> None:
        engine.storage.query.return_value = {
            "ids": [[]],
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }
        result = engine.query("q?")
        assert result.sources == []

    def test_query_to_dict(self, engine: RAGQueryEngine) -> None:
        result = engine.query("q?")
        d = result.to_dict()
        assert "answer" in d
        assert "sources" in d
        assert "latency_ms" in d
        assert "model" in d


# ---------------------------------------------------------------------------
# query_stream()
# ---------------------------------------------------------------------------


class TestRAGQueryEngineStream:
    def test_query_stream_yields_tokens_then_response(self, engine: RAGQueryEngine) -> None:
        engine.llm.generate.return_value = iter(["Hello", " world", "!"])

        results = list(engine.query_stream("q?"))
        # Last element should be a RAGResponse
        assert isinstance(results[-1], RAGResponse)
        # Earlier elements should be strings
        tokens = [r for r in results if isinstance(r, str)]
        assert len(tokens) > 0

    def test_query_stream_final_response_has_full_answer(self, engine: RAGQueryEngine) -> None:
        engine.llm.generate.return_value = iter(["Hello", " world"])

        results = list(engine.query_stream("q?"))
        final = results[-1]
        assert isinstance(final, RAGResponse)
        assert final.answer == "Hello world"

    def test_query_stream_model_used_in_response(self, engine: RAGQueryEngine) -> None:
        engine.llm.generate.return_value = iter(["token"])
        results = list(engine.query_stream("q?"))
        final = results[-1]
        assert final.model_used == engine.config.llm_model
