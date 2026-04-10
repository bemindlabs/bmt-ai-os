# BMT AI OS

AI-first operating system for ARM64, built on a minimal Linux base with containerized LLM inference and local RAG capabilities.

## Architecture

```
┌─────────────────────────────────────────────┐
│                BMT AI OS                    │
├─────────────────────────────────────────────┤
│  CLI / REST API                             │
├─────────────────────────────────────────────┤
│  Controller (Python)                        │
│  ├── Container lifecycle management         │
│  ├── Health monitoring & auto-recovery      │
│  └── RAG pipeline orchestration             │
├──────────────────┬──────────────────────────┤
│  Ollama (LLM)    │  ChromaDB (Vector DB)    │
│  :11434          │  :8000                   │
├──────────────────┴──────────────────────────┤
│  Containerd + Docker CLI                    │
│  GPU/NPU passthrough (Rockchip, Mali)       │
├─────────────────────────────────────────────┤
│  Linux Kernel (Buildroot, ARM64/aarch64)    │
└─────────────────────────────────────────────┘
```

## Project Structure

```
bmt_ai_os/
├── SPECIFICATION.md          # Architecture & requirements
├── kernel/
│   └── defconfig             # Buildroot ARM64 kernel config
├── runtime/                  # Boot scripts & init services
├── ai-stack/
│   └── docker-compose.yml    # Ollama + ChromaDB services
└── controller/
    └── main.py               # Container orchestration controller

bmt_ai_os-build/
├── base-config.toml          # Base system config (Alpine, aarch64)
├── layers/ai-first-layer/
│   ├── recipes-ai/
│   │   └── hardware-accel.bb # NPU/GPU driver recipe
│   └── recipes-containers/
│       └── container-engine.bb
└── services/
    └── ai-stack.yml          # Service definitions
```

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.10+
- `docker` Python package (`pip install docker`)

### Run the AI Stack (Development)

```bash
cd bmt_ai_os/ai-stack
docker compose up -d
```

### Verify Services

```bash
# Ollama
curl http://localhost:11434/api/tags

# ChromaDB
curl http://localhost:8000/api/v1/heartbeat
```

### Run the Controller

```bash
cd bmt_ai_os/controller
pip install docker
python main.py
```

## Building the OS Image

The full ARM64 image is built with Buildroot using the config in `kernel/defconfig` and the BitBake layers in `bmt_ai_os-build/`.

```bash
# Cross-compile for ARM64 (requires Buildroot toolchain)
make O=output defconfig BR2_DEFCONFIG=bmt_ai_os/kernel/defconfig
make
```

### Testing with QEMU

```bash
qemu-system-aarch64 \
  -M virt -cpu cortex-a72 -m 4G \
  -kernel output/images/Image \
  -drive file=output/images/rootfs.ext4,format=raw \
  -nographic
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| Architecture | ARM64 (aarch64) |
| Base OS | Alpine Linux via Buildroot |
| Container Runtime | containerd + Docker CLI |
| LLM Server | Ollama |
| Vector Database | ChromaDB |
| Hardware Accel | Rockchip NPU, Mali GPU |
| Controller | Python + docker-py |

## Goals

- Zero-latency local RAG — retrieval-augmented generation without cloud dependencies
- NPU-accelerated inference on ARM64 hardware
- Minimal footprint — lightweight Linux base with only essential services
- Container-native — all AI services run in isolated containers
- Self-contained — operates fully offline after initial setup

## License

MIT License — Powered by [Bemind Technology Co., Ltd.](https://bemind.tech)
