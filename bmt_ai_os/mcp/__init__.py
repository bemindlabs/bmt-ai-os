"""BMT AI OS — Model Context Protocol (MCP) server package.

Exposes BMT AI OS resources and tools to MCP clients such as Claude Code.

Resources
---------
bmt://models      — list installed Ollama models
bmt://status      — system status snapshot
bmt://providers   — registered LLM providers

Tools
-----
chat              — send a message to the active provider
pull_model        — pull a model from the Ollama registry
query_rag         — query the RAG pipeline
list_models       — list models (tool form, no URI needed)
"""

from .server import create_mcp_app, mcp_router

__all__ = ["create_mcp_app", "mcp_router"]
