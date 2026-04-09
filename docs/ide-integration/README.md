# IDE Integration Guide

BMT AI OS exposes an **OpenAI-compatible API** so that AI-powered IDEs and
editor plugins can use the on-device AI stack as their backend. This means
your code completions, chat, and embeddings all run locally (or on your LAN)
with zero cloud dependency.

## Supported IDEs

| IDE / Plugin | Feature | Guide |
|-------------|---------|-------|
| **Cursor** | Chat, code completion, inline edit | [cursor-setup.md](cursor-setup.md) |
| **GitHub Copilot** | Code completion, chat | [copilot-setup.md](copilot-setup.md) |
| **Sourcegraph Cody** | Chat, embeddings, code search | [copilot-setup.md](copilot-setup.md) |
| **Continue.dev** | Chat, code completion | Same config as Cursor |

## API Endpoints

All endpoints follow the OpenAI REST API specification:

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/chat/completions` | Chat completions (streaming SSE supported) |
| POST | `/v1/completions` | Legacy text/code completions |
| POST | `/v1/embeddings` | Text embeddings |
| GET | `/v1/models` | List available models |

Default port: **8080** (configurable via `BMT_API_PORT` or `controller.yml`).

## Quick Start

1. Start the BMT AI OS stack:

```bash
docker compose -f bmt-ai-os/ai-stack/docker-compose.yml up -d
python bmt-ai-os/controller/main.py
```

2. Verify the API is running:

```bash
curl http://localhost:8080/v1/models
```

3. Point your IDE to `http://<device-ip>:8080/v1` as the API base URL.

## Authentication

Authentication is **optional** and disabled by default for air-gapped
deployments. To enable it, set the `BMT_API_KEY` environment variable:

```bash
export BMT_API_KEY="your-secret-key"
```

IDEs will then need to provide this key as a Bearer token in the
`Authorization` header.

## Streaming

All chat and completion endpoints support Server-Sent Events (SSE) streaming
when `"stream": true` is set in the request body. This provides real-time
token-by-token output in the IDE.

## Default Models

BMT AI OS ships with Qwen-family models optimised for coding:

- **qwen2.5-coder:7b** -- primary code completion and chat model
- **nomic-embed-text** -- embeddings for code search and RAG
