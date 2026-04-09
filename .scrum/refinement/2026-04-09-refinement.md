# Backlog Refinement Session — 2026-04-09

**Project:** BMT AI OS (BMTOS)
**Items Reviewed:** 5
**Total Backlog Points:** 47

---

## Readiness Assessment

| ID | Title | Pts | Priority | Description | AC | Estimate | Dependencies | Ready? |
|----|-------|-----|----------|-------------|-----|----------|--------------|--------|
| BMTOS-1 | Finalize ARM64 Buildroot kernel config | 8 | critical | Yes | 3 criteria | Yes | None | **YES** |
| BMTOS-2 | Configure containerd with NPU passthrough | 13 | high | Yes | 3 criteria | Yes | BMTOS-1 | **NEEDS WORK** |
| BMTOS-3 | Deploy Ollama + ChromaDB AI stack | 5 | high | Yes | 3 criteria | Yes | BMTOS-2 | **YES** |
| BMTOS-4 | Implement controller orchestration | 8 | high | Yes | 3 criteria | Yes | BMTOS-3 | **YES** |
| BMTOS-5 | Build local RAG pipeline | 13 | medium | Yes | 4 criteria | Yes | BMTOS-3, BMTOS-4 | **NEEDS WORK** |

---

## Item-by-Item Analysis

### BMTOS-1 — Finalize ARM64 Buildroot kernel configuration
**Status:** READY
- Description is clear and actionable
- 3 acceptance criteria cover boot, networking, and init
- 8 points is appropriate for kernel config work
- No dependencies — can start immediately
- **INVEST check:** Independent ✓ | Negotiable ✓ | Valuable ✓ | Estimable ✓ | Small ✓ | Testable ✓

### BMTOS-2 — Configure containerd runtime with GPU/NPU passthrough
**Status:** NEEDS REFINEMENT
- **Issue 1: Size (13 pts)** — Consider splitting into two stories:
  - (a) Basic containerd setup and boot integration (5 pts)
  - (b) GPU/NPU device passthrough configuration (8 pts)
- **Issue 2: Missing dependency** — Requires BMTOS-1 (bootable kernel) before containerd can be configured on-device
- **Issue 3: Acceptance criteria gap** — Missing criteria for: specific NPU hardware target, fallback behavior when no NPU present
- **Recommendation:** Split this story and add hardware target specifics

### BMTOS-3 — Deploy Ollama + ChromaDB AI stack via Docker Compose
**Status:** READY
- Clear scope — Docker Compose is already scaffolded
- 5 points appropriate for hardening existing config
- Acceptance criteria cover service availability and resilience
- **Minor suggestion:** Add criteria for volume persistence (model data, vector DB data)
- **INVEST check:** Independent ✓ | Negotiable ✓ | Valuable ✓ | Estimable ✓ | Small ✓ | Testable ✓

### BMTOS-4 — Implement BMT AI OS controller for container orchestration
**Status:** READY
- Controller prototype exists (`controller/main.py`)
- 8 points reasonable for lifecycle management + health checks
- Acceptance criteria are testable
- **Minor suggestion:** Clarify which containers the controller manages (all Docker containers or only AI stack?)
- **INVEST check:** Independent ✓ | Negotiable ✓ | Valuable ✓ | Estimable ✓ | Small ✓ | Testable ✓

### BMTOS-5 — Build local RAG pipeline integration
**Status:** NEEDS REFINEMENT
- **Issue 1: Size (13 pts)** — Consider splitting:
  - (a) Document ingestion pipeline into ChromaDB (5 pts)
  - (b) Query retrieval + Ollama augmented generation (8 pts)
- **Issue 2: Performance criteria vague** — "under 2 seconds" needs context: what hardware? what document corpus size? what model?
- **Issue 3: Missing criteria** — No criteria for: supported document formats, embedding model selection, chunk strategy
- **Dependency:** Blocked by BMTOS-3 (Ollama + ChromaDB must be running) and BMTOS-4 (controller manages services)
- **Recommendation:** Split and add specificity to performance targets

---

## Dependency Map

```
BMTOS-1 (Kernel)
    └── BMTOS-2 (Containerd + NPU)
         └── BMTOS-3 (AI Stack)
              ├── BMTOS-4 (Controller)
              └── BMTOS-5 (RAG Pipeline)
                   └── depends on BMTOS-4
```

---

## Refinement Actions

- [ ] **BMTOS-2:** Split into basic containerd (5 pts) + NPU passthrough (8 pts)
- [ ] **BMTOS-2:** Specify target NPU hardware (e.g., Rockchip NPU, Mali GPU)
- [ ] **BMTOS-2:** Add fallback criteria for non-NPU environments
- [ ] **BMTOS-3:** Add acceptance criterion for persistent volumes
- [ ] **BMTOS-4:** Clarify scope — AI-stack containers only or system-wide?
- [ ] **BMTOS-5:** Split into ingestion (5 pts) + query/generation (8 pts)
- [ ] **BMTOS-5:** Define hardware baseline and corpus size for latency target
- [ ] **BMTOS-5:** Add criteria for document format support and embedding strategy
- [ ] Add dependency tracking to backlog items

---

## Sprint Readiness Summary

**Ready for Sprint 1:** BMTOS-1 (8 pts), BMTOS-3 (5 pts), BMTOS-4 (8 pts) = **21 pts**
**Need refinement before sprint:** BMTOS-2 (13 pts), BMTOS-5 (13 pts) = **26 pts**

> **Recommendation:** Start Sprint 1 with BMTOS-1 + BMTOS-3 as the core focus (13 pts).
> BMTOS-4 can be included if capacity allows (total 21 pts).
> Refine BMTOS-2 and BMTOS-5 during Sprint 1 for Sprint 2.
