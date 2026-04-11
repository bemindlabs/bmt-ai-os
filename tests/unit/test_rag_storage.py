"""Unit tests for bmt_ai_os.rag.storage.ChromaStorage.

All HTTP calls to ChromaDB are intercepted with unittest.mock.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from bmt_ai_os.rag.config import RAGConfig
from bmt_ai_os.rag.storage import ChromaStorage

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def config() -> RAGConfig:
    return RAGConfig(
        chromadb_url="http://localhost:8000",
        ollama_url="http://localhost:11434",
    )


@pytest.fixture()
def storage(config: RAGConfig) -> ChromaStorage:
    return ChromaStorage(config)


def _mock_response(json_data, status_code: int = 200) -> MagicMock:
    """Build a mock requests.Response."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data
    mock.raise_for_status = MagicMock()
    if status_code >= 400:
        mock.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status_code}")
    return mock


# ---------------------------------------------------------------------------
# list_collections
# ---------------------------------------------------------------------------


class TestListCollections:
    def test_returns_collection_list(self, storage: ChromaStorage) -> None:
        fake_collections = [{"id": "abc", "name": "default"}, {"id": "xyz", "name": "code"}]
        with patch("requests.get", return_value=_mock_response(fake_collections)):
            result = storage.list_collections()
        assert len(result) == 2
        assert result[0]["name"] == "default"

    def test_empty_collections(self, storage: ChromaStorage) -> None:
        with patch("requests.get", return_value=_mock_response([])):
            result = storage.list_collections()
        assert result == []

    def test_raises_on_http_error(self, storage: ChromaStorage) -> None:
        with patch("requests.get", return_value=_mock_response({}, status_code=500)):
            with pytest.raises(requests.HTTPError):
                storage.list_collections()


# ---------------------------------------------------------------------------
# get_or_create_collection
# ---------------------------------------------------------------------------


class TestGetOrCreateCollection:
    def test_returns_collection_id(self, storage: ChromaStorage) -> None:
        mock_col = _mock_response({"id": "col-123", "name": "default"})
        with patch("requests.post", return_value=mock_col):
            col_id = storage.get_or_create_collection("default")
        assert col_id == "col-123"

    def test_posts_correct_payload(self, storage: ChromaStorage) -> None:
        with patch("requests.post", return_value=_mock_response({"id": "abc"})) as mock_post:
            storage.get_or_create_collection("my-collection")
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"]["name"] == "my-collection"
        assert call_kwargs["json"]["get_or_create"] is True

    def test_raises_on_error(self, storage: ChromaStorage) -> None:
        with patch("requests.post", return_value=_mock_response({}, status_code=400)):
            with pytest.raises(requests.HTTPError):
                storage.get_or_create_collection("bad")


# ---------------------------------------------------------------------------
# upsert
# ---------------------------------------------------------------------------


class TestUpsert:
    def test_upsert_calls_embed_and_post(self, storage: ChromaStorage) -> None:
        vectors = [[0.1, 0.2], [0.3, 0.4]]
        with (
            patch.object(storage, "get_or_create_collection", return_value="col-1"),
            patch.object(storage.embeddings, "embed_batch", return_value=vectors),
            patch("requests.post", return_value=_mock_response({})) as mock_post,
        ):
            storage.upsert(
                "default",
                ids=["a", "b"],
                documents=["doc a", "doc b"],
            )
        assert mock_post.called
        post_payload = mock_post.call_args[1]["json"]
        assert post_payload["ids"] == ["a", "b"]
        assert post_payload["embeddings"] == vectors

    def test_upsert_includes_metadatas_when_provided(self, storage: ChromaStorage) -> None:
        vectors = [[0.1]]
        metas = [{"source": "readme.md"}]
        with (
            patch.object(storage, "get_or_create_collection", return_value="col-1"),
            patch.object(storage.embeddings, "embed_batch", return_value=vectors),
            patch("requests.post", return_value=_mock_response({})) as mock_post,
        ):
            storage.upsert("default", ids=["a"], documents=["doc"], metadatas=metas)
        payload = mock_post.call_args[1]["json"]
        assert payload["metadatas"] == metas

    def test_upsert_no_metadatas_omitted(self, storage: ChromaStorage) -> None:
        with (
            patch.object(storage, "get_or_create_collection", return_value="col-1"),
            patch.object(storage.embeddings, "embed_batch", return_value=[[0.1]]),
            patch("requests.post", return_value=_mock_response({})) as mock_post,
        ):
            storage.upsert("default", ids=["a"], documents=["doc"])
        payload = mock_post.call_args[1]["json"]
        assert "metadatas" not in payload


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------


class TestQuery:
    def test_query_returns_chromadb_response(self, storage: ChromaStorage) -> None:
        chroma_response = {
            "ids": [["id-1"]],
            "documents": [["doc text"]],
            "metadatas": [[{"filename": "a.md"}]],
            "distances": [[0.05]],
        }
        with (
            patch.object(storage, "get_or_create_collection", return_value="col-1"),
            patch.object(storage.embeddings, "embed", return_value=[0.1, 0.2, 0.3]),
            patch("requests.post", return_value=_mock_response(chroma_response)),
        ):
            result = storage.query("default", "What is X?", top_k=1)
        assert result["ids"] == [["id-1"]]
        assert result["documents"] == [["doc text"]]

    def test_query_sends_correct_top_k(self, storage: ChromaStorage) -> None:
        chroma_response = {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
        with (
            patch.object(storage, "get_or_create_collection", return_value="col-1"),
            patch.object(storage.embeddings, "embed", return_value=[0.0]),
            patch("requests.post", return_value=_mock_response(chroma_response)) as mock_post,
        ):
            storage.query("default", "query", top_k=7)
        payload = mock_post.call_args[1]["json"]
        assert payload["n_results"] == 7

    def test_query_includes_required_fields(self, storage: ChromaStorage) -> None:
        chroma_response = {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
        with (
            patch.object(storage, "get_or_create_collection", return_value="col-1"),
            patch.object(storage.embeddings, "embed", return_value=[0.0]),
            patch("requests.post", return_value=_mock_response(chroma_response)) as mock_post,
        ):
            storage.query("default", "query")
        payload = mock_post.call_args[1]["json"]
        assert "documents" in payload["include"]
        assert "metadatas" in payload["include"]
        assert "distances" in payload["include"]

    def test_query_raises_on_http_error(self, storage: ChromaStorage) -> None:
        with (
            patch.object(storage, "get_or_create_collection", return_value="col-1"),
            patch.object(storage.embeddings, "embed", return_value=[0.0]),
            patch("requests.post", return_value=_mock_response({}, status_code=500)),
        ):
            with pytest.raises(requests.HTTPError):
                storage.query("default", "query")


# ---------------------------------------------------------------------------
# base_url normalization
# ---------------------------------------------------------------------------


class TestBaseUrlNormalization:
    def test_trailing_slash_stripped(self) -> None:
        cfg = RAGConfig(chromadb_url="http://localhost:8000/")
        s = ChromaStorage(cfg)
        assert s.base_url == "http://localhost:8000"

    def test_no_trailing_slash_unchanged(self) -> None:
        cfg = RAGConfig(chromadb_url="http://localhost:8000")
        s = ChromaStorage(cfg)
        assert s.base_url == "http://localhost:8000"
