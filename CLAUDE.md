# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

BMT AI OS is an open-source, AI-first operating system for ARM64 by Bemind Technology Co., Ltd. It uses a minimal Linux base (Alpine/Buildroot) with containerized LLM inference, vector search, AI coding tools, and on-device model training. MIT licensed.

## Architecture

Three directories form the system:

- **`bmt-ai-os/`** — Runtime: kernel config, Docker Compose AI stack, Python controller, boot scripts, Next.js dashboard
- **`bmt-ai-os-build/`** — Build-time: Buildroot/Yocto BitBake layers, base distro config, hardware acceleration recipes
- **`.scrum/`** — Project management: backlog (42 stories), epics (6), sprints, ceremonies

The controller (`bmt-ai-os/controller/main.py`) orchestrates AI-stack containers via docker-py. It manages Ollama, ChromaDB, and training services.

**Dependency chain:** Kernel (defconfig) → OpenRC → Containerd → AI Stack (Compose) → Controller → Provider Layer → RAG + Training + Dashboard

**Known issue:** `bmt-ai-os-build/services/ai-stack.yml` references LanceDB while the main project uses ChromaDB. The canonical choice is ChromaDB.

## Port Map

| Port | Service |
|------|---------|
| 6006 | TensorBoard |
| 8000 | ChromaDB |
| 8080 | OpenAI-compatible API (IDE plugins) |
| 8888 | Jupyter Lab |
| 9090 | Dashboard (Next.js + shadcn/ui) |
| 11434 | Ollama |

## Commands

```bash
# Validate Docker Compose config
docker compose -f bmt-ai-os/ai-stack/docker-compose.yml config

# Run AI stack locally
docker compose -f bmt-ai-os/ai-stack/docker-compose.yml up -d

# Run tests
python -m pytest

# Run controller
python bmt-ai-os/controller/main.py
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

- **Frontend:** Next.js 15 + shadcn/ui (new-york style) + Tailwind CSS
- **TUI:** Python Textual
- **Backend:** Python + FastAPI + docker-py
- **Training:** PyTorch + Hugging Face Transformers + PEFT (LoRA/QLoRA)
- **Inference:** Ollama, vLLM, llama.cpp (provider abstraction layer)
- **Database:** ChromaDB (vector), SQLite (metadata)
- **Init:** OpenRC
- **Build:** Buildroot + BitBake layers

## Key Constraints

- Target architecture is ARM64 (aarch64) — all configs must be ARM64-compatible
- Tier 1 targets: Apple Silicon (Asahi Linux, CPU-first), Jetson Orin Nano Super, RK3588 boards, Pi 5 + Hailo AI HAT+ 2
- Apple Silicon: CPU-only via Asahi Linux (no Metal/GPU on Linux), fastest ARM64 CPU inference
- NPU passthrough: CUDA (Jetson), RKNN (RK3588), HailoRT (Pi 5) with CPU-only fallback
- Controller scope is AI-stack services only (defined in docker-compose.yml)
- RAG latency target: under 3 seconds on Jetson with 7B model and 1K-document corpus
- Dashboard must be under 2MB gzipped (static export for ARM64)
- System must operate fully offline after initial setup
- Default models: Qwen-family (best open-source coding models in 2026)
