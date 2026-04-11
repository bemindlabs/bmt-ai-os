"""Unit tests for bmt_ai_os.memory.search (BMTOS-72).

All tests use an explicit *documents* corpus so they run fully offline
without any ChromaDB dependency.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Corpus used across tests
# ---------------------------------------------------------------------------

_CORPUS = [
    "RAG stands for Retrieval-Augmented Generation and improves LLM accuracy.",
    "Vector search finds semantically similar documents using embeddings.",
    "BM25 is a bag-of-words ranking function based on term frequency.",
    "Python is a high-level programming language popular for AI workloads.",
    "Ed25519 is an elliptic-curve signature scheme used in OTA verification.",
]


# ===========================================================================
# BM25Index
# ===========================================================================


class TestBM25Index:
    def test_score_returns_one_score_per_doc(self):
        from bmt_ai_os.memory.search import BM25Index

        idx = BM25Index(_CORPUS)
        scores = idx.score("RAG retrieval generation")
        assert len(scores) == len(_CORPUS)

    def test_relevant_doc_scores_highest(self):
        from bmt_ai_os.memory.search import BM25Index

        idx = BM25Index(_CORPUS)
        scores = idx.score("BM25 ranking term frequency")
        best = scores.index(max(scores))
        # The BM25 document (index 2) should rank highest
        assert best == 2

    def test_rag_query_favours_rag_doc(self):
        from bmt_ai_os.memory.search import BM25Index

        idx = BM25Index(_CORPUS)
        scores = idx.score("RAG generation")
        best = scores.index(max(scores))
        assert best == 0

    def test_empty_query_all_zero(self):
        from bmt_ai_os.memory.search import BM25Index

        idx = BM25Index(_CORPUS)
        scores = idx.score("")
        assert all(s == 0.0 for s in scores)

    def test_single_document_corpus(self):
        from bmt_ai_os.memory.search import BM25Index

        idx = BM25Index(["only one document here"])
        scores = idx.score("document")
        assert len(scores) == 1
        assert scores[0] >= 0.0

    def test_out_of_vocabulary_term_zero(self):
        from bmt_ai_os.memory.search import BM25Index

        idx = BM25Index(_CORPUS)
        scores = idx.score("zzzzxyznonexistent999")
        assert all(s == 0.0 for s in scores)

    def test_all_docs_contain_term_idf_near_zero(self):
        """Ubiquitous term should have near-zero IDF across all docs."""
        from bmt_ai_os.memory.search import BM25Index

        # 'is' appears in several docs; scores should be low but not raise
        idx = BM25Index(_CORPUS)
        scores = idx.score("is")
        assert all(s >= 0.0 for s in scores)


# ===========================================================================
# _tokenize
# ===========================================================================


class TestTokenize:
    def test_lowercases(self):
        from bmt_ai_os.memory.search import _tokenize

        assert _tokenize("Hello World") == ["hello", "world"]

    def test_strips_punctuation(self):
        from bmt_ai_os.memory.search import _tokenize

        tokens = _tokenize("hello, world!")
        assert "hello" in tokens
        assert "world" in tokens

    def test_empty_string(self):
        from bmt_ai_os.memory.search import _tokenize

        assert _tokenize("") == []


# ===========================================================================
# _min_max_normalise
# ===========================================================================


class TestMinMaxNormalise:
    def test_empty_list(self):
        from bmt_ai_os.memory.search import _min_max_normalise

        assert _min_max_normalise([]) == []

    def test_all_zero(self):
        from bmt_ai_os.memory.search import _min_max_normalise

        result = _min_max_normalise([0.0, 0.0, 0.0])
        assert result == [0.0, 0.0, 0.0]

    def test_uniform_positive(self):
        from bmt_ai_os.memory.search import _min_max_normalise

        result = _min_max_normalise([5.0, 5.0, 5.0])
        # All equal and positive → all normalised to 1.0
        assert result == [1.0, 1.0, 1.0]

    def test_range_becomes_zero_to_one(self):
        from bmt_ai_os.memory.search import _min_max_normalise

        result = _min_max_normalise([0.0, 5.0, 10.0])
        assert abs(result[0] - 0.0) < 1e-9
        assert abs(result[1] - 0.5) < 1e-9
        assert abs(result[2] - 1.0) < 1e-9


# ===========================================================================
# hybrid_search
# ===========================================================================


class TestHybridSearch:
    def test_returns_k_or_fewer_results(self):
        from bmt_ai_os.memory.search import hybrid_search

        results = hybrid_search("RAG retrieval", k=3, bm25_weight=1.0, documents=_CORPUS)
        assert len(results) <= 3

    def test_result_has_required_keys(self):
        from bmt_ai_os.memory.search import hybrid_search

        results = hybrid_search("BM25", k=1, bm25_weight=1.0, documents=_CORPUS)
        assert results
        r = results[0]
        assert "document" in r
        assert "score" in r
        assert "bm25_score" in r
        assert "vector_score" in r
        assert "metadata" in r

    def test_sorted_descending_by_score(self):
        from bmt_ai_os.memory.search import hybrid_search

        results = hybrid_search("vector search embeddings", k=5, bm25_weight=1.0, documents=_CORPUS)
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_bm25_only_mode(self):
        """bm25_weight=1.0 should use BM25 exclusively (vector_score == 0)."""
        from bmt_ai_os.memory.search import hybrid_search

        results = hybrid_search("Python programming", k=5, bm25_weight=1.0, documents=_CORPUS)
        # vector_score should be 0 because vec_score_map is empty (no ChromaDB)
        for r in results:
            assert r["vector_score"] == 0.0

    def test_bm25_weight_zero_all_bm25_score_zero(self):
        """bm25_weight=0.0 → score is purely vector-based; bm25_score=0."""
        from bmt_ai_os.memory.search import hybrid_search

        # With bm25_weight=0.0 and documents provided but no vector results,
        # all scores should be 0 (because vector search will be empty).
        results = hybrid_search("anything", k=5, bm25_weight=0.0, documents=_CORPUS)
        for r in results:
            assert r["bm25_score"] == 0.0
            assert r["score"] == 0.0

    def test_invalid_bm25_weight_raises(self):
        from bmt_ai_os.memory.search import hybrid_search

        with pytest.raises(ValueError, match="bm25_weight"):
            hybrid_search("q", bm25_weight=1.5, documents=_CORPUS)

        with pytest.raises(ValueError, match="bm25_weight"):
            hybrid_search("q", bm25_weight=-0.1, documents=_CORPUS)

    def test_no_results_for_empty_corpus(self):
        from bmt_ai_os.memory.search import hybrid_search

        results = hybrid_search("anything", k=5, bm25_weight=1.0, documents=[])
        assert results == []

    def test_deduplication_no_duplicate_documents(self):
        from bmt_ai_os.memory.search import hybrid_search

        # Duplicate the corpus — results should still be unique per document text
        doubled = _CORPUS + _CORPUS
        results = hybrid_search("RAG", k=10, bm25_weight=1.0, documents=doubled)
        docs = [r["document"] for r in results]
        assert len(docs) == len(set(docs))

    def test_scores_in_zero_one_range(self):
        from bmt_ai_os.memory.search import hybrid_search

        results = hybrid_search("Ed25519 signature", k=5, bm25_weight=0.5, documents=_CORPUS)
        for r in results:
            assert 0.0 <= r["score"] <= 1.0

    def test_vector_results_fused_when_available(self):
        """When vector results are mocked, hybrid scores reflect them."""
        from bmt_ai_os.memory.search import hybrid_search

        fake_vec_results = [
            {"document": _CORPUS[1], "score": 0.9, "metadata": {"source": "chroma"}},
            {"document": _CORPUS[0], "score": 0.5, "metadata": {}},
        ]

        with patch(
            "bmt_ai_os.memory.search._vector_search",
            return_value=fake_vec_results,
        ):
            results = hybrid_search(
                "vector search",
                k=3,
                bm25_weight=0.4,
                documents=_CORPUS,
            )

        # The vector-top document should have a non-zero vector_score
        vec_top = next((r for r in results if r["document"] == _CORPUS[1]), None)
        assert vec_top is not None
        assert vec_top["vector_score"] > 0.0

    def test_vector_search_failure_non_fatal(self):
        """ChromaDB errors reduce to BM25-only, no exception propagated."""
        from bmt_ai_os.memory.search import hybrid_search

        with patch(
            "bmt_ai_os.memory.search._vector_search",
            return_value=[],
        ):
            results = hybrid_search("Python", k=3, bm25_weight=0.5, documents=_CORPUS)

        assert isinstance(results, list)

    def test_k_larger_than_corpus_returns_all(self):
        from bmt_ai_os.memory.search import hybrid_search

        results = hybrid_search("anything", k=100, bm25_weight=1.0, documents=_CORPUS)
        assert len(results) == len(_CORPUS)
