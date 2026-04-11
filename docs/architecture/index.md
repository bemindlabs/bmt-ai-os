# Architecture

BMT AI OS is a layered system. Each layer has a single responsibility and communicates through well-defined interfaces.

## Layers at a Glance

```
┌───────────────────────────────────────────────────┐
│                   BMT AI OS                       │
├───────────────────────────────────────────────────┤
│  Dashboard (:9090)  │  TUI (bmt_ai_os tui)        │
│  Next.js+shadcn/ui  │  Python Textual              │
├───────────────────────────────────────────────────┤
│  Coding CLIs        │  IDE Plugins  │  Code Agents │
│  Claude Code, Aider │  Cursor       │  SWE-agent   │
│  Continue, Tabby    │  Copilot,Cody │  Codex CLI   │
├───────────────────────────────────────────────────┤
│  Training Stack     │  RAG Pipeline │  REST API    │
│  PyTorch + LoRA     │  Ingest→Embed │  :8080       │
│  Jupyter (:8888)    │  →ChromaDB    │  OpenAI-     │
│  TensorBoard (:6006)│  →Query→LLM   │  compatible  │
├───────────────────────────────────────────────────┤
│         Provider Abstraction Layer                │
│  chat() │ embed() │ list_models() │ fallback()     │
├───────────────────┬───────────────────────────────┤
│   Local (primary) │     Cloud (fallback)          │
│   Ollama (:11434) │     OpenAI                    │
│   vLLM            │     Anthropic (Claude)        │
│   llama.cpp       │     Google (Gemini)           │
│                   │     Mistral / Groq             │
├───────────────────┴───────────────────────────────┤
│  Container Runtime (containerd) + Docker CLI      │
│  NPU/GPU passthrough (CUDA, RKNN, HailoRT)        │
├───────────────────────────────────────────────────┤
│  Linux Kernel (Buildroot, ARM64/aarch64, OpenRC)  │
└───────────────────────────────────────────────────┘
```

## Documentation

- [System Overview](system-overview.md) — detailed component breakdown and data flows
- [Provider Layer](provider-layer.md) — LLM provider abstraction, fallback chain, and circuit breaker
- [Boot Sequence](boot-sequence.md) — service start order and health checks
- [Filesystem Layout](filesystem-layout.md) — directory structure on the running OS
