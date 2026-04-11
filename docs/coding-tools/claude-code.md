# Claude Code — BMT AI OS Integration

This guide explains how to connect **Claude Code** (Anthropic's AI coding tool) to your BMT AI OS
device using the built-in **Model Context Protocol (MCP)** server.

---

## What the MCP server provides

| Type | Name | Description |
|------|------|-------------|
| Resource | `bmt://models` | Installed Ollama models |
| Resource | `bmt://status` | Controller and service status |
| Resource | `bmt://providers` | Registered LLM providers |
| Tool | `chat` | Send a message to the active provider |
| Tool | `pull_model` | Pull a model from the Ollama registry |
| Tool | `query_rag` | Query the RAG pipeline |
| Tool | `list_models` | List installed models |

---

## Option A — Use the MCP endpoint embedded in the controller

When the controller is running, the MCP server is automatically mounted at:

```
POST http://<device-ip>:8080/mcp/
GET  http://<device-ip>:8080/mcp/info
```

No extra process is required.

### Claude Code configuration

Create or edit `~/.claude/claude_desktop_config.json` (on your dev machine):

```json
{
  "mcpServers": {
    "bmt-ai-os": {
      "url": "http://<device-ip>:8080/mcp/"
    }
  }
}
```

Replace `<device-ip>` with the IP address (or hostname) of your BMT AI OS device.

---

## Option B — Standalone MCP server

Start the MCP server independently from the controller (useful for development):

```bash
# Default: binds to 127.0.0.1:8765
bmt-ai-os mcp serve

# Custom host/port
bmt-ai-os mcp serve --host 0.0.0.0 --port 8765

# With debug logging
bmt-ai-os mcp serve --log-level debug
```

### Claude Code configuration (standalone)

```json
{
  "mcpServers": {
    "bmt-ai-os": {
      "url": "http://127.0.0.1:8765/mcp/"
    }
  }
}
```

---

## Verifying the connection

### Check the info endpoint

```bash
curl http://localhost:8080/mcp/info
```

Expected response:

```json
{
  "mcp_version": "2024-11-05",
  "server": {"name": "bmt-ai-os", "version": "2026.4.11"},
  "resources": ["bmt://models", "bmt://status", "bmt://providers"],
  "tools": ["chat", "pull_model", "query_rag", "list_models"]
}
```

### Send a JSON-RPC ping

```bash
curl -s -X POST http://localhost:8080/mcp/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"ping"}' | jq .
```

Expected:

```json
{"jsonrpc": "2.0", "id": 1, "result": {}}
```

---

## JSON-RPC 2.0 protocol reference

All requests use `POST /mcp/` with `Content-Type: application/json`.

### Initialize (handshake)

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"claude-code"}}}
```

### List resources

```json
{"jsonrpc":"2.0","id":2,"method":"resources/list"}
```

### Read a resource

```json
{"jsonrpc":"2.0","id":3,"method":"resources/read","params":{"uri":"bmt://models"}}
```

### List tools

```json
{"jsonrpc":"2.0","id":4,"method":"tools/list"}
```

### Call a tool — chat

```json
{
  "jsonrpc": "2.0",
  "id": 5,
  "method": "tools/call",
  "params": {
    "name": "chat",
    "arguments": {
      "message": "Explain how RKNN works on RK3588",
      "model": "qwen2.5-coder:7b",
      "temperature": 0.5
    }
  }
}
```

### Call a tool — pull_model

```json
{
  "jsonrpc": "2.0",
  "id": 6,
  "method": "tools/call",
  "params": {
    "name": "pull_model",
    "arguments": {"model": "qwen2.5-coder:1.5b"}
  }
}
```

### Call a tool — query_rag

```json
{
  "jsonrpc": "2.0",
  "id": 7,
  "method": "tools/call",
  "params": {
    "name": "query_rag",
    "arguments": {
      "question": "What are the supported NPU backends?",
      "collection": "default",
      "top_k": 3
    }
  }
}
```

---

## Supported Claude Code versions

Claude Code (claude.ai/code) supports MCP servers via the `mcpServers` configuration key.
The BMT AI OS MCP server implements **MCP protocol version 2024-11-05**.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Connection refused` | Check the controller is running: `bmt-ai-os status` |
| `Method not found` | Verify method name (case-sensitive: `tools/call`, not `tools/Call`) |
| Tool returns error | Run `bmt-ai-os mcp serve --log-level debug` for verbose output |
| Models list empty | Ensure Ollama is running: `docker compose ps` |
| RAG query fails | Start ChromaDB: `docker compose up -d chromadb` |

---

## Security note

The MCP endpoint does **not** require authentication by default when running locally.
If the controller is exposed on a network interface, protect it with:

- `BMT_API_KEY` environment variable (API key auth)
- TLS (`BMT_TLS_ENABLED=true`)
- Network-level firewall (allow only trusted hosts on port 8080)
