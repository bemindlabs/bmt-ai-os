# Provider Management

BMT AI OS supports dynamic provider configuration with guided setup, health monitoring, and fallback chain management.

## Provider CRUD

Providers can be added, edited, and removed at runtime through the dashboard or API:

- **POST** `/api/v1/providers` — Register a new provider
- **PUT** `/api/v1/providers/{id}` — Update provider config
- **DELETE** `/api/v1/providers/{id}` — Remove a provider

Changes persist to `providers.yml` without requiring a restart.

## Setup Wizard

A guided multi-step wizard walks through provider setup:

1. Select provider type (Ollama, OpenAI, Anthropic, Gemini, etc.)
2. Choose auth method (API key or OAuth)
3. Enter credentials
4. Test connection
5. Select default model

## Fallback Chain

The fallback chain determines provider priority for inference requests. Configure via drag-and-drop in the dashboard:

```
Provider 1 (primary) → Provider 2 (fallback) → Provider 3 (last resort)
```

When a provider fails or is unavailable, requests automatically route to the next provider in the chain.

## Health Dashboard

Each provider card shows:

- Connection status (online/offline/degraded)
- Credential freshness and API key last-used timestamp
- Error count with cooldown timer
- Response latency trend (last 10 checks)
- Auto-refresh every 30 seconds

## Multi-Credential Profiles

Support multiple API keys per provider for load balancing:

- Round-robin or failover selection
- Per-profile usage statistics
- Automatic cooldown on rate-limit errors

## Auto-Discovery

On startup, BMT AI OS scans common local ports to auto-register discovered providers:

| Port | Provider |
|------|----------|
| 11434 | Ollama |
| 8001 | vLLM |
| 8002 | llama.cpp |

Discovered providers show a "Discovered" badge in the dashboard.

## Model Catalog

A unified model catalog shows all available models across providers:

| Field | Description |
|-------|-------------|
| Model name | Display name and ID |
| Provider | Which provider serves this model |
| Context window | Maximum context size |
| Max tokens | Maximum output tokens |
| Cost | Per 1M tokens (input/output) |
| Quantization | Quantization level (Q4, Q8, FP16) |

The catalog is sortable and filterable. Model probing tests connectivity with a simple prompt.
