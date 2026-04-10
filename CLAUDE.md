# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

BMT AI OS is an open-source, AI-first operating system for ARM64 by Bemind Technology Co., Ltd. It uses a minimal Linux base (Buildroot) with containerized LLM inference, vector search, AI coding tools, and on-device model training. MIT licensed.

Current release: **v2026.4.10**

## Project Structure

```
ai-first-os/
├── bmt_ai_os/                  # Runtime
│   ├── ai-stack/               #   Docker Compose (Ollama + ChromaDB)
│   │   ├── docker-compose.yml
│   │   ├── profiles/           #   Device tier profiles (lite/full)
│   │   └── scripts/            #   Stack management scripts
│   ├── controller/             #   Python FastAPI controller
│   │   ├── main.py             #     Entry point (orchestration + uvicorn)
│   │   ├── api.py              #     FastAPI app (/healthz)
│   │   ├── openai_compat.py    #     OpenAI-compatible /v1/chat/completions
│   │   ├── rag_routes.py       #     RAG API routes
│   │   ├── health.py           #     Health checker + circuit breaker
│   │   ├── config.py           #     Controller config (YAML loader)
│   │   └── middleware.py       #     CORS + logging middleware
│   ├── providers/              #   Multi-provider LLM abstraction
│   │   ├── base.py             #     ABC + data classes (ChatMessage, etc.)
│   │   ├── registry.py         #     Provider registry singleton
│   │   ├── router.py           #     Fallback chain router + circuit breaker
│   │   ├── config.py           #     Provider config + API key resolution
│   │   ├── ollama.py           #     Ollama provider (local)
│   │   ├── openai_provider.py  #     OpenAI-compatible base
│   │   ├── anthropic_provider.py
│   │   ├── gemini_provider.py
│   │   ├── groq_provider.py
│   │   ├── mistral_provider.py
│   │   ├── vllm.py             #     vLLM provider (local)
│   │   ├── llamacpp.py         #     llama.cpp provider (local)
│   │   └── providers.yml       #     Provider configuration
│   ├── rag/                    #   RAG pipeline
│   │   ├── query.py            #     RAG query engine
│   │   ├── ingest.py           #     Document ingestion
│   │   ├── chunker.py          #     Text chunking
│   │   ├── storage.py          #     ChromaDB storage
│   │   └── config.py           #     RAG configuration
│   ├── kernel/                 #   Kernel configs
│   │   ├── defconfig           #     Buildroot ARM64 defconfig
│   │   ├── linux.config        #     Kernel config fragment
│   │   └── uboot.config        #     U-Boot config
│   └── runtime/                #   OS runtime configs
│       ├── init.d/             #     OpenRC init scripts
│       ├── networking/         #     Network setup, firewall, DNS
│       ├── containerd/         #     Container runtime config
│       ├── docker/             #     Docker daemon config
│       ├── npu/                #     NPU passthrough stubs
│       └── security/           #     Security hardening
├── bmt_ai_os-build/            # Build-time
│   ├── buildroot-external/     #   Buildroot external tree
│   │   ├── Config.in           #     Package menu (BR2_EXTERNAL)
│   │   ├── external.mk         #     Package includes
│   │   ├── external.desc       #     Tree descriptor (BMT_AI_OS)
│   │   └── package/            #     Custom packages
│   │       ├── ollama/
│   │       ├── chromadb/
│   │       ├── containerd/
│   │       ├── docker-cli/
│   │       ├── bmt-controller/
│   │       └── bmt-npu-stub/
│   ├── layers/                 #   BitBake layers (Yocto)
│   └── services/               #   Service definitions
├── tests/
│   ├── smoke/                  #   Compose validation tests
│   ├── unit/                   #   Provider, RAG, router tests (295 tests)
│   └── integration/            #   QEMU boot + networking tests
├── scripts/
│   └── build.sh                #   Buildroot image build pipeline
├── docs/                       #   Architecture, hardware, IDE docs
├── releases/                   #   Release notes + build artifacts (gitignored)
├── .scrum/                     #   Backlog, epics, sprints, ceremonies
├── .github/workflows/ci.yml    #   CI pipeline
├── .pre-commit-config.yaml     #   Quality gates (ruff, shellcheck, tests)
├── pyproject.toml              #   Python config (ruff, pytest, setuptools)
├── conftest.py                 #   Pytest root config (bmt_ai_os path setup)
└── CLAUDE.md                   #   This file
```

## Architecture

The controller (`bmt_ai_os/controller/main.py`) orchestrates AI-stack containers via docker-py, registers LLM providers, and exposes an OpenAI-compatible API.

**Dependency chain:** Kernel (defconfig) → OpenRC → Containerd → AI Stack (Compose) → Controller → Provider Layer → RAG + Training + Dashboard

**Import convention:** All Python imports use the canonical `bmt_ai_os.providers.*` path. A `bmt_ai_os` symlink to `bmt_ai_os/` is required for local development (or `pip install -e .`).

## Port Map

| Port | Service |
|------|---------|
| 8000 | ChromaDB |
| 8080 | Controller API (OpenAI-compatible) |
| 11434 | Ollama |

## Commands

```bash
# Run AI stack
docker compose -f bmt_ai_os/ai-stack/docker-compose.yml up -d

# Run controller
ln -sf bmt_ai_os bmt_ai_os  # one-time symlink
BMT_COMPOSE_FILE=$(pwd)/bmt_ai_os/ai-stack/docker-compose.yml \
  PYTHONPATH=$(pwd):bmt_ai_os python3 -m controller.main

# Run tests
python3 -m pytest tests/smoke/ tests/unit/ -q

# Lint + format
uvx ruff check bmt_ai_os/ tests/
uvx ruff format --check bmt_ai_os/ tests/

# Build OS image (requires Linux host)
./scripts/build.sh --target qemu
```

## Releases

Release notes and build artifacts in `releases/` (gitignored).

```bash
gh release create vYYYY.M.DD --target main --title "vYYYY.M.DD" --notes-file releases/vYYYY.M.DD.md
```

## Scrum / Project Management

The `.scrum/` directory tracks backlog, sprints, and ceremonies. Backlog items use the `BMTOS-{n}` ID scheme with Fibonacci estimation. Workflow: `backlog → ready → in_progress → review → testing → done`.

**Epics:**

- BMTOS-EPIC-1: Multi-Provider LLM Support (35 pts)
- BMTOS-EPIC-2: AI Coding CLI & Agent Support (36 pts)
- BMTOS-EPIC-3: OS Foundation & Infrastructure (73 pts)
- BMTOS-EPIC-4: Hardware Board Support Packages (29 pts)
- BMTOS-EPIC-5: Native Dashboard — Next.js + shadcn/ui + TUI (52 pts)
- BMTOS-EPIC-6: On-Device AI Training & Fine-Tuning (36 pts)

## Tech Stack

- **Backend:** Python + FastAPI + docker-py + uvicorn
- **Inference:** Ollama, vLLM, llama.cpp (provider abstraction layer)
- **Database:** ChromaDB (vector), SQLite (metadata)
- **Frontend:** Next.js 15 + shadcn/ui + Tailwind CSS
- **Training:** PyTorch + Hugging Face Transformers + PEFT (LoRA/QLoRA)
- **Init:** OpenRC
- **Build:** Buildroot 2024.02.9 + BitBake layers
- **CI:** GitHub Actions + pre-commit (ruff, shellcheck)

## Key Constraints

- Target architecture is ARM64 (aarch64) — all configs must be ARM64-compatible
- Tier 1 targets: Apple Silicon (CPU-first), Jetson Orin Nano Super, RK3588 boards, Pi 5 + Hailo AI HAT+
- Apple Silicon: CPU-only (no Metal/GPU on Linux), fastest ARM64 CPU inference
- NPU passthrough: CUDA (Jetson), RKNN (RK3588), HailoRT (Pi 5) with CPU-only fallback
- Network subnet: 172.30.0.0/16 (bmt-ai-net bridge)
- Controller auto-registers Ollama provider on startup
- All provider imports use `bmt_ai_os.providers.*` canonical path
- System must operate fully offline after initial setup
- Default models: Qwen-family (best open-source coding models in 2026)
