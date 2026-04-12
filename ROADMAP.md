# BMT AI OS Roadmap

**Current Version:** `2026.4.12` | **Version Format:** `YYYY.M.D`

> 177 stories | 965 points | 23 epics | **177 stories done (965 pts, 100%)**

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
Phase 13 ████████████████████████████████████████████████ ✅  25 pts  Dashboard Integration
Phase 14 ████████████████████████████████████████████████ ✅  55 pts  AI Workspace
Phase 15 ████████████████████████████████████████████████ ✅  22 pts  Dynamic Providers
Phase 16 ████████████████████████████████████████████████ ✅  22 pts  Web SSH Terminal
Phase 17 ████████████████████████████████████████████████ ✅  21 pts  Enhanced Providers
Phase 18 ████████████████████████████████████████████████ ✅  39 pts  Knowledge Vaults
Phase 19 ████████████████████████████████████████████████ ✅  16 pts  IDE Terminal
Phase 20 ████████████████████████████████████████████████ ✅  21 pts  AI Coding & Models
Phase 21 ████████████████████████████████████████████████ ✅  26 pts  AI Coding Workflow
Phase 22 ████████████████████████████████████████████████ ✅  47 pts  Pi 5 OS Image
Phase 23 ████████████████████████████████████████████████ ✅  47 pts  AI DLC & Custom OS Builder
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

## Phase 13 — Dashboard Integration Sprint

**Epic:** BMTOS-EPIC-13 | **Points:** 25 | **Status: COMPLETE**

Wire all dashboard components into live UI: SSE streaming, session sidebar, slash commands, voice/file input, RAG toggle, source cards, persona editor, agents page.

| Story | Title | Pts | Status |
|-------|-------|-----|--------|
| BMTOS-101 | Wire SSE streaming into chat-interface.tsx | 3 | Done |
| BMTOS-102 | Wire session sidebar into chat page | 3 | Done |
| BMTOS-103 | Wire slash commands into chat input | 3 | Done |
| BMTOS-104 | Wire voice input and file drop into chat | 3 | Done |
| BMTOS-105 | Wire RAG toggle and source cards into chat | 3 | Done |
| BMTOS-106 | Create persona editor component for settings | 3 | Done |
| BMTOS-107 | Add persona CLI commands (set/get/list) | 2 | Done |
| BMTOS-108 | Add /agents page for multi-agent management | 3 | Done |
| BMTOS-109 | Wire auth headers into all dashboard API calls | 2 | Done |

---

## Phase 14 — AI Workspace

**Epic:** BMTOS-EPIC-14 | **Points:** 55 | **Status: COMPLETE**

Transform dashboard into full AI workspace: 3-panel resizable layout, tabbed work areas, terminal emulator (xterm.js), Monaco code editor, file manager, training studio, fleet dashboard.

| Story | Title | Pts | Status |
|-------|-------|-----|--------|
| BMTOS-110 | Workspace 3-panel resizable layout | 8 | Done |
| BMTOS-111 | Tabbed work area with split view | 5 | Done |
| BMTOS-112 | RAG knowledge base manager | 5 | Done |
| BMTOS-113 | WebSocket notification center | 5 | Done |
| BMTOS-114 | Terminal emulator (xterm.js) | 8 | Done |
| BMTOS-115 | Code editor (Monaco) | 8 | Done |
| BMTOS-116 | File manager with tree view | 5 | Done |
| BMTOS-117 | Training studio with live metrics | 5 | Done |
| BMTOS-118 | Fleet dashboard with device grid | 3 | Done |
| BMTOS-119 | Theme toggle and layout persistence | 3 | Done |

---

## Phase 15 — Dynamic Provider Configuration

**Epic:** BMTOS-EPIC-15 | **Points:** 22 | **Status: COMPLETE**

Provider CRUD API, add/edit/delete UI, connection testing, fallback chain drag-drop, per-provider model lists.

| Story | Title | Pts | Status |
|-------|-------|-----|--------|
| BMTOS-120 | Provider CRUD API (register/update/delete) | 5 | Done |
| BMTOS-121 | Add Provider form in dashboard | 3 | Done |
| BMTOS-122 | Per-provider edit/delete/toggle UI | 3 | Done |
| BMTOS-123 | Test Connection button | 3 | Done |
| BMTOS-124 | Fallback chain drag-drop configurator | 5 | Done |
| BMTOS-125 | Provider model list per provider | 3 | Done |

---

## Phase 16 — Web SSH Terminal

**Epic:** BMTOS-EPIC-16 | **Points:** 22 | **Status: COMPLETE**

SSH to fleet devices from the dashboard via WebSocket proxy with key management and multi-tab terminals.

| Story | Title | Pts | Status |
|-------|-------|-----|--------|
| BMTOS-126 | SSH WebSocket proxy backend (paramiko) | 8 | Done |
| BMTOS-127 | Terminal SSH mode with connection form | 5 | Done |
| BMTOS-128 | Fleet device Connect button opens SSH | 3 | Done |
| BMTOS-129 | SSH key management API and UI | 3 | Done |
| BMTOS-130 | Multi-tab terminal with split panes | 3 | Done |

---

## Phase 17 — Enhanced Provider Management

**Epic:** BMTOS-EPIC-17 | **Points:** 21 | **Status: COMPLETE**

Setup wizards, rich model catalog, provider health dashboard, multi-credential profiles, auto-discovery.

| Story | Title | Pts | Status |
|-------|-------|-----|--------|
| BMTOS-131 | Guided provider setup wizard (multi-step) | 5 | Done |
| BMTOS-132 | Rich model catalog with cost and context info | 5 | Done |
| BMTOS-133 | Provider health dashboard with expiry tracking | 5 | Done |
| BMTOS-134 | Multi-credential profiles per provider | 3 | Done |
| BMTOS-135 | Provider auto-discovery (scan local ports) | 3 | Done |

---

## Phase 18 — Multi-Agent Persona Knowledge Vaults

**Epic:** BMTOS-EPIC-18 | **Points:** 39 | **Status: COMPLETE**

Per-persona knowledge bases with Obsidian-compatible markdown vaults, wiki-links, auto-ingest RAG, graph view.

| Story | Title | Pts | Status |
|-------|-------|-----|--------|
| BMTOS-136 | Per-persona workspace directories and RAG collections | 8 | Done |
| BMTOS-137 | Obsidian-compatible markdown parser | 5 | Done |
| BMTOS-138 | Persona-scoped Knowledge & Files tab | 5 | Done |
| BMTOS-139 | Obsidian vault note editor with live preview | 5 | Done |
| BMTOS-140 | Auto-ingest persona vault into RAG on file changes | 3 | Done |
| BMTOS-141 | Chat RAG context auto-scoped to active persona | 5 | Done |
| BMTOS-142 | Vault graph view and backlinks panel | 5 | Done |
| BMTOS-147 | Workspace directory structure and auto-scaffold | 3 | Done |

---

## Phase 19 — Integrated Editor Terminal (IDE Experience)

**Epic:** BMTOS-EPIC-19 | **Points:** 16 | **Status: COMPLETE**

Embedded terminal in Code Editor with tmux session management, auto-connect, drag-resize.

| Story | Title | Pts | Status |
|-------|-------|-----|--------|
| BMTOS-143 | Embedded terminal panel in Code Editor | 5 | Done |
| BMTOS-144 | tmux session management via WebSocket | 5 | Done |
| BMTOS-145 | Terminal auto-connects on editor page load | 3 | Done |
| BMTOS-146 | Terminal panel resize with drag handle | 3 | Done |

---

## Phase 20 — Multi-Provider AI Coding & Model Manager

**Epic:** BMTOS-EPIC-20 | **Points:** 21 | **Status: COMPLETE**

Claude/Codex/Gemini in Code Editor, enhanced model catalog with probing, inline API key setup, A/B comparison.

| Story | Title | Pts | Status |
|-------|-------|-----|--------|
| BMTOS-148 | Multi-provider AI coding integration | 8 | Done |
| BMTOS-149 | Enhanced Model Manager with catalog and probing | 5 | Done |
| BMTOS-150 | Provider API key management in Code Editor | 3 | Done |
| BMTOS-151 | Model comparison and A/B prompt testing | 5 | Done |

---

## Phase 21 — AI Coding Workflow (Claw-Code Inspired)

**Epic:** BMTOS-EPIC-21 | **Points:** 26 | **Status: COMPLETE**

IDE-grade coding workflow: diff preview, slash commands (/fix, /refactor, /explain, /test), tool use, multi-file edits, git integration.

| Story | Title | Pts | Status |
|-------|-------|-----|--------|
| BMTOS-152 | Diff preview before applying AI-generated code | 5 | Done |
| BMTOS-153 | Slash commands in AI prompt | 5 | Done |
| BMTOS-154 | AI tool use: read files, run commands, search code | 8 | Done |
| BMTOS-155 | Multi-file edit workflow from AI prompt | 5 | Done |
| BMTOS-156 | Git integration in Code Editor | 3 | Done |

---

## Phase 22 — Raspberry Pi 5 Bootable OS Image

**Epic:** BMTOS-EPIC-22 | **Points:** 47 | **Status: COMPLETE**

Produce a flashable SD card image for Raspberry Pi 5 + AI HAT+ 2 (Hailo-10H, 40 TOPS). Boot to AI in under 90 seconds.

| Story | Title | Pts | Status |
|-------|-------|-----|--------|
| BMTOS-157 | Genimage partition layout for Pi 5 SD card | 8 | Done |
| BMTOS-158 | RPi 5 firmware and bootloader staging | 5 | Done |
| BMTOS-159 | Pi 5 boot config (config.txt) with PCIe Gen3 | 3 | Done |
| BMTOS-160 | Device tree overlays for AI HAT+ 2 | 5 | Done |
| BMTOS-161 | First-boot auto-setup OpenRC hook | 8 | Done |
| BMTOS-162 | Lite AI stack auto-start for Pi 5 (8GB) | 5 | Done |
| BMTOS-163 | SD card flash tooling and documentation | 3 | Done |
| BMTOS-164 | QEMU Pi 5 image validation in CI | 5 | Done |
| BMTOS-165 | Pi 5 image size optimization and compression | 5 | Done |

---

## Phase 23 — AI DLC & Custom OS Builder

**Epic:** BMTOS-EPIC-23 | **Points:** 47 | **Status: COMPLETE**

Downloadable content system: selectable AI tool packages, hardware target selection, build profiles, TUI wizard, and dashboard image builder.

| Story | Title | Pts | Status |
|-------|-------|-----|--------|
| BMTOS-166 | AI tool package registry (YAML) | 8 | Done |
| BMTOS-167 | Build profile schema and presets | 5 | Done |
| BMTOS-168 | TUI wizard for custom image builds | 8 | Done |
| BMTOS-169 | Dashboard /image-builder page | 8 | Done |
| BMTOS-170 | Controller API for build profiles | 5 | Done |
| BMTOS-171 | Build pipeline --profile integration | 8 | Done |
| BMTOS-172 | Pre-configured presets (minimal/developer/full) | 5 | Done |

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
