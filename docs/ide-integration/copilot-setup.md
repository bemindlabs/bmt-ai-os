# Copilot and Cody Setup Guide

Use BMT AI OS as the backend for **GitHub Copilot** (via compatible
proxies) and **Sourcegraph Cody**.

## GitHub Copilot

GitHub Copilot does not natively support custom API endpoints. However,
you can route Copilot traffic through BMT AI OS using one of these
approaches.

### Option A: Copilot Language Server Proxy

Tools like [copilot-gpt4-service](https://github.com/aaamoon/copilot-gpt4-service)
or similar proxies can redirect Copilot requests to any OpenAI-compatible
endpoint.

1. Configure the proxy to point at BMT AI OS:

```
OPENAI_API_BASE=http://<device-ip>:8080/v1
```

2. Start the proxy and configure your editor to use it.

### Option B: VS Code + Continue.dev (Recommended)

For a simpler setup, use [Continue.dev](https://continue.dev) which
provides Copilot-like inline completions with native OpenAI-compatible
endpoint support. See the [Cursor setup guide](cursor-setup.md) for
Continue.dev configuration.

### Endpoint Used

Copilot-style code completions use:

```
POST /v1/completions
```

Request body:

```json
{
  "model": "qwen2.5-coder:7b",
  "prompt": "def fibonacci(n):\n    ",
  "max_tokens": 256,
  "temperature": 0.2,
  "stream": true
}
```

---

## Sourcegraph Cody

Cody supports custom LLM endpoints for both chat and embeddings.

### 1. VS Code Extension Settings

Open VS Code settings and add:

```json
{
  "cody.autocomplete.advanced.provider": "unstable-openai",
  "cody.autocomplete.advanced.serverEndpoint": "http://<device-ip>:8080",
  "cody.autocomplete.advanced.model": "qwen2.5-coder:7b",
  "cody.autocomplete.advanced.accessToken": "your-bmt-api-key"
}
```

### 2. Chat Configuration

For Cody chat, configure the custom model in Cody Enterprise settings
or use the experimental custom provider support:

```json
{
  "cody.experimental.chatModel": "openai/qwen2.5-coder:7b",
  "cody.experimental.chatModelEndpoint": "http://<device-ip>:8080/v1"
}
```

### 3. Embeddings

Cody uses embeddings for code search and context retrieval. BMT AI OS
exposes the standard embeddings endpoint:

```
POST /v1/embeddings
```

Request body:

```json
{
  "input": ["function to sort an array"],
  "model": "nomic-embed-text"
}
```

Response follows the OpenAI format:

```json
{
  "object": "list",
  "data": [
    {
      "object": "embedding",
      "embedding": [0.1, 0.2, ...],
      "index": 0
    }
  ],
  "model": "nomic-embed-text",
  "usage": { "prompt_tokens": 5, "total_tokens": 5 }
}
```

### Endpoints Used by Cody

| Feature | Endpoint |
|---------|----------|
| Chat | `POST /v1/chat/completions` |
| Autocomplete | `POST /v1/completions` |
| Embeddings | `POST /v1/embeddings` |
| Model list | `GET /v1/models` |

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| "Connection refused" | Ensure controller is running: `curl http://localhost:8080/healthz` |
| "Invalid API key" | Check `BMT_API_KEY` matches what you entered in the IDE |
| CORS errors | The API allows all origins by default; check firewall rules |
| Slow embeddings | Embedding models are small; ensure the model is pre-loaded |
| Cody "no completions" | Verify the model name matches exactly: `curl http://localhost:8080/v1/models` |
