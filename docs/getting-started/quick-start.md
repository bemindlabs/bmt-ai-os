# Quick Start

Get up and running with BMT AI OS in minutes.

## 1. Verify Services

```bash
# Check all services are running
bmt-ai-os status

# Or manually check endpoints
curl http://localhost:11434/api/tags        # Ollama
curl http://localhost:8000/api/v1/heartbeat  # ChromaDB
```

## 2. Pull a Model

```bash
# Auto-detect hardware and install recommended preset
bmt-ai-os models install auto

# Or manually choose a preset
bmt-ai-os models install lite       # Qwen3.5-9B Q4 (~6GB)
bmt-ai-os models install standard   # Qwen2.5-Coder-7B Q4 + embedding (~8GB)
bmt-ai-os models install full       # Qwen3.5-27B Q4 + embedding (~18GB)

# Or pull any Ollama model
ollama pull qwen2.5-coder:7b
```

## 3. Chat with Your Model

```bash
# Direct Ollama chat
ollama run qwen2.5-coder:7b

# Or use the RAG-augmented query
bmt-ai-os query "How do I configure containerd on ARM64?"
```

## 4. Index a Codebase

```bash
# Ingest documents for RAG
bmt-ai-os ingest /path/to/your/project

# Query with context
bmt-ai-os query "What does the main function do?"
```

## 5. Start Coding with AI

```bash
# Aider (auto-configured to local model)
aider

# Claude Code (via Ollama Anthropic-compatible API)
claude

# Open the dashboard
open http://localhost:9090
```

## 6. Open the Dashboard

Navigate to `http://<device-ip>:9090` to see:
- System health and metrics
- Model management
- RAG console
- Provider configuration
- Live logs

## What's Next

- [IDE Plugin Setup](../coding-tools/ide-plugins.md) — connect Cursor, Copilot, or Cody
- [LoRA Training](../training/lora-guide.md) — fine-tune a model on your data
- [Provider Configuration](../architecture/provider-layer.md) — add cloud fallback
