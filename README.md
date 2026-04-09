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
  <a href="https://github.com/bemindlabs/bmt-ai-os"><img src="https://img.shields.io/badge/version-2026.4.9-green.svg" alt="Version"></a>
  <a href="https://github.com/bemindlabs/bmt-ai-os"><img src="https://img.shields.io/badge/arch-ARM64-orange.svg" alt="Architecture: ARM64"></a>
  <a href="https://github.com/bemindlabs/bmt-ai-os"><img src="https://img.shields.io/badge/status-active--development-yellow.svg" alt="Status: Active Development"></a>
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
│  Dashboard (:9090)  │  TUI (bmt-ai-os tui)        │
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

| Hardware | NPU/GPU | LLM Performance | Training | Price |
|----------|---------|-----------------|----------|-------|
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
cd bmt-ai-os/ai-stack
docker compose up -d

# Verify services
curl http://localhost:11434/api/tags        # Ollama
curl http://localhost:8000/api/v1/heartbeat  # ChromaDB
```

### Run the Controller

```bash
pip install docker
python bmt-ai-os/controller/main.py
```

### Build the OS Image

```bash
# Cross-compile for ARM64 (requires Buildroot toolchain)
make O=output defconfig BR2_DEFCONFIG=bmt-ai-os/kernel/defconfig
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
├── bmt-ai-os/                # Runtime
│   ├── kernel/defconfig      # Buildroot ARM64 config (37 packages)
│   ├── ai-stack/             # Ollama + ChromaDB Docker Compose
│   ├── controller/           # Python container orchestration
│   └── runtime/              # Boot scripts & init services
├── bmt-ai-os-build/          # Build infrastructure
│   ├── base-config.toml      # Base distro config (Alpine, aarch64)
│   └── layers/               # BitBake/Yocto layers (NPU drivers, etc.)
├── .scrum/                   # Backlog (48 stories, 6 epics, 292 pts)
├── VISION.md                 # Strategic vision
├── ROADMAP.md                # 8-phase roadmap
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

| Phase | Epic | Points | Focus |
|-------|------|--------|-------|
| 1 | OS Foundation | 86 | Bootable ARM64 image, containerd, init, CI |
| 2 | Multi-Provider | 35 | Provider abstraction, fallback chain |
| 3 | Coding Tools | 36 | Claude Code, Aider, Continue, Tabby, IDE plugins |
| 4 | Dashboard | 52 | Next.js + shadcn/ui web UI, Textual TUI |
| 5 | Training | 36 | PyTorch, LoRA/QLoRA, Jupyter, TensorBoard |
| 6 | Hardware BSPs | 21 | Jetson, RK3588, Pi 5 + Hailo |
| 7 | Tooling | 26 | CLI, REST API, logging, OTA updates |
| 8 | Production | TBD | Fleet management, security hardening |

## Limitations

- **Early stage** — project is in active development; no bootable image available yet
- **ARM64 only** — OS image targets ARM64 boards; x86 supported only via [dev Docker stack](docker-compose.dev.yml)
- **Small model ceiling** — Tier 1 hardware limited to 7B models for inference, 1.5-3B for training
- **No GUI desktop** — headless OS with web dashboard and TUI; no windowing system
- **NPU support fragmented** — RKNN and HailoRT drivers are not mainlined in upstream Linux kernel
- **Training is constrained** — LoRA/QLoRA on edge hardware is slow; full fine-tuning not feasible on 8GB devices
- **Single-user** — no multi-user accounts or access control yet
- **No OTA updates** — update mechanism planned (BMTOS-25) but not implemented
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
