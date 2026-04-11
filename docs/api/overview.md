# REST API Overview

The BMT AI OS controller API runs on port `8080` and provides an OpenAI-compatible interface plus BMT-specific extensions for RAG and system management.

## Design Principles

- **OpenAI-compatible** — drop-in replacement for IDE plugins (Cursor, Copilot, Cody)
- **SSE streaming** — all generation endpoints support Server-Sent Events
- **Local-first** — routes to the local Ollama instance by default; falls back to cloud providers if configured
- **Stateless** — no session management; each request is independent

## Endpoint Summary

### OpenAI-Compatible (`/v1/`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/chat/completions` | Chat completions with optional SSE streaming |
| `POST` | `/v1/completions` | Legacy text completions (code completion) |
| `POST` | `/v1/embeddings` | Generate embeddings |
| `GET` | `/v1/models` | List available models |

### RAG API (`/api/v1/`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/query` | RAG-augmented query |
| `POST` | `/api/v1/query/stream` | Streaming RAG query (SSE) |
| `POST` | `/api/v1/ingest` | Ingest documents into a collection |
| `GET` | `/api/v1/collections` | List ChromaDB collections |

### Health & Status

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/healthz` | Liveness check |
| `GET` | `/api/v1/status` | System status (version, uptime, services) |
| `GET` | `/api/v1/metrics` | Request and health-check metrics |
| `GET` | `/metrics` | Prometheus-format metrics |

## Error Handling

All endpoints return standard HTTP status codes:

| Code | Meaning |
|------|---------|
| `200` | Success |
| `422` | Validation error (bad request body) |
| `500` | Internal server error |
| `502` | Provider error (upstream LLM failed) |
| `503` | No provider available (provider registry empty) |

Error responses follow the format:

```json
{
  "detail": "Error description"
}
```

## Streaming

Chat and RAG query endpoints support SSE streaming. Set `stream: true` in the request body:

```bash
curl -N http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5-coder:7b",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": true
  }'
```

Streaming responses use the `text/event-stream` media type and end with `data: [DONE]`.
