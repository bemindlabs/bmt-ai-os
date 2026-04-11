"""Unit tests for bmt_ai_os.rag.embeddings.OllamaEmbeddings.

All HTTP calls are mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from bmt_ai_os.rag.config import RAGConfig
from bmt_ai_os.rag.embeddings import OllamaEmbeddings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def config() -> RAGConfig:
    return RAGConfig(
        ollama_url="http://localhost:11434",
        embedding_model="nomic-embed-text",
        embed_timeout=10,
    )


@pytest.fixture()
def embedder(config: RAGConfig) -> OllamaEmbeddings:
    return OllamaEmbeddings(config)


def _mock_embed_response(embeddings: list[list[float]]) -> MagicMock:
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    mock.json.return_value = {"embeddings": embeddings}
    return mock


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_base_url_trailing_slash_stripped(self):
        cfg = RAGConfig(ollama_url="http://localhost:11434/")
        e = OllamaEmbeddings(cfg)
        assert e.base_url == "http://localhost:11434"

    def test_base_url_no_trailing_slash(self):
        cfg = RAGConfig(ollama_url="http://localhost:11434")
        e = OllamaEmbeddings(cfg)
        assert e.base_url == "http://localhost:11434"


# ---------------------------------------------------------------------------
# embed_batch
# ---------------------------------------------------------------------------


class TestEmbedBatch:
    def test_returns_list_of_vectors(self, embedder: OllamaEmbeddings) -> None:
        expected = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        with patch("requests.post", return_value=_mock_embed_response(expected)):
            result = embedder.embed_batch(["text a", "text b"])
        assert result == expected

    def test_posts_to_correct_url(self, embedder: OllamaEmbeddings) -> None:
        with patch("requests.post", return_value=_mock_embed_response([[0.1]])) as mock_post:
            embedder.embed_batch(["text"])
        url = mock_post.call_args[0][0]
        assert url == "http://localhost:11434/api/embed"

    def test_uses_configured_model(self, embedder: OllamaEmbeddings) -> None:
        with patch("requests.post", return_value=_mock_embed_response([[0.1]])) as mock_post:
            embedder.embed_batch(["text"])
        payload = mock_post.call_args[1]["json"]
        assert payload["model"] == "nomic-embed-text"

    def test_sends_all_texts_in_batch(self, embedder: OllamaEmbeddings) -> None:
        texts = ["alpha", "beta", "gamma"]
        with patch(
            "requests.post",
            return_value=_mock_embed_response([[0.1], [0.2], [0.3]]),
        ) as mock_post:
            embedder.embed_batch(texts)
        payload = mock_post.call_args[1]["json"]
        assert payload["input"] == texts

    def test_raises_on_http_error(self, embedder: OllamaEmbeddings) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("500")
        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(requests.HTTPError):
                embedder.embed_batch(["text"])

    def test_single_text_batch(self, embedder: OllamaEmbeddings) -> None:
        with patch("requests.post", return_value=_mock_embed_response([[0.9, 0.8]])):
            result = embedder.embed_batch(["single text"])
        assert len(result) == 1
        assert result[0] == [0.9, 0.8]


# ---------------------------------------------------------------------------
# embed (single text)
# ---------------------------------------------------------------------------


class TestEmbed:
    def test_returns_single_vector(self, embedder: OllamaEmbeddings) -> None:
        with patch("requests.post", return_value=_mock_embed_response([[0.1, 0.2, 0.3]])):
            result = embedder.embed("hello world")
        assert result == [0.1, 0.2, 0.3]

    def test_delegates_to_embed_batch(self, embedder: OllamaEmbeddings) -> None:
        with patch.object(embedder, "embed_batch", return_value=[[0.5, 0.6]]) as mock_batch:
            result = embedder.embed("test")
        mock_batch.assert_called_once_with(["test"])
        assert result == [0.5, 0.6]

    def test_returns_first_element(self, embedder: OllamaEmbeddings) -> None:
        with patch.object(embedder, "embed_batch", return_value=[[1.0], [2.0]]):
            result = embedder.embed("text")
        assert result == [1.0]
