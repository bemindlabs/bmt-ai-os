# Provider Abstraction Layer

## Overview

The provider layer abstracts LLM backends behind a unified interface. All coding tools, RAG pipeline, and APIs use this layer — never call Ollama directly.

## Interface

```python
class LLMProvider:
    def chat(messages, model, **kwargs) -> Response
    def embed(text, model) -> list[float]
    def list_models() -> list[Model]
```

## Supported Providers

### Local (Primary)

| Provider | Port | Best For |
|----------|------|----------|
| Ollama | 11434 | General inference, model management |
| vLLM | — | High-throughput batch workloads |
| llama.cpp | — | Minimal memory, resource-constrained devices |

### Cloud (Optional Fallback)

| Provider | API | Notes |
|----------|-----|-------|
| OpenAI | Chat Completions + Embeddings | GPT-4o, GPT-4o-mini |
| Anthropic | Messages API | Claude Sonnet, Opus |
| Google | Gemini API | Gemini 2.5 Pro/Flash |
| Mistral | OpenAI-compatible | Codestral, Mistral Large |
| Groq | OpenAI-compatible | Low-latency cloud option |

## Fallback Chain

```yaml
# /etc/bmt-ai-os/providers.yml
providers:
  chain:
    - ollama          # Try first (local)
    - llama-cpp       # Try second (lighter)
    - openai          # Cloud fallback
    - anthropic       # Cloud fallback
  
  timeouts:
    local: 30s
    cloud: 15s
  
  circuit_breaker:
    cooldown: 60s     # Skip unhealthy provider for 60s
```

## Configuration

```bash
# Switch active provider
bmt-ai-os provider set ollama

# List providers and status
bmt-ai-os provider list

# Test a provider
bmt-ai-os provider test openai
```

Cloud API keys are stored in `/etc/bmt-ai-os/secrets/` with `0600` permissions.
