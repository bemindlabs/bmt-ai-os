"""BMT AI OS — Model Context Protocol (MCP) server.

Implements a JSON-RPC 2.0 based MCP server following the MCP specification
(https://modelcontextprotocol.io/specification).  The server is exposed as:

  - A FastAPI sub-application mountable at ``/mcp/`` in the main controller.
  - A standalone uvicorn application started by ``bmt-ai-os mcp serve``.

Protocol overview
-----------------
All requests are ``POST /mcp/`` (JSON-RPC 2.0 envelope).  The ``method`` field
selects the operation:

  initialize              — handshake; returns server capabilities
  resources/list          — enumerate available BMT resources
  resources/read          — fetch a resource by URI
  tools/list              — enumerate available tools
  tools/call              — invoke a tool by name
  ping                    — liveness probe (returns empty result)

Resources
---------
  bmt://models            — installed Ollama models (array)
  bmt://status            — controller system status snapshot
  bmt://providers         — registered provider names + active flag

Tools
-----
  chat                    — send a chat message to the active provider
  pull_model              — pull an Ollama model by name
  query_rag               — query the RAG pipeline
  list_models             — list installed models (tool form)
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy-imported singletons (imported here so tests can patch at this namespace)
# ---------------------------------------------------------------------------


def get_registry():
    """Return the provider registry singleton (lazy import, patchable in tests)."""
    from bmt_ai_os.providers.registry import get_registry as _get_registry

    return _get_registry()


def get_controller():
    """Return the current controller instance (lazy import, patchable in tests)."""
    from bmt_ai_os.controller.api import get_controller as _get_controller

    return _get_controller()


def RAGConfig(*args, **kwargs):  # noqa: N802
    """Proxy to bmt_ai_os.rag.config.RAGConfig (patchable in tests)."""
    from bmt_ai_os.rag.config import RAGConfig as _RAGConfig

    return _RAGConfig(*args, **kwargs)


def ChromaStorage(*args, **kwargs):  # noqa: N802
    """Proxy to bmt_ai_os.rag.storage.ChromaStorage (patchable in tests)."""
    from bmt_ai_os.rag.storage import ChromaStorage as _ChromaStorage

    return _ChromaStorage(*args, **kwargs)


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 envelope schemas
# ---------------------------------------------------------------------------

_JSONRPC = "2.0"
_MCP_VERSION = "2024-11-05"


class _RpcRequest(BaseModel):
    jsonrpc: str = _JSONRPC
    id: int | str | None = None
    method: str
    params: dict[str, Any] | None = None


class _RpcError(BaseModel):
    code: int
    message: str
    data: Any | None = None


# ---------------------------------------------------------------------------
# MCP Server capabilities
# ---------------------------------------------------------------------------

_SERVER_INFO = {
    "name": "bmt-ai-os",
    "version": "2026.4.11",
}

_CAPABILITIES = {
    "resources": {"subscribe": False, "listChanged": False},
    "tools": {"listChanged": False},
}

# ---------------------------------------------------------------------------
# Resource definitions
# ---------------------------------------------------------------------------

_RESOURCES = [
    {
        "uri": "bmt://models",
        "name": "Installed Models",
        "description": "List of all models installed in the Ollama registry.",
        "mimeType": "application/json",
    },
    {
        "uri": "bmt://status",
        "name": "System Status",
        "description": "Current status of the BMT AI OS controller and services.",
        "mimeType": "application/json",
    },
    {
        "uri": "bmt://providers",
        "name": "LLM Providers",
        "description": "Registered LLM providers and the currently active provider.",
        "mimeType": "application/json",
    },
]

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

_TOOLS = [
    {
        "name": "chat",
        "description": "Send a chat message to the active BMT AI OS provider and receive a reply.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "User message to send."},
                "model": {
                    "type": "string",
                    "description": "Optional model override (e.g. qwen2.5-coder:7b).",
                },
                "temperature": {
                    "type": "number",
                    "description": "Sampling temperature (0.0–1.0).",
                    "default": 0.7,
                },
            },
            "required": ["message"],
        },
    },
    {
        "name": "pull_model",
        "description": "Pull a model from the Ollama registry onto this device.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Ollama model tag to pull (e.g. qwen2.5-coder:7b).",
                }
            },
            "required": ["model"],
        },
    },
    {
        "name": "query_rag",
        "description": "Query the BMT AI OS RAG pipeline with a natural-language question.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to answer via RAG."},
                "collection": {
                    "type": "string",
                    "description": "ChromaDB collection name (default: 'default').",
                    "default": "default",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of chunks to retrieve.",
                    "default": 3,
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "list_models",
        "description": "List all models installed on this BMT AI OS device.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


# ---------------------------------------------------------------------------
# Resource fetchers
# ---------------------------------------------------------------------------


async def _fetch_models() -> list[dict[str, Any]]:
    """Return installed Ollama models by querying the provider registry."""
    try:
        registry = get_registry()
        provider = registry.get_active()
        models = await provider.list_models()
        out = []
        for m in models:
            if isinstance(m, dict):
                out.append(m)
            elif hasattr(m, "to_dict"):
                out.append(m.to_dict())
            else:
                out.append({"name": str(m)})
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("MCP: failed to list models: %s", exc)
        return []


async def _fetch_status() -> dict[str, Any]:
    """Return a system status snapshot."""
    try:
        ctrl = get_controller()
        if ctrl is not None:
            return {
                "version": "2026.4.11",
                "status": "running",
                "uptime_seconds": round(time.time() - ctrl._start_time, 1),
                "services": ctrl.get_status(),
            }
    except Exception:  # noqa: BLE001
        pass
    return {"version": "2026.4.11", "status": "running", "uptime_seconds": None, "services": []}


async def _fetch_providers() -> dict[str, Any]:
    """Return registered provider names and the active provider."""
    try:
        registry = get_registry()
        return {
            "providers": registry.list(),
            "active": registry.active_name,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("MCP: failed to fetch providers: %s", exc)
        return {"providers": [], "active": None}


# ---------------------------------------------------------------------------
# Tool executors
# ---------------------------------------------------------------------------


async def _tool_chat(args: dict[str, Any]) -> str:
    """Send a chat message to the active provider."""
    message = args.get("message", "")
    model = args.get("model") or None
    temperature = float(args.get("temperature", 0.7))

    try:
        from bmt_ai_os.providers.base import ChatMessage

        registry = get_registry()
        provider = registry.get_active()
        msg = ChatMessage(role="user", content=message)
        response = await provider.chat(
            [msg],
            model=model,
            temperature=temperature,
            max_tokens=4096,
            stream=False,
        )
        return getattr(response, "content", str(response))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"chat failed: {exc}") from exc


async def _tool_pull_model(args: dict[str, Any]) -> str:
    """Pull an Ollama model by name via the Ollama HTTP API."""
    model = args.get("model", "").strip()
    if not model:
        raise ValueError("model parameter is required")

    ollama_base = "http://localhost:11434"
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(
                f"{ollama_base}/api/pull",
                json={"name": model, "stream": False},
            )
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status", "unknown")
            return f"Model '{model}' pull status: {status}"
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Ollama pull request failed: {exc}") from exc


async def _tool_query_rag(args: dict[str, Any]) -> str:
    """Query the RAG pipeline."""
    question = args.get("question", "")
    collection = args.get("collection", "default")
    top_k = int(args.get("top_k", 3))

    try:
        config = RAGConfig()
        storage = ChromaStorage(config)
        raw = storage.query(collection, question, top_k=top_k)
        documents = (raw.get("documents") or [[]])[0]
        if not documents:
            return "No relevant context found."
        return "\n\n".join(f"[{i + 1}] {doc}" for i, doc in enumerate(documents))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"RAG query failed: {exc}") from exc


async def _tool_list_models(_args: dict[str, Any]) -> list[dict[str, Any]]:
    """List installed models (tool form)."""
    return await _fetch_models()


_TOOL_HANDLERS = {
    "chat": _tool_chat,
    "pull_model": _tool_pull_model,
    "query_rag": _tool_query_rag,
    "list_models": _tool_list_models,
}


# ---------------------------------------------------------------------------
# JSON-RPC dispatch helpers
# ---------------------------------------------------------------------------


def _ok(id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": _JSONRPC, "id": id, "result": result}


def _err(id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": _JSONRPC, "id": id, "error": error}


# JSON-RPC 2.0 standard error codes
_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603


# ---------------------------------------------------------------------------
# MCP method handlers
# ---------------------------------------------------------------------------


async def _handle_initialize(id: Any, params: dict | None) -> dict[str, Any]:
    return _ok(
        id,
        {
            "protocolVersion": _MCP_VERSION,
            "capabilities": _CAPABILITIES,
            "serverInfo": _SERVER_INFO,
        },
    )


async def _handle_resources_list(id: Any, _params: dict | None) -> dict[str, Any]:
    return _ok(id, {"resources": _RESOURCES})


async def _handle_resources_read(id: Any, params: dict | None) -> dict[str, Any]:
    if not params or "uri" not in params:
        return _err(id, _INVALID_PARAMS, "Missing 'uri' parameter")

    uri = params["uri"]

    if uri == "bmt://models":
        data = await _fetch_models()
        return _ok(
            id,
            {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": str(data),
                    }
                ]
            },
        )

    if uri == "bmt://status":
        data = await _fetch_status()
        return _ok(
            id,
            {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": str(data),
                    }
                ]
            },
        )

    if uri == "bmt://providers":
        data = await _fetch_providers()
        return _ok(
            id,
            {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": str(data),
                    }
                ]
            },
        )

    return _err(id, _INVALID_PARAMS, f"Unknown resource URI: {uri!r}")


async def _handle_tools_list(id: Any, _params: dict | None) -> dict[str, Any]:
    return _ok(id, {"tools": _TOOLS})


async def _handle_tools_call(id: Any, params: dict | None) -> dict[str, Any]:
    if not params or "name" not in params:
        return _err(id, _INVALID_PARAMS, "Missing 'name' parameter")

    tool_name = params["name"]
    tool_args: dict[str, Any] = params.get("arguments") or {}

    handler = _TOOL_HANDLERS.get(tool_name)
    if handler is None:
        return _err(id, _METHOD_NOT_FOUND, f"Unknown tool: {tool_name!r}")

    try:
        result = await handler(tool_args)
    except (ValueError, TypeError) as exc:
        return _err(id, _INVALID_PARAMS, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("MCP tool %r failed", tool_name)
        return _err(id, _INTERNAL_ERROR, str(exc))

    # Normalise result to MCP content array
    if isinstance(result, str):
        content = [{"type": "text", "text": result}]
    elif isinstance(result, list):
        content = [{"type": "text", "text": str(item)} for item in result]
    else:
        content = [{"type": "text", "text": str(result)}]

    return _ok(id, {"content": content, "isError": False})


async def _handle_ping(id: Any, _params: dict | None) -> dict[str, Any]:
    return _ok(id, {})


_DISPATCH: dict[str, Any] = {
    "initialize": _handle_initialize,
    "resources/list": _handle_resources_list,
    "resources/read": _handle_resources_read,
    "tools/list": _handle_tools_list,
    "tools/call": _handle_tools_call,
    "ping": _handle_ping,
}


# ---------------------------------------------------------------------------
# FastAPI router (mounted at /mcp/ by the controller)
# ---------------------------------------------------------------------------

mcp_router = APIRouter(tags=["mcp"])


@mcp_router.post("/")
async def mcp_endpoint(request: Request) -> JSONResponse:
    """Receive a JSON-RPC 2.0 request and dispatch to the appropriate handler."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            _err(None, _PARSE_ERROR, "Parse error: body is not valid JSON"),
            status_code=200,  # JSON-RPC always returns 200
        )

    rpc_id = body.get("id")
    method = body.get("method")
    params = body.get("params")

    if not isinstance(method, str):
        return JSONResponse(
            _err(rpc_id, _INVALID_REQUEST, "Invalid Request: 'method' must be a string"),
            status_code=200,
        )

    handler = _DISPATCH.get(method)
    if handler is None:
        return JSONResponse(
            _err(rpc_id, _METHOD_NOT_FOUND, f"Method not found: {method!r}"),
            status_code=200,
        )

    try:
        result = await handler(rpc_id, params)
    except Exception as exc:  # noqa: BLE001
        logger.exception("MCP dispatch error for method %r", method)
        return JSONResponse(
            _err(rpc_id, _INTERNAL_ERROR, f"Internal error: {exc}"),
            status_code=200,
        )

    return JSONResponse(result, status_code=200)


@mcp_router.get("/info")
async def mcp_info() -> dict[str, Any]:
    """Return MCP server metadata (non-JSON-RPC convenience endpoint)."""
    return {
        "mcp_version": _MCP_VERSION,
        "server": _SERVER_INFO,
        "resources": [r["uri"] for r in _RESOURCES],
        "tools": [t["name"] for t in _TOOLS],
    }


# ---------------------------------------------------------------------------
# Standalone FastAPI application (for ``bmt-ai-os mcp serve``)
# ---------------------------------------------------------------------------


def create_mcp_app() -> FastAPI:
    """Create a standalone MCP FastAPI application.

    Useful for running the MCP server independently of the main controller
    (e.g. ``bmt-ai-os mcp serve``).
    """
    app = FastAPI(
        title="BMT AI OS MCP Server",
        description="Model Context Protocol server for BMT AI OS — Claude Code integration.",
        version="2026.4.11",
    )
    app.include_router(mcp_router, prefix="/mcp")
    return app


# ---------------------------------------------------------------------------
# CLI entry point: bmt-ai-os mcp serve
# ---------------------------------------------------------------------------


def _cli_serve() -> None:
    """Start the standalone MCP server (called by ``bmt-ai-os mcp serve``)."""
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="BMT AI OS MCP server (standalone)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765)")
    parser.add_argument("--log-level", default="info", help="Log level (default: info)")
    args = parser.parse_args()

    mcp_app = create_mcp_app()
    uvicorn.run(mcp_app, host=args.host, port=args.port, log_level=args.log_level)


if __name__ == "__main__":
    _cli_serve()
