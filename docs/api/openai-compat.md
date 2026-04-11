# OpenAI-Compatible API

The controller exposes a drop-in OpenAI-compatible REST API. Any tool that targets the OpenAI API — Cursor, GitHub Copilot, Sourcegraph Cody, Aider, Continue, and others — can point to `http://localhost:8080` without modification.

## Chat Completions

### `POST /v1/chat/completions`

Generate a response for a conversation. Supports both synchronous and SSE streaming responses.

**Request body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `model` | string | `"default"` | Model name (e.g. `qwen2.5-coder:7b`). Use `"default"` to use the active provider's default model. |
| `messages` | array | required | Array of `{role, content}` objects. Roles: `system`, `user`, `assistant`. |
| `temperature` | float | `0.7` | Sampling temperature (0.0–2.0) |
| `max_tokens` | integer | `4096` | Maximum tokens to generate |
| `top_p` | float | `1.0` | Nucleus sampling probability |
| `stream` | boolean | `false` | Enable SSE streaming |
| `stop` | string or array | `null` | Stop sequences |
| `presence_penalty` | float | `0.0` | Penalize repeated topics |
| `frequency_penalty` | float | `0.0` | Penalize repeated tokens |

**Example — synchronous:**

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5-coder:7b",
    "messages": [
      {"role": "system", "content": "You are a helpful coding assistant."},
      {"role": "user", "content": "Write a Python function to parse JSON."}
    ],
    "temperature": 0.2
  }'
```

**Example — streaming:**

```bash
curl -N http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5-coder:7b",
    "messages": [{"role": "user", "content": "Count to 5"}],
    "stream": true
  }'
```

**Response (non-streaming):**

```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "created": 1712800000,
  "model": "qwen2.5-coder:7b",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Here is the function..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 25,
    "completion_tokens": 80,
    "total_tokens": 105
  }
}
```

## Legacy Completions

### `POST /v1/completions`

Text completion for code fill-in. Used by GitHub Copilot and similar tools for inline code completion.

**Request body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `model` | string | `"default"` | Model name |
| `prompt` | string or array | `""` | Input text or array of texts |
| `max_tokens` | integer | `256` | Maximum tokens to generate |
| `temperature` | float | `0.7` | Sampling temperature |
| `stream` | boolean | `false` | Enable SSE streaming |

**Example:**

```bash
curl http://localhost:8080/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5-coder:7b",
    "prompt": "def fibonacci(n):",
    "max_tokens": 128,
    "temperature": 0.1
  }'
```

## Embeddings

### `POST /v1/embeddings`

Generate vector embeddings. Used by Sourcegraph Cody and other RAG-enabled IDE plugins.

**Request body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `input` | string or array | required | Text(s) to embed |
| `model` | string | `"default"` | Embedding model name |
| `encoding_format` | string | `"float"` | Output format (`float` or `base64`) |

**Example:**

```bash
curl http://localhost:8080/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{
    "input": "How do I configure containerd?",
    "model": "qwen3-embedding-8b"
  }'
```

**Response:**

```json
{
  "object": "list",
  "data": [
    {
      "object": "embedding",
      "embedding": [0.0023, -0.009, ...],
      "index": 0
    }
  ],
  "model": "qwen3-embedding-8b",
  "usage": {
    "prompt_tokens": 8,
    "total_tokens": 8
  }
}
```

## List Models

### `GET /v1/models`

List all models available from the active provider.

**Example:**

```bash
curl http://localhost:8080/v1/models
```

**Response:**

```json
{
  "object": "list",
  "data": [
    {
      "id": "qwen2.5-coder:7b",
      "object": "model",
      "created": 1712800000,
      "owned_by": "bmt_ai_os"
    }
  ]
}
```

## Configuring IDE Plugins

Point the API base URL to `http://<device-ip>:8080` in your IDE. See the [IDE Integration](../ide-integration/index.md) docs for per-tool instructions.
