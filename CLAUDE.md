# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

BMT AI OS is an open-source, AI-first operating system for ARM64 by Bemind Technology Co., Ltd. It uses a minimal Linux base (Buildroot) with containerized LLM inference, vector search, AI coding tools, and on-device model training. MIT licensed.

Current release: **v2026.4.12**

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
│   │   ├── auth.py             #     JWT auth + RBAC (admin/operator/viewer)
│   │   ├── auth_routes.py      #     Auth API routes (login/logout/me)
│   │   ├── conversation_routes.py #  Conversation CRUD + search
│   │   ├── training_routes.py  #     Training job management API
│   │   ├── persona_routes.py   #     Persona CRUD API
│   │   ├── prometheus.py       #     Prometheus /metrics endpoint
│   │   ├── plugin_routes.py    #     Plugin management API
│   │   ├── rate_limit.py       #     Per-IP sliding window rate limiter
│   │   ├── health.py           #     Health checker + circuit breaker
│   │   ├── metrics.py          #     Internal metrics collector
│   │   ├── config.py           #     Controller config (YAML loader)
│   │   └── middleware.py       #     CORS + logging + request ID middleware
│   ├── providers/              #   Multi-provider LLM abstraction (8 providers)
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
│   ├── memory/                 #   Conversation memory + context engine
│   │   ├── store.py            #     SQLite conversation persistence
│   │   ├── context.py          #     Token budget + compaction engine
│   │   ├── search.py           #     Hybrid BM25 + vector search
│   │   └── dreaming.py         #     Memory consolidation system
│   ├── persona/                #   AI persona system
│   │   ├── loader.py           #     SOUL.md workspace file loader
│   │   ├── assembler.py        #     System prompt assembly
│   │   ├── config.py           #     Agent persona config
│   │   └── presets/            #     coding.md, general.md, creative.md
│   ├── fleet/                  #   Fleet management
│   │   ├── agent.py            #     Fleet agent (heartbeats, offline queue)
│   │   ├── registry.py         #     SQLite-backed device registry
│   │   ├── routes.py           #     Fleet API routes
│   │   └── models.py           #     Data models
│   ├── ota/                    #   OTA update engine
│   │   ├── engine.py           #     A/B slot switching + rollback
│   │   ├── state.py            #     OTA state management
│   │   └── verify.py           #     Image verification (SHA-256, Ed25519)
│   ├── update/                 #   OS update orchestration
│   │   └── orchestrator.py     #     4-stage update pipeline
│   ├── training/               #   On-device training
│   │   ├── lora.py             #     LoRA/QLoRA fine-tuning module
│   │   ├── data_prep.py        #     Dataset preparation tools
│   │   └── export.py           #     Model export (GGUF/Ollama)
│   ├── mcp/                    #   Claude Code integration
│   │   └── server.py           #     MCP server (JSON-RPC 2.0)
│   ├── messaging/              #   Multi-channel delivery
│   │   └── channels.py         #     Webhook + file channel router
│   ├── plugins/                #   Plugin system
│   │   ├── manager.py          #     Plugin lifecycle + sandboxed execution
│   │   ├── loader.py           #     Plugin discovery (manifests + entry points)
│   │   └── hooks.py            #     Hook types + plugin manifest
│   ├── tls/                    #   TLS/mTLS support
│   │   ├── config.py           #     TLS config + cipher hardening
│   │   ├── certs.py            #     Self-signed cert generation + renewal
│   │   └── mtls.py             #     mTLS PKI (CA, server, client certs)
│   ├── benchmark/              #   Performance benchmarking
│   │   ├── suite.py            #     Benchmark suite runner + reports
│   │   ├── inference.py        #     Inference benchmarks
│   │   ├── rag.py              #     RAG benchmarks
│   │   └── system.py           #     CPU/memory/disk benchmarks
│   ├── cli.py                  #   CLI entry point (Click)
│   ├── logging.py              #   Structured JSON logging + rotation
│   ├── secret_files.py         #   /run/secrets/ file reader
│   ├── dashboard/              #   Next.js 16 web dashboard
│   │   └── src/
│   │       ├── app/            #     Pages: /, /chat, /models, /providers,
│   │       │                   #     /training, /logs, /settings, /login, /agents
│   │       ├── components/     #     UI components (shadcn/ui + custom)
│   │       └── lib/            #     API client, auth, sessions, commands
│   ├── kernel/                 #   Kernel configs
│   │   ├── defconfig           #     Buildroot ARM64 defconfig
│   │   ├── linux.config        #     Kernel config fragment
│   │   └── uboot.config        #     U-Boot config
│   └── runtime/                #   OS runtime configs
│       ├── init.d/             #     OpenRC init scripts
│       ├── networking/         #     Network setup, firewall, DNS-over-TLS
│       ├── monitoring/         #     Prometheus alerts + Grafana dashboard
│       ├── containerd/         #     Container runtime config
│       ├── docker/             #     Docker daemon config
│       ├── npu/                #     NPU passthrough stubs
│       └── security/           #     AppArmor/seccomp profiles, secrets
├── bmt-ai-os-build/            # Build-time
│   ├── buildroot-external/     #   Buildroot external tree
│   ├── layers/                 #   BitBake layers (Yocto)
│   └── services/               #   Service definitions
├── tests/
│   ├── smoke/                  #   Compose validation + security tests
│   ├── unit/                   #   1900+ unit tests
│   ├── e2e/                    #   28 end-to-end controller tests
│   ├── load/                   #   12 load/throughput tests
│   ├── security/               #   31 OWASP security tests
│   └── integration/            #   QEMU boot + networking tests
├── scripts/
│   └── build.sh                #   Buildroot image build pipeline
├── docs/                       #   MkDocs site (architecture, API, hardware)
├── .scrum/                     #   Backlog, epics, sprints, ceremonies
├── .github/workflows/          #   CI (lint, test, trivy, benchmark, docs)
├── Dockerfile                  #   Multi-stage controller image
├── docker-compose.dev.yml      #   Full dev stack
├── pyproject.toml              #   Python config (ruff, pytest, setuptools)
└── CLAUDE.md                   #   This file
```

## Architecture

The controller (`bmt_ai_os/controller/main.py`) orchestrates AI-stack containers via docker-py, registers LLM providers, and exposes an OpenAI-compatible API.

**Dependency chain:** Kernel (defconfig) → OpenRC → Containerd → AI Stack (Compose) → Controller → Provider Layer → RAG + Training + Dashboard

**Import convention:** All Python imports use the canonical `bmt_ai_os.*` path. No symlinks or sys.path hacks needed — the package directory name matches the import name.

## Port Map

| Port | Service |
|------|---------|
| 8000 | ChromaDB |
| 8080 | Controller API (OpenAI-compatible) |
| 8443 | Controller API (HTTPS, when TLS enabled) |
| 9090 | Dashboard (Web UI) |
| 11434 | Ollama |

## Commands

```bash
# Run full dev stack
docker compose -f docker-compose.dev.yml up -d

# Run AI stack only
docker compose -f bmt_ai_os/ai-stack/docker-compose.yml up -d

# Run controller locally
BMT_COMPOSE_FILE=$(pwd)/bmt_ai_os/ai-stack/docker-compose.yml \
  BMT_JWT_SECRET=$(openssl rand -hex 32) BMT_ENV=dev \
  PYTHONPATH=$(pwd) python3 -m bmt_ai_os.controller.main

# Run tests
python3 -m pytest tests/smoke/ tests/unit/ tests/e2e/ tests/security/ -q

# Lint + format
uvx ruff check bmt_ai_os/ tests/
uvx ruff format --check bmt_ai_os/ tests/

# Build OS image (requires Linux host)
./scripts/build.sh --target qemu

# Build dashboard
cd bmt_ai_os/dashboard && npx next build
```

## Branching Strategy

```
main          ← production-ready, protected (requires PR + review)
  ↑
develop       ← integration branch, direct push allowed
  ↑
feature/*     ← short-lived feature branches (auto-deleted on merge)
```

## Scrum / Project Management

The `.scrum/` directory tracks backlog, sprints, and ceremonies. Backlog items use the `BMTOS-{n}` ID scheme with Fibonacci estimation. Workflow: `backlog → ready → in_progress → review → testing → done`.

**Epics (all completed):**

- BMTOS-EPIC-1: Multi-Provider LLM Support (35 pts) — DONE
- BMTOS-EPIC-2: AI Coding CLI & Agent Support (36 pts) — DONE
- BMTOS-EPIC-3: OS Foundation & Infrastructure (86 pts) — DONE
- BMTOS-EPIC-4: Hardware Board Support Packages (29 pts) — DONE
- BMTOS-EPIC-5: Native Dashboard (52 pts) — DONE
- BMTOS-EPIC-6: On-Device AI Training Framework (36 pts) — DONE
- BMTOS-EPIC-7: Production Hardening (76 pts) — DONE
- BMTOS-EPIC-8: Security & Production Readiness (68 pts) — DONE
- BMTOS-EPIC-9: AI Memory & Conversations (44 pts) — DONE
- BMTOS-EPIC-10: Dashboard AI Assistant (39 pts) — DONE
- BMTOS-EPIC-10b: Training Pipeline Implementation (60 pts) — DONE
- BMTOS-EPIC-11: Claude Code Integration (21 pts) — DONE
- BMTOS-EPIC-12: AI Persona System (24 pts) — DONE
- BMTOS-EPIC-13: Dashboard Integration Sprint (25 pts) — DONE
- BMTOS-EPIC-14: AI Workspace (55 pts) — DONE
- BMTOS-EPIC-15: Dynamic Provider Configuration (22 pts) — DONE
- BMTOS-EPIC-16: Web SSH Terminal (22 pts) — DONE
- BMTOS-EPIC-17: Enhanced Provider Management (21 pts) — DONE
- BMTOS-EPIC-18: Multi-Agent Persona Knowledge Vaults (39 pts) — DONE
- BMTOS-EPIC-19: Integrated Editor Terminal (16 pts) — DONE
- BMTOS-EPIC-20: Multi-Provider AI Coding & Models (21 pts) — DONE
- BMTOS-EPIC-21: AI Coding Workflow (26 pts) — DONE
- BMTOS-EPIC-22: Raspberry Pi 5 Bootable OS Image (47 pts) — DONE
- BMTOS-EPIC-23: AI DLC & Custom OS Builder (47 pts) — DONE

## Tech Stack

- **Backend:** Python + FastAPI + docker-py + uvicorn
- **Inference:** Ollama, vLLM, llama.cpp (provider abstraction layer)
- **Database:** ChromaDB (vector), SQLite (metadata, auth, fleet, conversations)
- **Frontend:** Next.js 16 + shadcn/ui + Tailwind CSS 4
- **Training:** PyTorch + Hugging Face Transformers + PEFT (LoRA/QLoRA)
- **Init:** OpenRC
- **Build:** Buildroot 2024.02.9 + BitBake layers
- **CI:** GitHub Actions + pre-commit (ruff, shellcheck, trivy)

## Key Constraints

- Target architecture is ARM64 (aarch64) — all configs must be ARM64-compatible
- Tier 1 targets: Apple Silicon (CPU-first), Jetson Orin Nano Super, RK3588 boards, Pi 5 + Hailo AI HAT+
- Apple Silicon: CPU-only (no Metal/GPU on Linux), fastest ARM64 CPU inference
- NPU passthrough: CUDA (Jetson), RKNN (RK3588), HailoRT (Pi 5) with CPU-only fallback
- Network subnet: 172.30.0.0/16 (bmt-ai-net bridge)
- Controller auto-registers Ollama provider on startup (uses OLLAMA_HOST env var)
- All provider imports use `bmt_ai_os.providers.*` canonical path
- System must operate fully offline after initial setup
- Default models: Qwen-family (best open-source coding models in 2026)
- JWT auth required: set BMT_JWT_SECRET (32+ chars) and BMT_ENV=dev for development
- Default dev credentials: admin/admin (production requires BMT_ADMIN_PASS)
