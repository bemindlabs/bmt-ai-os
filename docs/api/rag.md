# RAG API

The RAG (Retrieval-Augmented Generation) API lets you query documents stored in ChromaDB and get LLM-augmented answers. All RAG endpoints are under the `/api/v1/` prefix.

## Query

### `POST /api/v1/query`

Run a RAG query. Retrieves relevant chunks from ChromaDB, builds a context-augmented prompt, and returns an LLM-generated answer with source citations.

**Request body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `question` | string | required | The question to answer |
| `collection` | string | `"default"` | ChromaDB collection to search |
| `top_k` | integer | `5` | Number of chunks to retrieve (1–50) |
| `code_mode` | boolean | `false` | Optimise prompt for code-related questions |

**Example:**

```bash
curl http://localhost:8080/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "How do I configure the Ollama provider?",
    "collection": "default",
    "top_k": 5
  }'
```

**Response:**

```json
{
  "answer": "To configure the Ollama provider, edit /etc/bmt_ai_os/providers.yml...",
  "sources": [
    {
      "id": "doc-001",
      "content": "The Ollama provider is configured via providers.yml...",
      "metadata": {"file": "provider-layer.md", "chunk": 3}
    }
  ],
  "latency_ms": 342.5,
  "model": "qwen2.5-coder:7b"
}
```

## Streaming Query

### `POST /api/v1/query/stream`

Same as `/api/v1/query` but streams the answer token-by-token as Server-Sent Events.

**Example:**

```bash
curl -N http://localhost:8080/api/v1/query/stream \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is the provider fallback chain?",
    "collection": "default"
  }'
```

**SSE event format:**

Token events:
```
data: {"token": "The"}
data: {"token": " fallback"}
...
```

Final event (includes full response with sources):
```
data: {"done": true, "answer": "...", "sources": [...], "latency_ms": 250.0, "model": "qwen2.5-coder:7b"}
```

## Ingest Documents

### `POST /api/v1/ingest`

Ingest documents from a local file system path into a ChromaDB collection.

**Request body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `path` | string | required | Absolute path to file or directory |
| `collection` | string | `"default"` | Target ChromaDB collection |
| `recursive` | boolean | `true` | Recursively process subdirectories |

**Example:**

```bash
curl http://localhost:8080/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "path": "/home/user/my-project",
    "collection": "my-project",
    "recursive": true
  }'
```

**Response:**

```json
{
  "status": "accepted",
  "path": "/home/user/my-project",
  "collection": "my-project",
  "recursive": true
}
```

## List Collections

### `GET /api/v1/collections`

List all ChromaDB collections with their document counts.

**Example:**

```bash
curl http://localhost:8080/api/v1/collections
```

**Response:**

```json
[
  {
    "name": "default",
    "count": 1247
  },
  {
    "name": "my-project",
    "count": 83
  }
]
```

## CLI Shortcuts

The `bmt_ai_os` CLI wraps these endpoints:

```bash
# Query with RAG
bmt_ai_os query "How does the provider fallback work?"

# Ingest a codebase
bmt_ai_os ingest /path/to/project

# Query with code mode
bmt_ai_os query "What does main.py do?" --code-mode
```
