# System Architecture

## Layer Diagram

```
┌───────────────────────────────────────────────────┐
│                   BMT AI OS                       │
├───────────────────────────────────────────────────┤
│  Dashboard (:9090)  │  TUI (bmt_ai_os tui)       │
│  Next.js+shadcn/ui  │  Python Textual             │
├───────────────────────────────────────────────────┤
│  Coding CLIs        │  IDE Plugins  │  Code Agents│
│  Claude Code, Aider │  Cursor       │  SWE-agent  │
│  Continue, Tabby    │  Copilot,Cody │  Codex CLI  │
├───────────────────────────────────────────────────┤
│  Training Stack     │  RAG Pipeline │  REST API   │
│  PyTorch + LoRA     │  Ingest→Embed │  :8080      │
│  Jupyter (:8888)    │  →ChromaDB    │  OpenAI-    │
│  TensorBoard (:6006)│  →Query→LLM   │  compatible │
├───────────────────────────────────────────────────┤
│         Provider Abstraction Layer                │
│  chat() │ embed() │ list_models() │ fallback()    │
├───────────────────┬───────────────────────────────┤
│   Local (primary) │     Cloud (fallback)          │
│   Ollama (:11434) │     OpenAI                    │
│   vLLM            │     Anthropic (Claude)        │
│   llama.cpp       │     Google (Gemini)           │
│                   │     Mistral / Groq            │
├───────────────────┴───────────────────────────────┤
│  Container Runtime (containerd) + Docker CLI      │
│  NPU/GPU passthrough (CUDA, RKNN, HailoRT)       │
├───────────────────────────────────────────────────┤
│  Linux Kernel (Buildroot, ARM64/aarch64, OpenRC)  │
└───────────────────────────────────────────────────┘
```

## Component Responsibilities

### Kernel Layer
- Buildroot-based minimal Linux for ARM64
- OpenRC init system manages service boot ordering
- Kernel features: cgroups v2, namespaces, overlayfs, bridge networking

### Container Layer
- containerd manages all AI service containers
- Docker CLI for user interaction
- NPU/GPU device passthrough into containers (CUDA, RKNN, HailoRT)
- iptables + bridge-utils for container networking

### Provider Layer
- Unified interface: `chat()`, `embed()`, `list_models()`
- Local-first: Ollama → vLLM → llama.cpp
- Cloud fallback: OpenAI → Anthropic → Gemini → Mistral/Groq
- Circuit breaker with configurable cooldown per provider

### AI Stack
- **Ollama** (:11434) — LLM inference server
- **ChromaDB** (:8000) — Vector database for RAG
- **Controller** — Python orchestrator managing container lifecycle

### Application Layer
- **Dashboard** (:9090) — Next.js + shadcn/ui web interface
- **TUI** — Python Textual terminal interface
- **Coding CLIs** — Pre-installed and auto-configured
- **REST API** (:8080) — OpenAI-compatible endpoint for IDE plugins
- **Training** — PyTorch + LoRA/QLoRA with Jupyter (:8888) and TensorBoard (:6006)

## Data Flow

### Inference Request
```
User/CLI → Provider Layer → Ollama (or fallback) → Response
```

### RAG Query
```
User → Query → ChromaDB (retrieve chunks) → Prompt + Context → LLM → Response + Sources
```

### Training Pipeline
```
Documents → Data Prep → LoRA Training (PyTorch) → Export (GGUF) → Register (Ollama) → Serve
```
