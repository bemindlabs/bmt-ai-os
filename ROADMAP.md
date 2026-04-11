# BMT AI OS Roadmap

**Current Version:** `2026.4.11` | **Version Format:** `YYYY.M.D`

> 105 stories | 624 points | 12 epics | **105 stories done (624 pts, 100%)**

## Overview

```
Phase 1  ████████████████████████████████████████████████ ✅  86 pts  Foundation
Phase 2  ████████████████████████████████████████████████ ✅  35 pts  Providers
Phase 3  ████████████████████████████████████████████████ ✅  36 pts  Coding Tools
Phase 4  ████████████████████████████████████████████████ ✅  52 pts  Dashboard
Phase 5  ████████████████████████████████████████████████ ✅  36 pts  Training (Framework)
Phase 6  ████████████████████████████████████████████████ ✅  29 pts  Hardware BSPs
Phase 7  ████████████████████████████████████████████████ ✅  76 pts  Production Hardening
Phase 8  ████████████████████████████████████████████████ ✅  68 pts  Security Hardening
Phase 9  ████████████████████████████████████████████████ ✅  44 pts  AI Memory & Conversations
Phase 10 ████████████████████████████████████████████████ ✅  39 pts  Dashboard AI Assistant
Phase 11 ████████████████████████████████████████████████ ✅  81 pts  Training Pipeline + Claude
Phase 12 ████████████████████████████████████████████████ ✅  24 pts  AI Persona System
```

---

## Phase 1 — OS Foundation & Infrastructure

**Epic:** BMTOS-EPIC-3 | **Points:** 86 | **Status: COMPLETE**

Build the bootable ARM64 base system with containerized AI services.

| Story | Title | Pts | Status |
|-------|-------|-----|--------|
| BMTOS-1 | Finalize ARM64 Buildroot kernel configuration | 8 | Done |
| BMTOS-16 | Build bootable ARM64 image pipeline | 8 | Done |
| BMTOS-2a | Set up containerd runtime with boot integration | 5 | Done |
| BMTOS-2b | Configure GPU/NPU device passthrough for containers | 8 | Done |
| BMTOS-3 | Deploy Ollama + ChromaDB AI stack via Docker Compose | 5 | Done |
| BMTOS-4 | Implement controller for AI stack orchestration | 8 | Done |
| BMTOS-5a | Build document ingestion pipeline into ChromaDB | 5 | Done |
| BMTOS-5b | Build RAG query and augmented generation pipeline | 8 | Done |
| BMTOS-17 | Configure init system and service boot ordering | 8 | Done |
| BMTOS-18 | Set up QEMU testing and CI pipeline | 8 | Done |
| BMTOS-19 | Design filesystem layout and storage partitioning | 5 | Done |
| BMTOS-20 | Implement service discovery and container networking | 5 | Done |
| BMTOS-21 | Configure container security and secrets management | 5 | Done |

---

## Phase 2 — Multi-Provider LLM Support

**Epic:** BMTOS-EPIC-1 | **Points:** 35 | **Status: COMPLETE**

8 providers: Ollama, vLLM, llama.cpp (local) + OpenAI, Anthropic, Gemini, Groq, Mistral (cloud).

---

## Phase 3 — AI Coding CLI & Agent Support

**Epic:** BMTOS-EPIC-2 | **Points:** 36 | **Status: COMPLETE**

Pre-installed coding tools: Claude Code, Aider, Continue, Tabby, SWE-agent, Codex CLI.

---

## Phase 4 — Native Dashboard

**Epic:** BMTOS-EPIC-5 | **Points:** 52 | **Status: COMPLETE**

Next.js 16 + shadcn/ui web dashboard at `:9090` with 7 pages.

---

## Phase 5 — On-Device AI Training (Framework)

**Epic:** BMTOS-EPIC-6 | **Points:** 36 | **Status: COMPLETE**

PyTorch + Hugging Face PEFT framework for LoRA/QLoRA fine-tuning.

---

## Phase 6 — Hardware Board Support Packages

**Epic:** BMTOS-EPIC-4 | **Points:** 29 | **Status: COMPLETE**

Apple Silicon, Jetson Orin, RK3588, Pi 5 + Hailo AI HAT+ 2.

---

## Phase 7 — Production Hardening

**Epic:** BMTOS-EPIC-7 | **Points:** 76 | **Status: COMPLETE**

| Story | Title | Pts | Status |
|-------|-------|-----|--------|
| BMTOS-44 | OTA update engine with A/B slot switching | 8 | Done |
| BMTOS-45 | Multi-user authentication and RBAC | 8 | Done |
| BMTOS-46 | Fleet management agent and central registry | 13 | Done |
| BMTOS-47 | Performance benchmarking suite with CI | 8 | Done |
| BMTOS-48 | Plugin and extension system | 8 | Done |
| BMTOS-49 | Prometheus metrics export and alerting | 5 | Done |
| BMTOS-50 | Container security (AppArmor/seccomp) | 5 | Done |
| BMTOS-51 | MkDocs documentation site | 5 | Done |
| BMTOS-52 | TLS termination and network hardening | 5 | Done |
| BMTOS-53 | Structured JSON logging and rotation | 3 | Done |
| BMTOS-25 | OS update mechanism with rollback | 8 | Done |

---

## Phase 8 — Security & Production Readiness

**Epic:** BMTOS-EPIC-8 | **Points:** 68 | **Status: COMPLETE**

| Story | Title | Pts | Status |
|-------|-------|-----|--------|
| BMTOS-54 | Enforce JWT secret at startup + password complexity | 5 | Done |
| BMTOS-55 | Replace bare except clauses with typed exceptions | 5 | Done |
| BMTOS-56 | Rate limiting on auth and inference endpoints | 5 | Done |
| BMTOS-57 | Path traversal protection for RAG ingest | 3 | Done |
| BMTOS-58 | Secrets from /run/secrets/ files | 5 | Done |
| BMTOS-59 | Add all test categories to CI pipeline | 3 | Done |
| BMTOS-60 | Token revocation and account lockout | 5 | Done |
| BMTOS-61 | Fleet registry SQLite persistence | 8 | Done |
| BMTOS-62 | Container vulnerability scanning (Trivy) | 3 | Done |
| BMTOS-63 | Fix CI continue-on-error flags | 2 | Done |
| BMTOS-64 | Password complexity requirements | 2 | Done |
| BMTOS-65 | Unit tests for 10+ core modules | 13 | Done |
| BMTOS-66 | Production deployment runbook | 5 | Done |
| BMTOS-67 | Plugin manager lock fix | 3 | Done |
| BMTOS-68 | OTA Ed25519 signature verification | 3 | Done |

---

## Phase 9 — AI Memory & Conversations

**Epic:** BMTOS-EPIC-9 | **Points:** 44 | **Status: COMPLETE**

| Story | Title | Pts | Status |
|-------|-------|-----|--------|
| BMTOS-69 | Session/conversation persistence (SQLite) | 8 | Done |
| BMTOS-70 | Context engine with token budget + compaction | 8 | Done |
| BMTOS-71 | RAG auto-injection into chat completions | 5 | Done |
| BMTOS-72 | Hybrid BM25 + vector memory search | 5 | Done |
| BMTOS-73 | Conversation history API | 5 | Done |
| BMTOS-74 | Memory dreaming/consolidation system | 5 | Done |
| BMTOS-75 | Multi-channel message delivery | 8 | Done |

---

## Phase 10 — Dashboard AI Assistant Enhancement

**Epic:** BMTOS-EPIC-10 | **Points:** 39 | **Status: COMPLETE**

SSE streaming, session persistence, JWT auth, RAG toggle, slash commands, voice input.

---

## Phase 11 — Training Pipeline + Claude Code Integration

**Epics:** BMTOS-EPIC-10b + BMTOS-EPIC-11 | **Points:** 81 | **Status: COMPLETE**

LoRA/QLoRA training module, training API, model export, MCP server, tool_use support.

---

## Phase 12 — AI Persona & Personality

**Epic:** BMTOS-EPIC-12 | **Points:** 24 | **Status: COMPLETE**

SOUL.md workspace files, persona assembler, preset library (coding/general/creative), dashboard editor.

---

## Hardware Target Matrix

| Feature | Apple Silicon ($800+) | Jetson Orin ($250) | RK3588 ($100-180) | Pi 5 + Hailo ($210) |
|---------|----------------------|-------------------|-------------------|---------------------|
| LLM Inference (7B) | 30-50 tok/s (CPU) | 15-22 tok/s (CUDA) | 4-6 tok/s (CPU) | 9.5 tok/s (1.5B only) |
| LoRA Training | 3B CPU ~20min | 1.5B CUDA ~30min | 1.5B CPU ~3hrs | <1B CPU ~6hrs |
| Accel | CPU NEON (no GPU) | 67 TOPS CUDA | 6 TOPS RKNN | 40 TOPS Hailo-10H |
| Max Model (16GB) | 13B Q4 | 7B Q4 | 7B Q4 | 7B Q4 (CPU) |
| Dashboard | Full | Full | Full | Full |
| Coding CLIs | All | All | All | All (lite models) |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to get involved. Check the [backlog](.scrum/backlog.json) for available stories.

## License

MIT License — Powered by [Bemind Technology Co., Ltd.](https://bemind.tech)
