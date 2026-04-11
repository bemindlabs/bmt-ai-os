"""Unit tests for bmt_ai_os.rag.storage."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from bmt_ai_os.rag.config import RAGConfig
from bmt_ai_os.rag.storage import ChromaStorage


def _make_config(**overrides) -> RAGConfig:
    defaults = dict(
        chromadb_url="http://localhost:8000",
        ollama_url="http://localhost:11434",
        embedding_model="nomic-embed-text",
        embed_timeout=30,
    )
    defaults.update(overrides)
    return RAGConfig(**defaults)


def _make_storage(**cfg_overrides) -> ChromaStorage:
    config = _make_config(**cfg_overrides)
    storage = ChromaStorage.__new__(ChromaStorage)
    storage.config = config
    storage.base_url = config.chromadb_url.rstrip("/")
    # Mock the embeddings object so network calls are intercepted
    storage.embeddings = MagicMock()
    storage.embeddings.embed_batch.return_value = [[0.1, 0.2, 0.3]]
    storage.embeddings.embed.return_value = [0.1, 0.2, 0.3]
    return storage


class TestListCollections:
    def test_returns_list_from_api(self):
        storage = _make_storage()
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"name": "docs", "id": "col-1"}]
        with patch("bmt_ai_os.rag.storage.requests.get", return_value=mock_resp):
            result = storage.list_collections()
        assert result == [{"name": "docs", "id": "col-1"}]
        mock_resp.raise_for_status.assert_called_once()

    def test_raises_on_http_error(self):
        storage = _make_storage()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("404")
        with patch("bmt_ai_os.rag.storage.requests.get", return_value=mock_resp):
            with pytest.raises(requests.HTTPError):
                storage.list_collections()


class TestGetOrCreateCollection:
    def test_returns_collection_id(self):
        storage = _make_storage()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": "col-abc", "name": "my-docs"}
        with patch("bmt_ai_os.rag.storage.requests.post", return_value=mock_resp) as mock_post:
            col_id = storage.get_or_create_collection("my-docs")
        assert col_id == "col-abc"
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"]["name"] == "my-docs"
        assert call_kwargs["json"]["get_or_create"] is True

    def test_sends_to_correct_url(self):
        storage = _make_storage()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": "x"}
        with patch("bmt_ai_os.rag.storage.requests.post", return_value=mock_resp) as mock_post:
            storage.get_or_create_collection("col")
        url = mock_post.call_args[0][0]
        assert url == "http://localhost:8000/api/v1/collections"


class TestUpsert:
    def test_upserts_with_embeddings(self):
        storage = _make_storage()
        storage.embeddings.embed_batch.return_value = [[0.1, 0.2], [0.3, 0.4]]

        # Mock get_or_create_collection
        get_resp = MagicMock()
        get_resp.json.return_value = {"id": "col-1"}

        upsert_resp = MagicMock()

        with patch(
            "bmt_ai_os.rag.storage.requests.post", side_effect=[get_resp, upsert_resp]
        ) as mock_post:
            storage.upsert(
                collection="docs",
                ids=["doc-1", "doc-2"],
                documents=["hello", "world"],
            )

        # Second call is the upsert
        upsert_call = mock_post.call_args_list[1]
        payload = upsert_call[1]["json"]
        assert payload["ids"] == ["doc-1", "doc-2"]
        assert payload["documents"] == ["hello", "world"]
        assert payload["embeddings"] == [[0.1, 0.2], [0.3, 0.4]]

    def test_upsert_includes_metadatas_when_provided(self):
        storage = _make_storage()
        storage.embeddings.embed_batch.return_value = [[0.1]]

        get_resp = MagicMock()
        get_resp.json.return_value = {"id": "col-1"}
        upsert_resp = MagicMock()

        with patch(
            "bmt_ai_os.rag.storage.requests.post", side_effect=[get_resp, upsert_resp]
        ) as mock_post:
            storage.upsert(
                collection="docs",
                ids=["doc-1"],
                documents=["hello"],
                metadatas=[{"source": "readme.md"}],
            )

        payload = mock_post.call_args_list[1][1]["json"]
        assert payload["metadatas"] == [{"source": "readme.md"}]

    def test_upsert_omits_metadatas_when_none(self):
        storage = _make_storage()
        storage.embeddings.embed_batch.return_value = [[0.1]]

        get_resp = MagicMock()
        get_resp.json.return_value = {"id": "col-1"}
        upsert_resp = MagicMock()

        with patch(
            "bmt_ai_os.rag.storage.requests.post", side_effect=[get_resp, upsert_resp]
        ) as mock_post:
            storage.upsert("docs", ["doc-1"], ["hello"])

        payload = mock_post.call_args_list[1][1]["json"]
        assert "metadatas" not in payload


class TestQuery:
    def test_returns_chroma_response(self):
        storage = _make_storage()
        storage.embeddings.embed.return_value = [0.1, 0.2, 0.3]

        get_resp = MagicMock()
        get_resp.json.return_value = {"id": "col-1"}

        query_resp = MagicMock()
        query_resp.json.return_value = {
            "ids": [["doc-1"]],
            "documents": [["hello"]],
            "metadatas": [[{"source": "readme"}]],
            "distances": [[0.05]],
        }

        with patch("bmt_ai_os.rag.storage.requests.post", side_effect=[get_resp, query_resp]):
            result = storage.query("docs", "hello world", top_k=1)

        assert result["ids"] == [["doc-1"]]
        assert result["documents"] == [["hello"]]

    def test_query_sends_correct_payload(self):
        storage = _make_storage()
        storage.embeddings.embed.return_value = [0.5]

        get_resp = MagicMock()
        get_resp.json.return_value = {"id": "col-q"}
        query_resp = MagicMock()
        query_resp.json.return_value = {
            "ids": [],
            "documents": [],
            "metadatas": [],
            "distances": [],
        }

        with patch(
            "bmt_ai_os.rag.storage.requests.post", side_effect=[get_resp, query_resp]
        ) as mock_post:
            storage.query("docs", "test query", top_k=3)

        query_payload = mock_post.call_args_list[1][1]["json"]
        assert query_payload["query_embeddings"] == [[0.5]]
        assert query_payload["n_results"] == 3
        assert "documents" in query_payload["include"]
