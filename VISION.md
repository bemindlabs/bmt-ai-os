# BMT AI OS Vision

## What

An open-source, ARM64-native operating system where AI is a kernel-level service — not an app you install. Boot a $100 board and get local LLM inference, RAG, AI coding tools, and on-device model training running in seconds, fully offline.

## Why

There is no vendor-neutral, bootable OS that ships containerized LLM inference + RAG + coding tools + training as first-class system services on affordable ARM64 hardware.

The closest alternatives all fall short:

| Project            | Gap                                                                  |
| ------------------ | -------------------------------------------------------------------- |
| RHEL AI bootc      | AI OS as container image, but x86/enterprise, $$$$                   |
| NVIDIA JetPack     | ARM64 AI, but locked to NVIDIA hardware ($250-2000)                  |
| Balena OS          | Container OS for IoT fleets, zero AI integration                     |
| Umbrel OS          | Self-hosted apps with Ollama, but x86-focused, AI is an afterthought |
| Ollama / LM Studio | Great inference tools, but not an operating system                   |

BMT AI OS fills the gap: **the AI-native OS for $100-250 ARM64 hardware.**

## Who

- Developers who want a private, local AI coding environment
- Teams in regulated industries (finance, healthcare, defense) that can't send code to cloud APIs
- Edge/IoT builders deploying AI at the edge without cloud dependencies
- ML engineers who want to fine-tune models on local data without cloud GPU costs
- Hobbyists and researchers who want a turnkey local AI lab

## Hardware Targets

### Tier 1 — Primary (optimize first)

| Hardware                                      | NPU/GPU           | LLM Performance      | Training              | Price    |
| --------------------------------------------- | ----------------- | -------------------- | --------------------- | -------- |
| NVIDIA Jetson Orin Nano Super                 | 67 TOPS CUDA      | 7B @ 15-22 tok/s     | LoRA 1.5B, QLoRA 3B   | ~$250    |
| Raspberry Pi 5 + AI HAT+ 2                    | 40 TOPS Hailo-10H | 1.5B @ 9.5 tok/s     | LoRA <1B (CPU)        | ~$210    |
| Rockchip RK3588 boards (Orange Pi 5, ROCK 5B) | 6 TOPS RKNN       | 7B @ 4-6 tok/s (CPU) | LoRA 1.5B (CPU, slow) | $100-180 |

### Tier 2 — Future

| Hardware                        | Notes                                    |
| ------------------------------- | ---------------------------------------- |
| Apple Silicon (via Asahi Linux) | Best raw performance, closed ecosystem   |
| Raspberry Pi 5 (CPU-only)       | Baseline compatibility, 1-3B models only |

### Avoid

- **Qualcomm Snapdragon X**: Linux NPU support is dead (DSP headers not open-sourced)
- **MediaTek Dimensity**: No Linux SBC path, Android-only

## Full Architecture

```
┌───────────────────────────────────────────────────┐
│                   BMT AI OS                       │
├───────────────────────────────────────────────────┤
│  Dashboard (:9090)  │  TUI (bmt-ai-os tui)        │
│  Next.js+shadcn/ui  │  Python Textual             │
├───────────────────────────────────────────────────┤
│  Coding CLIs        │  IDE Plugins  │  Code Agents│
│  Claude Code, Aider │  Cursor       │  SWE-agent  │
│  Continue, Tabby    │  Copilot,Cody │  Codex CLI  │
├───────────────────────────────────────────────────┤
│  Training Stack     │  RAG Pipeline │  REST API   │
│  PyTorch + LoRA     │  Ingest→Embed │  :8080      │
│  Jupyter (:8888)    │  →ChromaDB    │  OpenAI-    │
│  TensorBoard (:6006)│  →Query→LLM   │  compatible │
├───────────────────────────────────────────────────┤
│  Workspace Context (codebase → ChromaDB → LLM)    │
├───────────────────────────────────────────────────┤
│         Provider Abstraction Layer                │
│  chat() │ embed() │ list_models() │ fallback()    │
├───────────────────┬───────────────────────────────┤
│   Local (primary) │     Cloud (fallback)          │
│   Ollama (:11434) │     OpenAI                    │
│   vLLM            │     Anthropic (Claude)        │
│   llama.cpp       │     Google (Gemini)           │
│                   │     Mistral / Groq            │
├───────────────────┴───────────────────────────────┤
│  Container Runtime (containerd) + Docker CLI      │
│  NPU/GPU passthrough (CUDA, RKNN, HailoRT)        │
├───────────────────────────────────────────────────┤
│  Linux Kernel (Buildroot, ARM64/aarch64, OpenRC)  │
│  37 packages: Python, Node.js, PyTorch, Git, GCC  │
└───────────────────────────────────────────────────┘
```

## Port Map

| Port  | Service                              |
| ----- | ------------------------------------ |
| 6006  | TensorBoard (training visualization) |
| 8000  | ChromaDB (vector database)           |
| 8080  | OpenAI-compatible API (IDE plugins)  |
| 8888  | Jupyter Lab (interactive training)   |
| 9090  | Dashboard (Next.js + shadcn/ui)      |
| 11434 | Ollama (LLM inference)               |

## Coding Tools (pre-installed, auto-configured)

### AI Coding CLIs

- **Claude Code** — via Ollama Anthropic-compatible API (v0.14+)
- **Aider** — best CLI coding assistant (72.4% SWE-bench with Qwen3.5-27B)
- **Continue.dev** — best IDE extension, native Ollama support
- **Tabby** — self-hosted Copilot alternative (32k GitHub stars)
- **Open Interpreter** — natural language system interaction

### IDE Plugin Support

- **Cursor / Copilot / Cody** — via OpenAI-compatible API endpoint at :8080

### Code Agents

- **SWE-agent / Codex CLI / Mentat** — sandboxed autonomous coding agents

## On-Device Training

LoRA/QLoRA fine-tuning pipeline for edge hardware:

```
Prepare Data → Train (LoRA) → Export → Serve
bmt-ai-os      bmt-ai-os     bmt-ai-os   ollama
data prepare   train          model export run
```

| Capability     | Jetson Orin (8GB) | RK3588 (16GB) | Pi 5 (8GB)    |
| -------------- | ----------------- | ------------- | ------------- |
| LoRA 1.5B      | CUDA, ~30 min     | CPU, ~3 hours | CPU, ~6 hours |
| QLoRA 3B       | CUDA, ~1 hour     | Not feasible  | Not feasible  |
| Export to GGUF | ~5 min            | ~5 min        | ~5 min        |

## Default Models

Ship coding-optimized models, auto-selected by device capability:

| Preset     | Model                                    | RAM    | Target                |
| ---------- | ---------------------------------------- | ------ | --------------------- |
| `lite`     | Qwen3.5-9B Q4                            | ~6 GB  | Pi 5, RK3588 (8GB)    |
| `standard` | Qwen2.5-Coder-7B Q4 + Qwen3-Embedding-8B | ~8 GB  | RK3588 (16GB), Jetson |
| `full`     | Qwen3.5-27B Q4 + Qwen3-Embedding-8B      | ~18 GB | Jetson, RK3588 (32GB) |

## Key Principles

1. **Local-first** — everything works offline after initial setup. Cloud is optional fallback, never required.
2. **Boot to AI** — LLM inference, vector DB, and RAG are system services that start on boot, not apps you install.
3. **Train locally** — fine-tune models on your own data without cloud GPU costs or data leaving your device.
4. **Hardware abstraction** — same experience on Jetson, Pi, or RK3588. NPU acceleration when available, CPU fallback always.
5. **Container-native** — all AI services run isolated in containers. The controller manages lifecycle, health, and recovery.
6. **Developer-centric** — coding tools are first-class citizens. Index your codebase, query with RAG, code with AI — all locally.
7. **Open and vendor-neutral** — no hardware lock-in, no cloud lock-in, no vendor lock-in. MIT licensed.

## Competitive Moat

The combination that no one else offers:

- **Bootable OS** (not just a tool) — unlike Ollama, LM Studio, Jan.ai
- **ARM64-native** (not x86-first) — unlike RHEL AI, Umbrel
- **Vendor-neutral** (not hardware-locked) — unlike JetPack
- **AI as system service** (not an app) — unlike Balena OS, Umbrel
- **On-device training** (not just inference) — unlike everything else in this category
- **Coding tools pre-configured** — unlike everything else
- **Native dashboard** (web + TUI) — unlike CLI-only alternatives
- **Affordable target hardware** ($100-250) — unlike Apple Silicon, enterprise GPUs

## Market Context (2026)

- 84% of developers use AI tools, but only 29% trust them — privacy drives local adoption
- 52M monthly Ollama downloads — local inference is mainstream
- Qwen3.5-27B hits 72.4% SWE-bench — local models rival cloud for coding
- 7B models at 20+ tok/s is the "good enough" threshold — achievable on Tier 1 hardware
- MoE models (Qwen3.5-35B-A3B, Gemma 4 26B-A4B) activate only 3-4B params — big model quality on small hardware
- NPU adoption accelerating: Hailo-10H (40 TOPS for $130), Jetson Orin Super (67 TOPS for $250)

## Roadmap

### Phase 1 — Foundation (BMTOS-EPIC-3, 73 pts)

Bootable ARM64 image, OpenRC init, containerd, networking, security, CI/CD, filesystem layout

### Phase 2 — AI Stack (26 pts)

Ollama + ChromaDB as system services, controller orchestration, RAG pipeline

### Phase 3 — Provider Layer (BMTOS-EPIC-1, 35 pts)

Multi-provider abstraction (Ollama, vLLM, llama.cpp), cloud fallback chain, NPU passthrough

### Phase 4 — Developer Experience (BMTOS-EPIC-2, 36 pts)

Pre-installed coding CLIs, IDE plugin API, codebase RAG, model presets

### Phase 5 — Dashboard (BMTOS-EPIC-5, 52 pts)

Next.js + shadcn/ui web dashboard, Python Textual TUI, system monitoring

### Phase 6 — Training (BMTOS-EPIC-6, 36 pts)

PyTorch ARM64, LoRA/QLoRA fine-tuning, data prep, Jupyter, TensorBoard, model export

### Phase 7 — Hardware (BMTOS-EPIC-4, 21 pts)

Board support packages: Jetson Orin (CUDA), RK3588 (RKNN), Pi 5 + Hailo

### Phase 8 — Production

OTA updates with rollback, fleet management, security hardening

## License

MIT License — Powered by [Bemind Technology Co., Ltd.](https://bemind.tech)
