# BMT AI OS

**An open-source, AI-first operating system for ARM64**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/bemindlabs/bmt-ai-os/blob/main/LICENSE)
[![Version](https://img.shields.io/badge/version-2026.4.12-green.svg)](https://github.com/bemindlabs/bmt-ai-os/releases/tag/v2026.4.12)
[![Architecture](https://img.shields.io/badge/arch-ARM64-orange.svg)](https://github.com/bemindlabs/bmt-ai-os)

---

Containerized LLM inference, local RAG, AI coding tools, and on-device model training — all on a $100 ARM64 board. Fully offline after initial setup.

Powered by [Bemind Technology Co., Ltd.](https://bemind.tech)

## Key Features

- **Boot to AI** — LLM inference and RAG start as system services on boot
- **Multi-provider** — Ollama, vLLM, llama.cpp locally; OpenAI, Anthropic, Gemini as cloud fallback
- **AI Workspace** — browser-based IDE with Monaco editor, terminal, file manager, and AI coding assistant
- **Coding tools** — Claude Code, Aider, Continue, Tabby pre-installed and auto-configured
- **AI Coding Workflow** — diff preview, slash commands (/fix, /refactor, /explain), tool use, multi-file edits, git integration
- **On-device training** — LoRA/QLoRA fine-tuning with PyTorch on edge hardware
- **Knowledge Vaults** — per-persona Obsidian-compatible knowledge bases with auto-RAG
- **Web SSH Terminal** — SSH to fleet devices from the browser with key management
- **Native dashboard** — Next.js 16 + shadcn/ui web UI (:9090) with AI assistant
- **Hardware abstraction** — same experience on Jetson, Pi, or RK3588
- **Fully offline** — operates without cloud after initial setup

## Architecture

```
┌───────────────────────────────────────────────────┐
│                   BMT AI OS                       │
├───────────────────────────────────────────────────┤
│  AI Workspace (:9090)                             │
│  Monaco Editor │ Terminal │ File Manager │ Chat   │
│  AI Coding (Claude/Codex/Gemini) │ Knowledge     │
├───────────────────────────────────────────────────┤
│  Coding CLIs        │  IDE Plugins  │  Code Agents│
│  Claude Code, Aider │  Cursor       │  SWE-agent  │
│  Continue, Tabby    │  Copilot,Cody │  Codex CLI  │
├───────────────────────────────────────────────────┤
│  Training (PyTorch) │  RAG Pipeline │  REST API   │
│  LoRA/QLoRA         │  ChromaDB     │  :8080      │
│  Jupyter (:8888)    │  :8000        │  OpenAI-    │
│  TensorBoard (:6006)│               │  compatible │
├───────────────────────────────────────────────────┤
│  Persona System     │  Knowledge Vaults (Obsidian)│
│  SOUL.md presets    │  Per-agent RAG collections  │
├───────────────────────────────────────────────────┤
│         Provider Abstraction Layer                │
│  Local: Ollama(:11434), vLLM, llama.cpp           │
│  Cloud: OpenAI, Anthropic, Gemini, Mistral, Groq  │
├───────────────────────────────────────────────────┤
│  Containerd + Docker CLI │ NPU/GPU passthrough    │
├───────────────────────────────────────────────────┤
│  Linux Kernel (Buildroot, ARM64/aarch64, OpenRC)  │
└───────────────────────────────────────────────────┘
```

## Hardware Targets

| Hardware | Accelerator | LLM Performance | Training | Price |
|----------|-------------|-----------------|----------|-------|
| Apple Silicon (M1-M4, Asahi Linux) | CPU (NEON) | 7B @ 30-50 tok/s | LoRA 3B ~20min | $800+ |
| NVIDIA Jetson Orin Nano Super | 67 TOPS CUDA | 7B @ 15-22 tok/s | LoRA 1.5B ~30min | ~$250 |
| Raspberry Pi 5 + AI HAT+ 2 | 40 TOPS Hailo-10H | 1.5B @ 9.5 tok/s | LoRA <1B | ~$210 |
| RK3588 boards (Orange Pi 5, ROCK 5B) | 6 TOPS RKNN | 7B @ 4-6 tok/s (CPU) | LoRA 1.5B ~3hrs | $100-180 |

## Port Map

| Port | Service |
|------|---------|
| 6006 | TensorBoard |
| 8000 | ChromaDB |
| 8080 | OpenAI-compatible API |
| 8888 | Jupyter Lab |
| 9090 | Dashboard (Web UI) |
| 11434 | Ollama |

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.11+
- Node.js 18+ and npm

### Run the AI Stack

```bash
# Start Ollama + ChromaDB
cd bmt_ai_os/ai-stack
docker compose up -d

# Verify services
curl http://localhost:11434/api/tags        # Ollama
curl http://localhost:8000/api/v1/heartbeat  # ChromaDB
```

### Run the Controller

```bash
pip install -e .
BMT_COMPOSE_FILE=$(pwd)/bmt_ai_os/ai-stack/docker-compose.yml \
  PYTHONPATH=$(pwd) python3 -m bmt_ai_os.controller.main
```

See the [Quick Start guide](getting-started/quick-start.md) for a full walkthrough.

## Tech Stack

| Component | Technology |
|-----------|------------|
| Architecture | ARM64 (aarch64) |
| Base OS | Alpine Linux via Buildroot |
| Init System | OpenRC |
| Container Runtime | containerd + Docker CLI |
| LLM Inference | Ollama, vLLM, llama.cpp |
| Vector Database | ChromaDB |
| Training | PyTorch + HF Transformers + PEFT (LoRA/QLoRA) |
| Dashboard | Next.js 16 + shadcn/ui + Tailwind CSS 4 |
| TUI | Python Textual |
| Controller | Python + FastAPI + docker-py |
| Hardware Accel | CUDA (Jetson), RKNN (RK3588), HailoRT (Pi 5) |

## Limitations

- **ARM64 only** — OS image targets ARM64 boards; x86 supported only via dev Docker stack
- **Small model ceiling** — Tier 1 hardware limited to 7B models for inference, 1.5-3B for training
- **No GUI desktop** — headless OS with web dashboard and TUI; no windowing system
- **NPU support fragmented** — RKNN and HailoRT drivers are not mainlined in upstream Linux kernel

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](https://github.com/bemindlabs/bmt-ai-os/blob/main/CONTRIBUTING.md) for guidelines.

## License

[MIT License](https://github.com/bemindlabs/bmt-ai-os/blob/main/LICENSE) — Powered by [Bemind Technology Co., Ltd.](https://bemind.tech)
