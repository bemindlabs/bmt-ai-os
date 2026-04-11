"""Unit tests for bmt_ai_os.mcp.server — Model Context Protocol server.

Covers:
- JSON-RPC 2.0 protocol dispatch (initialize, ping, resources/*, tools/*)
- Resource fetchers (_fetch_models, _fetch_status, _fetch_providers)
- Tool executors (chat, pull_model, query_rag, list_models)
- Error handling (parse error, method not found, invalid params)
- /mcp/info convenience endpoint
- create_mcp_app standalone factory
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch):
    monkeypatch.setenv("BMT_JWT_SECRET", "test-secret-key-for-mcp-server-32chars!")


@pytest.fixture()
def mcp_client():
    """TestClient for the main controller app with the MCP router mounted."""
    from bmt_ai_os.controller.api import app

    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture()
def standalone_client():
    """TestClient for the standalone MCP FastAPI app."""
    from bmt_ai_os.mcp.server import create_mcp_app

    return TestClient(create_mcp_app(), raise_server_exceptions=True)


def _rpc(method: str, params: dict | None = None, id: int = 1) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": id, "method": method}
    if params is not None:
        body["params"] = params
    return body


# ---------------------------------------------------------------------------
# /mcp/info endpoint
# ---------------------------------------------------------------------------


class TestMcpInfo:
    def test_info_returns_200(self, mcp_client):
        resp = mcp_client.get("/mcp/info")
        assert resp.status_code == 200

    def test_info_contains_server_name(self, mcp_client):
        data = mcp_client.get("/mcp/info").json()
        assert data["server"]["name"] == "bmt-ai-os"

    def test_info_lists_resources(self, mcp_client):
        data = mcp_client.get("/mcp/info").json()
        assert "bmt://models" in data["resources"]
        assert "bmt://status" in data["resources"]
        assert "bmt://providers" in data["resources"]

    def test_info_lists_tools(self, mcp_client):
        data = mcp_client.get("/mcp/info").json()
        for tool in ("chat", "pull_model", "query_rag", "list_models"):
            assert tool in data["tools"]

    def test_info_mcp_version(self, mcp_client):
        data = mcp_client.get("/mcp/info").json()
        assert data["mcp_version"] == "2024-11-05"


# ---------------------------------------------------------------------------
# JSON-RPC protocol tests
# ---------------------------------------------------------------------------


class TestJsonRpcProtocol:
    def test_parse_error_non_json_body(self, mcp_client):
        resp = mcp_client.post(
            "/mcp/",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data
        assert data["error"]["code"] == -32700  # Parse error

    def test_invalid_request_missing_method(self, mcp_client):
        resp = mcp_client.post("/mcp/", json={"jsonrpc": "2.0", "id": 1})
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data
        assert data["error"]["code"] == -32600  # Invalid request

    def test_method_not_found(self, mcp_client):
        resp = mcp_client.post("/mcp/", json=_rpc("nonexistent/method"))
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"]["code"] == -32601  # Method not found

    def test_ping_returns_empty_result(self, mcp_client):
        resp = mcp_client.post("/mcp/", json=_rpc("ping"))
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        assert data["result"] == {}
        assert data["id"] == 1

    def test_response_preserves_request_id(self, mcp_client):
        resp = mcp_client.post("/mcp/", json=_rpc("ping", id=42))
        assert resp.json()["id"] == 42

    def test_jsonrpc_version_in_response(self, mcp_client):
        resp = mcp_client.post("/mcp/", json=_rpc("ping"))
        assert resp.json()["jsonrpc"] == "2.0"


# ---------------------------------------------------------------------------
# initialize
# ---------------------------------------------------------------------------


class TestInitialize:
    def test_initialize_returns_protocol_version(self, mcp_client):
        resp = mcp_client.post("/mcp/", json=_rpc("initialize"))
        data = resp.json()
        assert "result" in data
        assert data["result"]["protocolVersion"] == "2024-11-05"

    def test_initialize_returns_capabilities(self, mcp_client):
        resp = mcp_client.post("/mcp/", json=_rpc("initialize"))
        caps = resp.json()["result"]["capabilities"]
        assert "resources" in caps
        assert "tools" in caps

    def test_initialize_returns_server_info(self, mcp_client):
        resp = mcp_client.post("/mcp/", json=_rpc("initialize"))
        info = resp.json()["result"]["serverInfo"]
        assert info["name"] == "bmt-ai-os"


# ---------------------------------------------------------------------------
# resources/list
# ---------------------------------------------------------------------------


class TestResourcesList:
    def test_resources_list_returns_three_resources(self, mcp_client):
        resp = mcp_client.post("/mcp/", json=_rpc("resources/list"))
        resources = resp.json()["result"]["resources"]
        uris = [r["uri"] for r in resources]
        assert "bmt://models" in uris
        assert "bmt://status" in uris
        assert "bmt://providers" in uris

    def test_resources_have_required_fields(self, mcp_client):
        resp = mcp_client.post("/mcp/", json=_rpc("resources/list"))
        for r in resp.json()["result"]["resources"]:
            assert "uri" in r
            assert "name" in r
            assert "mimeType" in r


# ---------------------------------------------------------------------------
# resources/read
# ---------------------------------------------------------------------------


class TestResourcesRead:
    def test_missing_uri_param_returns_error(self, mcp_client):
        resp = mcp_client.post("/mcp/", json=_rpc("resources/read", params={}))
        data = resp.json()
        assert data["error"]["code"] == -32602  # Invalid params

    def test_unknown_uri_returns_error(self, mcp_client):
        resp = mcp_client.post(
            "/mcp/", json=_rpc("resources/read", params={"uri": "bmt://unknown"})
        )
        data = resp.json()
        assert data["error"]["code"] == -32602

    def test_read_models_resource(self, mcp_client):
        mock_registry = MagicMock()
        mock_provider = MagicMock()
        mock_provider.list_models = AsyncMock(return_value=[{"name": "qwen2.5-coder:7b"}])
        mock_registry.get_active.return_value = mock_provider

        with patch("bmt_ai_os.mcp.server.get_registry", return_value=mock_registry):
            resp = mcp_client.post(
                "/mcp/", json=_rpc("resources/read", params={"uri": "bmt://models"})
            )
        data = resp.json()
        assert "result" in data
        contents = data["result"]["contents"]
        assert len(contents) == 1
        assert contents[0]["uri"] == "bmt://models"

    def test_read_status_resource(self, mcp_client):
        resp = mcp_client.post("/mcp/", json=_rpc("resources/read", params={"uri": "bmt://status"}))
        data = resp.json()
        assert "result" in data
        text = data["result"]["contents"][0]["text"]
        assert "version" in text

    def test_read_providers_resource(self, mcp_client):
        mock_registry = MagicMock()
        mock_registry.list.return_value = ["ollama"]
        mock_registry.active_name = "ollama"

        with patch("bmt_ai_os.mcp.server.get_registry", return_value=mock_registry):
            resp = mcp_client.post(
                "/mcp/", json=_rpc("resources/read", params={"uri": "bmt://providers"})
            )
        data = resp.json()
        assert "result" in data


# ---------------------------------------------------------------------------
# tools/list
# ---------------------------------------------------------------------------


class TestToolsList:
    def test_tools_list_returns_four_tools(self, mcp_client):
        resp = mcp_client.post("/mcp/", json=_rpc("tools/list"))
        tools = resp.json()["result"]["tools"]
        names = [t["name"] for t in tools]
        assert set(names) == {"chat", "pull_model", "query_rag", "list_models"}

    def test_tools_have_input_schema(self, mcp_client):
        resp = mcp_client.post("/mcp/", json=_rpc("tools/list"))
        for t in resp.json()["result"]["tools"]:
            assert "inputSchema" in t
            assert t["inputSchema"]["type"] == "object"

    def test_chat_tool_requires_message(self, mcp_client):
        resp = mcp_client.post("/mcp/", json=_rpc("tools/list"))
        chat = next(t for t in resp.json()["result"]["tools"] if t["name"] == "chat")
        assert "message" in chat["inputSchema"]["required"]


# ---------------------------------------------------------------------------
# tools/call — valid invocations
# ---------------------------------------------------------------------------


class TestToolsCallChat:
    def test_chat_returns_text_content(self, mcp_client):
        mock_registry = MagicMock()
        mock_provider = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Hello from BMT AI OS!"
        mock_provider.chat = AsyncMock(return_value=mock_response)
        mock_registry.get_active.return_value = mock_provider

        with patch("bmt_ai_os.mcp.server.get_registry", return_value=mock_registry):
            resp = mcp_client.post(
                "/mcp/",
                json=_rpc(
                    "tools/call",
                    params={"name": "chat", "arguments": {"message": "Hello!"}},
                ),
            )
        data = resp.json()
        assert "result" in data
        assert data["result"]["isError"] is False
        content = data["result"]["content"]
        assert content[0]["type"] == "text"
        assert "Hello from BMT AI OS!" in content[0]["text"]

    def test_chat_error_on_provider_failure(self, mcp_client):
        mock_registry = MagicMock()
        mock_provider = MagicMock()
        mock_provider.chat = AsyncMock(side_effect=RuntimeError("provider down"))
        mock_registry.get_active.return_value = mock_provider

        with patch("bmt_ai_os.mcp.server.get_registry", return_value=mock_registry):
            resp = mcp_client.post(
                "/mcp/",
                json=_rpc(
                    "tools/call",
                    params={"name": "chat", "arguments": {"message": "Hi"}},
                ),
            )
        data = resp.json()
        assert data["error"]["code"] == -32603  # Internal error


class TestToolsCallListModels:
    def test_list_models_returns_model_names(self, mcp_client):
        mock_registry = MagicMock()
        mock_provider = MagicMock()
        mock_provider.list_models = AsyncMock(
            return_value=[{"name": "qwen2.5-coder:7b"}, {"name": "nomic-embed-text"}]
        )
        mock_registry.get_active.return_value = mock_provider

        with patch("bmt_ai_os.mcp.server.get_registry", return_value=mock_registry):
            resp = mcp_client.post(
                "/mcp/",
                json=_rpc("tools/call", params={"name": "list_models", "arguments": {}}),
            )
        data = resp.json()
        assert "result" in data
        assert data["result"]["isError"] is False


class TestToolsCallQueryRag:
    def test_query_rag_returns_context(self, mcp_client):
        mock_storage = MagicMock()
        mock_storage.query.return_value = {
            "documents": [["Vector search uses embeddings.", "HNSW is an ANN algorithm."]]
        }

        with (
            patch("bmt_ai_os.mcp.server.ChromaStorage", return_value=mock_storage),
            patch("bmt_ai_os.mcp.server.RAGConfig"),
        ):
            resp = mcp_client.post(
                "/mcp/",
                json=_rpc(
                    "tools/call",
                    params={
                        "name": "query_rag",
                        "arguments": {"question": "What is vector search?"},
                    },
                ),
            )
        data = resp.json()
        assert "result" in data
        assert data["result"]["isError"] is False

    def test_query_rag_no_results(self, mcp_client):
        mock_storage = MagicMock()
        mock_storage.query.return_value = {"documents": [[]]}

        with (
            patch("bmt_ai_os.mcp.server.ChromaStorage", return_value=mock_storage),
            patch("bmt_ai_os.mcp.server.RAGConfig"),
        ):
            resp = mcp_client.post(
                "/mcp/",
                json=_rpc(
                    "tools/call",
                    params={"name": "query_rag", "arguments": {"question": "Anything"}},
                ),
            )
        data = resp.json()
        assert "result" in data
        assert "No relevant context" in data["result"]["content"][0]["text"]


class TestToolsCallPullModel:
    def test_pull_model_missing_arg_returns_error(self, mcp_client):
        resp = mcp_client.post(
            "/mcp/",
            json=_rpc("tools/call", params={"name": "pull_model", "arguments": {"model": ""}}),
        )
        data = resp.json()
        assert data["error"]["code"] == -32602  # Invalid params (ValueError)


# ---------------------------------------------------------------------------
# tools/call — error paths
# ---------------------------------------------------------------------------


class TestToolsCallErrors:
    def test_missing_name_param(self, mcp_client):
        resp = mcp_client.post("/mcp/", json=_rpc("tools/call", params={}))
        data = resp.json()
        assert data["error"]["code"] == -32602

    def test_unknown_tool_name(self, mcp_client):
        resp = mcp_client.post(
            "/mcp/",
            json=_rpc("tools/call", params={"name": "nonexistent_tool", "arguments": {}}),
        )
        data = resp.json()
        assert data["error"]["code"] == -32601  # Method not found


# ---------------------------------------------------------------------------
# Resource fetchers (unit tests for the async helpers)
# ---------------------------------------------------------------------------


class TestFetchHelpers:
    @pytest.mark.asyncio
    async def test_fetch_models_returns_list_on_success(self):
        from bmt_ai_os.mcp.server import _fetch_models

        mock_registry = MagicMock()
        mock_provider = MagicMock()
        mock_provider.list_models = AsyncMock(return_value=[{"name": "qwen2.5-coder:7b"}])
        mock_registry.get_active.return_value = mock_provider

        with patch("bmt_ai_os.mcp.server.get_registry", return_value=mock_registry):
            models = await _fetch_models()

        assert isinstance(models, list)
        assert models[0]["name"] == "qwen2.5-coder:7b"

    @pytest.mark.asyncio
    async def test_fetch_models_returns_empty_on_error(self):
        from bmt_ai_os.mcp.server import _fetch_models

        with patch("bmt_ai_os.mcp.server.get_registry", side_effect=RuntimeError("no registry")):
            models = await _fetch_models()

        assert models == []

    @pytest.mark.asyncio
    async def test_fetch_status_without_controller(self):
        from bmt_ai_os.mcp.server import _fetch_status

        with patch("bmt_ai_os.mcp.server.get_controller", return_value=None):
            status = await _fetch_status()

        assert status["version"] == "2026.4.11"
        assert status["status"] == "running"

    @pytest.mark.asyncio
    async def test_fetch_providers_returns_dict(self):
        from bmt_ai_os.mcp.server import _fetch_providers

        mock_registry = MagicMock()
        mock_registry.list.return_value = ["ollama"]
        mock_registry.active_name = "ollama"

        with patch("bmt_ai_os.mcp.server.get_registry", return_value=mock_registry):
            result = await _fetch_providers()

        assert result["providers"] == ["ollama"]
        assert result["active"] == "ollama"

    @pytest.mark.asyncio
    async def test_fetch_providers_returns_empty_on_error(self):
        from bmt_ai_os.mcp.server import _fetch_providers

        with patch("bmt_ai_os.mcp.server.get_registry", side_effect=RuntimeError("nope")):
            result = await _fetch_providers()

        assert result["providers"] == []
        assert result["active"] is None


# ---------------------------------------------------------------------------
# Standalone app factory
# ---------------------------------------------------------------------------


class TestCreateMcpApp:
    def test_create_mcp_app_is_fastapi(self):
        from fastapi import FastAPI

        from bmt_ai_os.mcp.server import create_mcp_app

        app = create_mcp_app()
        assert isinstance(app, FastAPI)

    def test_standalone_app_ping(self, standalone_client):
        resp = standalone_client.post("/mcp/", json=_rpc("ping"))
        assert resp.status_code == 200
        assert resp.json()["result"] == {}

    def test_standalone_app_info(self, standalone_client):
        resp = standalone_client.get("/mcp/info")
        assert resp.status_code == 200
        assert "bmt-ai-os" in resp.json()["server"]["name"]
