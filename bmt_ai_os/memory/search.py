"""Hybrid BM25 + vector memory search (BMTOS-72).

Two complementary retrieval strategies are combined:

1. **BM25 text search** — classic probabilistic ranking with TF-IDF-like
   scoring.  Implemented entirely in stdlib so there are no extra
   dependencies on ARM64 targets.

2. **Vector search** — semantic similarity via ChromaDB embeddings.

3. **Hybrid scorer** — a weighted average of the two normalised score
   distributions, configurable at call time via *bm25_weight*.

Typical usage
-------------
>>> results = hybrid_search("What is RAG?", k=5, bm25_weight=0.3)
>>> for r in results:
...     print(r["score"], r["document"])
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BM25 implementation (stdlib-only)
# ---------------------------------------------------------------------------

_BM25_K1: float = 1.5  # term-frequency saturation
_BM25_B: float = 0.75  # length normalisation


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, return individual word tokens."""
    return re.findall(r"\w+", text.lower())


class BM25Index:
    """In-memory BM25 index over a corpus of plain-text documents.

    Parameters
    ----------
    documents:
        Sequence of document strings to index.
    k1:
        Term-frequency saturation parameter.
    b:
        Length normalisation parameter (0 = no normalisation, 1 = full).
    """

    def __init__(
        self,
        documents: list[str],
        k1: float = _BM25_K1,
        b: float = _BM25_B,
    ) -> None:
        self.k1 = k1
        self.b = b
        self._docs = documents
        self._tokenized: list[list[str]] = [_tokenize(d) for d in documents]
        self._doc_lengths: list[int] = [len(t) for t in self._tokenized]
        self._avg_len: float = (
            sum(self._doc_lengths) / len(self._doc_lengths) if self._doc_lengths else 1.0
        )
        self._n = len(documents)
        # Inverted document frequency per term
        self._df: dict[str, int] = self._build_df()

    # ------------------------------------------------------------------
    # Index construction
    # ------------------------------------------------------------------

    def _build_df(self) -> dict[str, int]:
        df: dict[str, int] = {}
        for tokens in self._tokenized:
            for term in set(tokens):
                df[term] = df.get(term, 0) + 1
        return df

    def _idf(self, term: str) -> float:
        """Robertson-Spärck Jones IDF, floored at 0 to avoid negatives."""
        df = self._df.get(term, 0)
        return max(0.0, math.log((self._n - df + 0.5) / (df + 0.5) + 1.0))

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def score(self, query: str) -> list[float]:
        """Return a BM25 score for each document in the corpus."""
        query_terms = _tokenize(query)
        scores: list[float] = [0.0] * self._n

        for term in query_terms:
            idf = self._idf(term)
            for i, tokens in enumerate(self._tokenized):
                tf = Counter(tokens)[term]
                dl = self._doc_lengths[i]
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * dl / self._avg_len)
                scores[i] += idf * (numerator / denominator if denominator else 0.0)

        return scores


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------


def _min_max_normalise(scores: list[float]) -> list[float]:
    """Scale scores to [0, 1] using min-max normalisation."""
    if not scores:
        return []
    lo, hi = min(scores), max(scores)
    if hi == lo:
        return [1.0 if s > 0 else 0.0 for s in scores]
    return [(s - lo) / (hi - lo) for s in scores]


# ---------------------------------------------------------------------------
# Vector search helper
# ---------------------------------------------------------------------------


def _vector_search(query: str, k: int, collection: str = "default") -> list[dict[str, Any]]:
    """Query ChromaDB and return a list of result dicts.

    Each dict has keys: ``document`` (str), ``score`` (float 0-1),
    ``metadata`` (dict).

    Returns an empty list when ChromaDB is unreachable or returns nothing.
    """
    try:
        from bmt_ai_os.rag.config import RAGConfig
        from bmt_ai_os.rag.storage import ChromaStorage

        config = RAGConfig()
        storage = ChromaStorage(config)
        raw = storage.query(collection, query, top_k=k)

        documents = (raw.get("documents") or [[]])[0]
        metadatas = (raw.get("metadatas") or [[]])[0]
        distances = (raw.get("distances") or [[]])[0]

        results: list[dict[str, Any]] = []
        for doc, meta, dist in zip(documents, metadatas or [{}] * len(documents), distances):
            score = max(0.0, 1.0 - dist)  # cosine distance → similarity
            results.append(
                {
                    "document": doc or "",
                    "score": score,
                    "metadata": meta or {},
                }
            )
        return results

    except Exception as exc:
        logger.warning("Vector search unavailable: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Hybrid search — public API
# ---------------------------------------------------------------------------


def hybrid_search(
    query: str,
    k: int = 5,
    bm25_weight: float = 0.3,
    collection: str = "default",
    documents: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Perform hybrid BM25 + vector search and return the top-*k* results.

    The final score is a weighted average of the normalised BM25 score and
    the normalised vector similarity score::

        hybrid_score = bm25_weight * bm25_norm + (1 - bm25_weight) * vec_norm

    Parameters
    ----------
    query:
        The user's natural-language search query.
    k:
        Number of results to return.
    bm25_weight:
        Weight assigned to BM25 scores (0.0 = vector-only, 1.0 = BM25-only).
        Must be in the range [0, 1].
    collection:
        ChromaDB collection name to search.
    documents:
        Optional pre-loaded document corpus for BM25 scoring.  When *None*
        the vector search results' documents are used as the BM25 corpus.
        Providing an explicit corpus is recommended for offline/unit-test use.

    Returns
    -------
    list[dict]
        Sorted list (highest score first) of result dicts, each with keys:

        * ``document`` (str) — the raw document text
        * ``score`` (float) — hybrid score in [0, 1]
        * ``bm25_score`` (float) — normalised BM25 component
        * ``vector_score`` (float) — normalised vector component
        * ``metadata`` (dict) — ChromaDB metadata (empty when using a local corpus)
    """
    if not 0.0 <= bm25_weight <= 1.0:
        raise ValueError(f"bm25_weight must be in [0, 1], got {bm25_weight!r}")

    vector_weight = 1.0 - bm25_weight

    # ------------------------------------------------------------------
    # 1. Vector retrieval
    # ------------------------------------------------------------------
    vec_results: list[dict[str, Any]] = []
    if vector_weight > 0.0 or documents is None:
        vec_results = _vector_search(query, k=max(k * 2, 20), collection=collection)

    # Determine the BM25 corpus
    if documents is None:
        # Fall back to vector result documents when no corpus is provided
        corpus = [r["document"] for r in vec_results]
        meta_map: dict[str, dict] = {r["document"]: r.get("metadata", {}) for r in vec_results}
    else:
        corpus = documents
        # Merge any vector metadata for docs that appear in both
        meta_map = {r["document"]: r.get("metadata", {}) for r in vec_results}

    if not corpus:
        return []

    # ------------------------------------------------------------------
    # 2. BM25 scoring
    # ------------------------------------------------------------------
    bm25_index = BM25Index(corpus)
    raw_bm25 = bm25_index.score(query)
    norm_bm25 = _min_max_normalise(raw_bm25)

    # ------------------------------------------------------------------
    # 3. Vector scores aligned to corpus order
    # ------------------------------------------------------------------
    # Build a lookup: document text → vector score
    vec_score_map: dict[str, float] = {r["document"]: r["score"] for r in vec_results}
    raw_vec = [vec_score_map.get(doc, 0.0) for doc in corpus]
    norm_vec = _min_max_normalise(raw_vec)

    # ------------------------------------------------------------------
    # 4. Hybrid fusion
    # ------------------------------------------------------------------
    results: list[dict[str, Any]] = []
    for i, doc in enumerate(corpus):
        hybrid_score = bm25_weight * norm_bm25[i] + vector_weight * norm_vec[i]
        results.append(
            {
                "document": doc,
                "score": round(hybrid_score, 6),
                "bm25_score": round(norm_bm25[i], 6),
                "vector_score": round(norm_vec[i], 6),
                "metadata": meta_map.get(doc, {}),
            }
        )

    # Sort by hybrid score descending, de-duplicate by document text
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for r in sorted(results, key=lambda x: x["score"], reverse=True):
        if r["document"] not in seen:
            seen.add(r["document"])
            deduped.append(r)
        if len(deduped) >= k:
            break

    return deduped
