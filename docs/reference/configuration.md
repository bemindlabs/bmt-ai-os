# Configuration Reference

BMT AI OS is configured through YAML files and environment variable overrides. This page documents all configuration options.

## Controller Configuration

**File:** `/etc/bmt_ai_os/controller.yml`
**Dev fallback:** `controller.yml` in the current directory

```yaml
# controller.yml — example
compose_file: /opt/bmt_ai_os/ai-stack/docker-compose.yml
api_port: 8080
api_host: "0.0.0.0"
log_level: INFO
log_file: /var/log/bmt-controller.log
health_interval: 30
health_timeout: 5
health_history_size: 10
max_restarts: 3
circuit_breaker_threshold: 5
circuit_breaker_reset: 300

services:
  - name: ollama
    container_name: bmt-ollama
    health_url: http://localhost:11434/api/tags
    port: 11434
  - name: chromadb
    container_name: bmt-chromadb
    health_url: http://localhost:8000/api/v1/heartbeat
    port: 8000
```

### Controller Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `compose_file` | string | `/opt/bmt_ai_os/ai-stack/docker-compose.yml` | Path to the Docker Compose file for the AI stack |
| `api_port` | integer | `8080` | Port the controller API listens on |
| `api_host` | string | `"0.0.0.0"` | Host address to bind the API server |
| `log_level` | string | `"INFO"` | Log verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `log_file` | string | `/var/log/bmt-controller.log` | Path to the log file |
| `health_interval` | integer | `30` | Seconds between health checks |
| `health_timeout` | integer | `5` | Seconds to wait for a health check response |
| `health_history_size` | integer | `10` | Number of health check results to retain per service |
| `max_restarts` | integer | `3` | Maximum service restart attempts before giving up |
| `circuit_breaker_threshold` | integer | `5` | Number of failures before opening the circuit breaker |
| `circuit_breaker_reset` | integer | `300` | Seconds before the circuit breaker resets (allows retry) |

### Environment Variable Overrides

All controller settings can be overridden via environment variables prefixed with `BMT_`:

| Variable | Overrides |
|----------|-----------|
| `BMT_COMPOSE_FILE` | `compose_file` |
| `BMT_API_PORT` | `api_port` |
| `BMT_API_HOST` | `api_host` |
| `BMT_LOG_LEVEL` | `log_level` |
| `BMT_LOG_FILE` | `log_file` |
| `BMT_HEALTH_INTERVAL` | `health_interval` |
| `BMT_HEALTH_TIMEOUT` | `health_timeout` |
| `BMT_MAX_RESTARTS` | `max_restarts` |
| `BMT_CIRCUIT_BREAKER_THRESHOLD` | `circuit_breaker_threshold` |
| `BMT_CIRCUIT_BREAKER_RESET` | `circuit_breaker_reset` |

## Provider Configuration

**File:** `/etc/bmt_ai_os/providers.yml`
**Packaged default:** `bmt_ai_os/providers/providers.yml`

```yaml
# providers.yml — example
providers:
  chain:
    - ollama          # Try first (local)
    - llama-cpp       # Try second (lighter local)
    - openai          # Cloud fallback
    - anthropic       # Cloud fallback

  timeouts:
    local: 30         # seconds
    cloud: 15         # seconds

  circuit_breaker:
    cooldown: 60      # seconds to skip an unhealthy provider

  ollama:
    base_url: http://localhost:11434
    default_model: qwen2.5-coder:7b

  openai:
    api_key: ${OPENAI_API_KEY}
    default_model: gpt-4o-mini

  anthropic:
    api_key: ${ANTHROPIC_API_KEY}
    default_model: claude-3-5-haiku-20241022

  gemini:
    api_key: ${GEMINI_API_KEY}
    default_model: gemini-2.0-flash

  mistral:
    api_key: ${MISTRAL_API_KEY}
    default_model: codestral-latest

  groq:
    api_key: ${GROQ_API_KEY}
    default_model: llama-3.3-70b-versatile
```

!!! note "API key security"
    API keys can be referenced via `${ENV_VAR}` syntax. Store secrets in `/etc/bmt_ai_os/secrets/` with `0600` permissions, or use environment variables.

## RAG Configuration

```yaml
# rag configuration (embedded in controller config or standalone)
rag:
  chroma_host: localhost
  chroma_port: 8000
  default_collection: default
  chunk_size: 512
  chunk_overlap: 64
  embedding_model: qwen3-embedding-8b
  top_k: 5
```

## Filesystem Locations

| Path | Contents |
|------|----------|
| `/etc/bmt_ai_os/controller.yml` | Controller configuration |
| `/etc/bmt_ai_os/providers.yml` | Provider configuration |
| `/etc/bmt_ai_os/secrets/` | API keys (0600 permissions) |
| `/var/log/bmt-controller.log` | Controller log file |
| `/opt/bmt_ai_os/` | Application files |
| `/var/lib/bmt_ai_os/` | Persistent data |

## Docker / Dev Environment

When running with Docker Compose, configure via environment variables in `.env`:

```bash
# .env
BMT_COMPOSE_FILE=/path/to/docker-compose.yml
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

Or pass directly:

```bash
BMT_COMPOSE_FILE=$(pwd)/bmt_ai_os/ai-stack/docker-compose.yml \
BMT_LOG_LEVEL=DEBUG \
PYTHONPATH=$(pwd) python3 -m bmt_ai_os.controller.main
```
