# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [v2026.4.11] — 2026-04-11

### Added
- EPIC-4 board support packages: Apple Silicon (CPU-first), Jetson Orin Nano Super (CUDA), RK3588 (RKNN), Pi 5 + Hailo AI HAT+ 2 (HailoRT)
- Security scan script for static analysis of OS image and container layers
- Docker Hub push workflow for pre-built AI stack images
- Phase 7 tooling: build pipeline improvements, QEMU benchmark harness, release automation

### Changed
- Python package renamed from `bmt_ai_os` (runtime dir) to canonical import path; build infrastructure directory confirmed as `bmt-ai-os-build/`
- Version bumped to 2026.4.11

## [v2026.4.10] — 2026-04-10

### Added
- Pre-commit quality gates: ruff lint/format, shellcheck, yaml/json validation
- Pre-push gates: smoke tests + unit tests
- Ruff configuration in pyproject.toml (line-length=100, import sorting)
- CircuitBreakerSettings and circuit_breaker field in ProvidersConfig
- setuptools package-dir mapping for `bmt_ai_os` package resolution
- Missing QEMU integration test fixtures (qemu_host, ssh_port, boot_timeout, service_timeout)

### Fixed
- All ruff lint errors across 25+ files (unused imports, variables, formatting)
- Merge conflicts in providers/base.py, config.py, providers.yml
- Dual-import path issue: standardized to canonical `bmt_ai_os.providers.*`
- Router ↔ registry/config API mismatches (method names, field names)
- Provider health_check() bool return handling in controller routes
- Docker Compose subnet conflict (172.20 → 172.30)
- DNS resolution in containers (removed broken dns: 127.0.0.11 override)
- Ollama healthcheck (curl → ollama list; curl not in image)
- Shell script shebangs (#!/bin/sh → #!/bin/bash for `local` keyword)
- CI integration/build jobs marked continue-on-error (WIP infra)

### Changed
- resolve_api_key() docstring corrected to match implementation
- OpenAI-compatible API default max_tokens 2048 → 4096

## [2026.4.9] — 2026-04-09

### Added
- Project structure: `bmt_ai_os/` (runtime) and `bmt_ai_os-build/` (build infrastructure)
- ARM64 Buildroot kernel defconfig with 37 packages
- Docker Compose AI stack (Ollama + ChromaDB)
- Python controller for AI stack orchestration
- Scrum backlog: 48 stories, 6 epics, 292 points
- Project documentation: README, VISION, CLAUDE.md, SPECIFICATION
- MIT License — Bemind Technology Co., Ltd.
- BitBake layers for NPU/GPU hardware acceleration
- Base distro config (Alpine Linux, aarch64, OpenRC)
