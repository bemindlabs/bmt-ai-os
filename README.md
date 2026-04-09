# ai-first-os

Monorepo for **BMT AI OS** — an open-source, AI-first operating system for ARM64 with containerized LLM inference, local RAG, AI coding tools, and on-device model training.

Powered by [Bemind Technology Co., Ltd.](https://bemind.tech)

## Architecture

```
┌───────────────────────────────────────────────────┐
│                   BMT AI OS                       │
├───────────────────────────────────────────────────┤
│  Dashboard (:9090)  │  TUI (bmt-ai-os tui)       │
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
│         Provider Abstraction Layer                │
│  Local: Ollama(:11434), vLLM, llama.cpp           │
│  Cloud: OpenAI, Anthropic, Gemini, Mistral, Groq  │
├───────────────────────────────────────────────────┤
│  Containerd + Docker CLI │ NPU/GPU passthrough    │
├───────────────────────────────────────────────────┤
│  Linux Kernel (Buildroot, ARM64/aarch64, OpenRC)  │
└───────────────────────────────────────────────────┘
```

## Repository Structure

```
ai-first-os/
├── bmt-ai-os/                # Runtime components
│   ├── SPECIFICATION.md      # Architecture & requirements
│   ├── kernel/defconfig      # Buildroot ARM64 config (37 packages)
│   ├── runtime/              # Boot scripts & init services
│   ├── ai-stack/             # Ollama + ChromaDB Docker Compose
│   ├── controller/           # Python container orchestration
│   └── dashboard/            # Next.js + shadcn/ui web dashboard
├── bmt-ai-os-build/          # Build infrastructure
│   ├── base-config.toml      # Base distro config (Alpine, aarch64)
│   ├── layers/               # BitBake/Yocto layers
│   └── services/             # Service definitions
├── VISION.md                 # Strategic vision & roadmap
├── CLAUDE.md                 # Claude Code guidance
└── .scrum/                   # Sprint & backlog tracking (42 stories)
```

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.10+
- Node.js 18+ & npm

### Run the AI Stack

```bash
cd bmt-ai-os/ai-stack
docker compose up -d

# Verify
curl http://localhost:11434/api/tags        # Ollama
curl http://localhost:8000/api/v1/heartbeat  # ChromaDB
```

### Run the Controller

```bash
pip install docker
python bmt-ai-os/controller/main.py
```

## Building the OS Image

Full ARM64 image is built with Buildroot using `kernel/defconfig` and BitBake layers from `bmt-ai-os-build/`.

```bash
make O=output defconfig BR2_DEFCONFIG=bmt-ai-os/kernel/defconfig
make

# Test with QEMU
qemu-system-aarch64 \
  -M virt -cpu cortex-a72 -m 4G \
  -kernel output/images/Image \
  -drive file=output/images/rootfs.ext4,format=raw \
  -nographic
```

## Hardware Targets

| Hardware | NPU/GPU | LLM Performance | Price |
|----------|---------|-----------------|-------|
| NVIDIA Jetson Orin Nano Super | 67 TOPS CUDA | 7B @ 15-22 tok/s | ~$250 |
| Raspberry Pi 5 + AI HAT+ 2 | 40 TOPS Hailo-10H | 1.5B @ 9.5 tok/s | ~$210 |
| RK3588 boards (Orange Pi 5, ROCK 5B) | 6 TOPS RKNN | 7B @ 4-6 tok/s (CPU) | $100-180 |

## Port Map

| Port | Service |
|------|---------|
| 6006 | TensorBoard |
| 8000 | ChromaDB |
| 8080 | OpenAI-compatible API |
| 8888 | Jupyter Lab |
| 9090 | Dashboard (Web UI) |
| 11434 | Ollama |

## Tech Stack

| Component | Technology |
|-----------|------------|
| Architecture | ARM64 (aarch64) |
| Base OS | Alpine Linux via Buildroot |
| Init System | OpenRC |
| Container Runtime | containerd + Docker CLI |
| LLM Inference | Ollama, vLLM, llama.cpp |
| Vector Database | ChromaDB |
| Training | PyTorch + HF Transformers + LoRA/QLoRA |
| Dashboard | Next.js + shadcn/ui + Tailwind CSS |
| TUI | Python Textual |
| Controller | Python + docker-py |
| Hardware Accel | CUDA (Jetson), RKNN (RK3588), Hailo (Pi 5) |

## Key Features

- **Boot to AI** — LLM inference + RAG as system services, not apps
- **Multi-provider** — Ollama, vLLM, llama.cpp locally; OpenAI, Anthropic, Gemini as cloud fallback
- **Coding tools** — Claude Code, Aider, Continue, Tabby pre-installed and auto-configured
- **On-device training** — LoRA/QLoRA fine-tuning with PyTorch on edge hardware
- **Native dashboard** — Next.js + shadcn/ui web UI and Textual TUI
- **Hardware abstraction** — same experience on Jetson, Pi, or RK3588
- **Fully offline** — operates without cloud after initial setup

## License

MIT License — Powered by [Bemind Technology Co., Ltd.](https://bemind.tech)
