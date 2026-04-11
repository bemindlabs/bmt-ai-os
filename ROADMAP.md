# BMT AI OS Roadmap

**Current Version:** `2026.4.11` | **Version Format:** `YYYY.M.D`

> 48 stories | 292 points | 6 epics | 8 phases | **48 stories done (292 pts, 100%)**

## Overview

```
Phase 1 ████████████████████████████████████████████████ ✅ 86 pts  Foundation
Phase 2 ████████████████████████████████████████████████ ✅ 35 pts  Providers
Phase 3 ████████████████████████████████████████████████ ✅ 36 pts  Coding Tools
Phase 4 ████████████████████████████████████████████████ ✅ 52 pts  Dashboard
Phase 5 ████████████████████████████████████████████████ ✅ 36 pts  Training
Phase 6 ████████████████████████████████████████████████ ✅ 29 pts  Hardware BSPs
Phase 7 ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░   26 pts  Tooling
Phase 8 ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░   TBD    Production
```

---

## Phase 1 — OS Foundation & Infrastructure

**Epic:** BMTOS-EPIC-3 | **Points:** 86 | **Priority:** Critical | **Status: COMPLETE**

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

**Milestone:** Bootable ARM64 image that boots on QEMU, starts containerd, launches Ollama + ChromaDB, and serves inference requests.

---

## Phase 2 — Multi-Provider LLM Support

**Epic:** BMTOS-EPIC-1 | **Points:** 35 | **Priority:** High | **Status: COMPLETE**

Abstraction layer for multiple LLM backends with local-first fallback chain.

| Story | Title | Pts | Status |
|-------|-------|-----|--------|
| BMTOS-6 | Design and implement LLM provider abstraction layer | 8 | Done |
| BMTOS-9 | Implement provider fallback chain and routing logic | 5 | Done |
| BMTOS-7a | Implement local LLM provider: vLLM | 5 | Done |
| BMTOS-7b | Implement local LLM provider: llama.cpp server | 5 | Done |
| BMTOS-8a | Implement cloud LLM provider: OpenAI | 3 | Done |
| BMTOS-8b | Implement cloud LLM provider: Anthropic (Claude) | 3 | Done |
| BMTOS-8c | Implement cloud LLM provider: Google Gemini | 3 | Done |
| BMTOS-8d | Implement cloud LLM providers: Mistral and Groq | 3 | Done |

**Milestone:** Any coding tool or RAG query can use any backend (Ollama, vLLM, llama.cpp, or cloud) via a unified interface. Automatic failover when a provider goes down.

---

## Phase 3 — AI Coding CLI & Agent Support

**Epic:** BMTOS-EPIC-2 | **Points:** 36 | **Priority:** High | **Status: COMPLETE**

Pre-installed, auto-configured AI coding tools for developers.

| Story | Title | Pts | Status |
|-------|-------|-----|--------|
| BMTOS-10 | Package coding CLIs (Claude Code, Aider, Continue, Tabby) | 8 | Done |
| BMTOS-11 | Auto-configure coding CLIs to use local LLM providers | 5 | Done |
| BMTOS-15 | Create coding model preset manager | 5 | Done |
| BMTOS-12 | Add IDE AI plugin support (Cursor, Copilot, Cody) | 5 | Done |
| BMTOS-13 | Add code agent support (SWE-agent, Codex CLI, Mentat) | 5 | Done |
| BMTOS-14 | Implement workspace and project context management | 8 | Done |

**Milestone:** Boot the OS, plug in a keyboard, run `aider` or `claude` — coding with local AI immediately. IDE plugins connect via `:8080` API.

---

## Phase 4 — Native Dashboard

**Epic:** BMTOS-EPIC-5 | **Points:** 52 | **Priority:** High | **Status: COMPLETE**

Web dashboard (Next.js + shadcn/ui) and terminal UI (Python Textual) for system management.

| Story | Title | Pts | Status |
|-------|-------|-----|--------|
| BMTOS-29 | Scaffold Next.js dashboard app with shadcn/ui | 8 | Done |
| BMTOS-30 | Build system overview dashboard page | 8 | Done |
| BMTOS-31 | Build model manager dashboard page | 5 | Done |
| BMTOS-32 | Build RAG console dashboard page | 8 | Done |
| BMTOS-33 | Build provider configuration dashboard page | 5 | Done |
| BMTOS-34 | Build logs viewer dashboard page | 5 | Done |
| BMTOS-35 | Build coding tools status dashboard page | 5 | Done |
| BMTOS-36 | Build terminal UI (TUI) dashboard with Textual | 8 | Done |

**Milestone:** Open `http://device-ip:9090` — see system health, manage models, query RAG, configure providers. Or SSH in and run `bmt_ai_os tui`.

---

## Phase 5 — On-Device AI Training & Fine-Tuning

**Epic:** BMTOS-EPIC-6 | **Points:** 36 | **Priority:** Medium | **Status: COMPLETE**

LoRA/QLoRA fine-tuning pipeline for edge hardware.

| Story | Title | Pts | Status |
|-------|-------|-----|--------|
| BMTOS-37 | Install PyTorch and ML training framework for ARM64 | 8 | Done |
| BMTOS-38 | Implement LoRA/QLoRA fine-tuning pipeline | 8 | Done |
| BMTOS-39 | Build training data preparation tools | 5 | Done |
| BMTOS-40 | Add Jupyter Notebook server for interactive training | 5 | Done |
| BMTOS-41 | Implement training monitoring and TensorBoard integration | 5 | Done |
| BMTOS-42 | Build model export and deployment pipeline | 5 | Done |

**Milestone:** Prepare data → fine-tune a 1.5B model with LoRA on Jetson → export to GGUF → serve via Ollama. Full loop on one device.

---

## Phase 6 — Hardware Board Support Packages

**Epic:** BMTOS-EPIC-4 | **Points:** 29 | **Priority:** High | **Status: COMPLETE**

Board-specific support for Tier 1 hardware targets.

| Story | Title | Pts | Status |
|-------|-------|-----|--------|
| BMTOS-43 | Add Apple Silicon BSP (Asahi Linux, CPU-first) | 8 | Done |
| BMTOS-26 | Add Jetson Orin board support package | 8 | Done |
| BMTOS-27 | Add Rockchip RK3588 board support package | 8 | Done |
| BMTOS-28 | Add Raspberry Pi 5 + Hailo AI HAT+ 2 board support package | 5 | Done |

**Milestone:** Flash BMT AI OS on any Tier 1 board. Apple Silicon leads with fastest CPU inference (30-50 tok/s). NPU/GPU acceleration on other boards. Performance benchmarks published.

---

## Phase 7 — Tooling & Infrastructure

**Standalone stories** | **Points:** 26 | **Priority:** Medium

Cross-cutting tools used by all epics.

| Story | Title | Pts | Priority |
|-------|-------|-----|----------|
| BMTOS-22 | Build BMT AI OS CLI tool (bmt_ai_os command) | 8 | Medium |
| BMTOS-23 | Expose external REST API for AI stack access | 5 | Medium |
| BMTOS-24 | Build centralized logging and system metrics | 5 | Medium |
| BMTOS-25 | Implement OS update mechanism with rollback | 8 | Low |

**Milestone:** `bmt_ai_os status`, `bmt_ai_os models install`, `bmt_ai_os update` — one CLI for everything. OTA updates with A/B rollback.

---

## Phase 8 — Production Hardening

**Not yet scoped** | **Priority:** Future

- Fleet management for multi-device deployments
- Advanced security hardening (AppArmor/seccomp profiles)
- Performance optimization and benchmarking suite
- Documentation site and developer portal
- Community plugin/extension system
- Multi-user support with access control

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
