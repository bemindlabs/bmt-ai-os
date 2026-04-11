<p align="center">
  <h1 align="center">BMT AI OS</h1>
  <p align="center">
    An open-source, AI-first operating system for ARM64
    <br />
    <a href="VISION.md"><strong>Vision</strong></a> · <a href="ROADMAP.md"><strong>Roadmap</strong></a> · <a href="CONTRIBUTING.md"><strong>Contributing</strong></a> · <a href="CHANGELOG.md"><strong>Changelog</strong></a>
  </p>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://github.com/bemindlabs/bmt-ai-os/releases/tag/v2026.4.11"><img src="https://img.shields.io/badge/version-2026.4.11-green.svg" alt="Version"></a>
  <a href="https://github.com/bemindlabs/bmt-ai-os"><img src="https://img.shields.io/badge/arch-ARM64-orange.svg" alt="Architecture: ARM64"></a>
  <a href="https://github.com/bemindlabs/bmt-ai-os"><img src="https://img.shields.io/badge/progress-100%25_(59%2F59_stories)-brightgreen.svg" alt="Progress: 100%"></a>
</p>

---

Containerized LLM inference, local RAG, AI coding tools, and on-device model training — all on a $100 ARM64 board. Fully offline after initial setup.

Powered by [Bemind Technology Co., Ltd.](https://bemind.tech)

## Key Features

- **Boot to AI** — LLM inference + RAG start as system services on boot
- **Multi-provider** — Ollama, vLLM, llama.cpp locally; OpenAI, Anthropic, Gemini as cloud fallback
- **Coding tools** — Claude Code, Aider, Continue, Tabby pre-installed and auto-configured
- **On-device training** — LoRA/QLoRA fine-tuning with PyTorch on edge hardware
- **Native dashboard** — Next.js + shadcn/ui web UI (:9090) and Python Textual TUI
- **Hardware abstraction** — same experience on Jetson, Pi, or RK3588
- **Fully offline** — operates without cloud after initial setup

## Architecture

```
┌───────────────────────────────────────────────────┐
│                   BMT AI OS                       │
├───────────────────────────────────────────────────┤
│  Dashboard (:9090)  │  TUI (bmt_ai_os tui)        │
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

## Hardware Targets

| Hardware | Accel | LLM Performance | Training | Price |
|----------|-------|-----------------|----------|-------|
| Apple Silicon (M1-M4, Asahi Linux) | CPU (NEON) | 7B @ 30-50 tok/s | LoRA 3B ~20min | $800+ |
| NVIDIA Jetson Orin Nano Super | 67 TOPS CUDA | 7B @ 15-22 tok/s | LoRA 1.5B ~30min | ~$250 |
| Raspberry Pi 5 + AI HAT+ 2 | 40 TOPS Hailo-10H | 1.5B @ 9.5 tok/s | LoRA <1B | ~$210 |
| RK3588 boards (Orange Pi 5, ROCK 5B) | 6 TOPS RKNN | 7B @ 4-6 tok/s (CPU) | LoRA 1.5B ~3hrs | $100-180 |

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.10+
- Node.js 18+ & npm

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

# Or via Docker
docker build -t bmt-ai-os . && docker run -p 8080:8080 --network bmt-ai-net bmt-ai-os
```

### Build the OS Image

```bash
# Cross-compile for ARM64 (requires Buildroot toolchain)
make O=output defconfig BR2_DEFCONFIG=bmt_ai_os/kernel/defconfig
make

# Test with QEMU
qemu-system-aarch64 \
  -M virt -cpu cortex-a72 -m 4G \
  -kernel output/images/Image \
  -drive file=output/images/rootfs.ext4,format=raw \
  -nographic
```

## Repository Structure

```
ai-first-os/
├── bmt_ai_os/                # Runtime
│   ├── kernel/               # Buildroot defconfig, linux.config, uboot.config
│   ├── ai-stack/             # Docker Compose (Ollama, ChromaDB, vLLM, llama.cpp, Jupyter)
│   ├── controller/           # FastAPI orchestration (health, auth, providers, RAG, plugins)
│   ├── providers/            # LLM provider abstraction (8 providers, fallback router)
│   ├── rag/                  # RAG pipeline (ingest, chunk, embed, query, stream)
│   ├── fleet/                # Fleet management (agent, registry, device heartbeats)
│   ├── ota/                  # OTA update engine (A/B slot switching, rollback)
│   ├── update/               # OS update orchestrator (4-stage pipeline)
│   ├── plugins/              # Plugin system (manifests, lifecycle, sandboxed hooks)
│   ├── tls/                  # TLS/mTLS (certs, cipher hardening, PKI)
│   ├── benchmark/            # Performance benchmarks (inference, RAG, system)
│   ├── dashboard/            # Next.js 15 + shadcn/ui web dashboard (6 pages)
│   └── runtime/              # OpenRC init, containerd, networking, security, monitoring
├── bmt-ai-os-build/          # Build infrastructure
│   ├── base-config.toml      # Base distro config (Alpine, aarch64)
│   ├── buildroot-external/   # Buildroot packages (containerd, docker, ollama, training)
│   └── layers/               # BitBake/Yocto layers (NPU drivers, etc.)
├── scripts/                  # Build, QEMU test, CI, benchmarking, boot timing
├── tests/                    # Unit tests (smoke, integration, unit — 950 tests)
├── docs/                     # Architecture, IDE integration, security policy
├── .scrum/                   # Backlog (59 stories, 7 epics, 368 pts — all complete)
├── VISION.md                 # Strategic vision
├── ROADMAP.md                # 8-phase roadmap (Phases 1-5 complete)
└── CLAUDE.md                 # Claude Code guidance
```

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
| Training | PyTorch + HF Transformers + PEFT (LoRA/QLoRA) |
| Dashboard | Next.js 15 + shadcn/ui + Tailwind CSS |
| TUI | Python Textual |
| Controller | Python + FastAPI + docker-py |
| Hardware Accel | CUDA (Jetson), RKNN (RK3588), HailoRT (Pi 5) |

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the full 8-phase plan.

| Phase | Epic | Points | Status |
|-------|------|--------|--------|
| 1 | OS Foundation | 86 | **Complete** |
| 2 | Multi-Provider | 35 | **Complete** |
| 3 | Coding Tools | 36 | **Complete** |
| 4 | Dashboard | 52 | **Complete** |
| 5 | Training | 36 | **Complete** |
| 6 | Hardware BSPs | 29 | **Complete** |
| 7 | Production Hardening | 76 | **Complete** |

## Limitations

- **ARM64 only** — OS image targets ARM64 boards; x86 supported only via [dev Docker stack](docker-compose.dev.yml)
- **Small model ceiling** — Tier 1 hardware limited to 7B models for inference, 1.5-3B for training
- **No GUI desktop** — headless OS with web dashboard and TUI; no windowing system
- **NPU support fragmented** — RKNN and HailoRT drivers are not mainlined in upstream Linux kernel
- **Training is constrained** — LoRA/QLoRA on edge hardware is slow; full fine-tuning not feasible on 8GB devices
- **Qualcomm NPU blocked** — Snapdragon X Linux NPU support dead (DSP headers not open-sourced)
- **Cloud providers require internet** — fallback to OpenAI/Anthropic/Gemini only works when online

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

- [Report a Bug](.github/ISSUE_TEMPLATE/bug_report.md)
- [Request a Feature](.github/ISSUE_TEMPLATE/feature_request.md)
- [Security Policy](SECURITY.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)

## License

[MIT License](LICENSE) — Powered by [Bemind Technology Co., Ltd.](https://bemind.tech)
