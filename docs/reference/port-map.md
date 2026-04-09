# Port Map

## Service Ports

| Port | Service | Protocol | Access |
|------|---------|----------|--------|
| 6006 | TensorBoard | HTTP | Training visualization |
| 8000 | ChromaDB | HTTP | Vector database API |
| 8080 | OpenAI-compatible API | HTTP/SSE | IDE plugins (Cursor, Copilot, Cody) |
| 8888 | Jupyter Lab | HTTP/WS | Interactive training notebooks |
| 9090 | Dashboard | HTTP/WS | Web UI (Next.js + shadcn/ui) |
| 11434 | Ollama | HTTP | LLM inference API |

## Network Architecture

```
External (LAN)
  │
  ├── :9090  Dashboard (web browser)
  ├── :8080  OpenAI API (IDE plugins)
  ├── :8888  Jupyter Lab (browser)
  ├── :6006  TensorBoard (browser)
  │
  └── Host Network
        │
        ├── :11434  Ollama ──┐
        ├── :8000   ChromaDB ┤ Docker bridge network
        └── Controller ──────┘ (inter-container DNS)
```

## Firewall Recommendations

For production deployments, only expose ports that need external access:

| Port | Expose to LAN? | Notes |
|------|----------------|-------|
| 9090 | Yes | Dashboard — primary management interface |
| 8080 | Yes | IDE plugins need this from developer machines |
| 8888 | Optional | Only if using Jupyter remotely |
| 6006 | Optional | Only during active training |
| 11434 | No | Access via controller/API, not directly |
| 8000 | No | Access via controller/API, not directly |
