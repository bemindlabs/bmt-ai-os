# Security Report �� BMT AI OS v2026.4.11

**Date:** 2026-04-11
**Scanner versions:** Trivy 0.69.1, Semgrep

## Summary

| Check | Status | Details |
|-------|--------|---------|
| Docker Image (Trivy) | WARN | 0 critical, 10 high |
| Filesystem Deps (Trivy) | PASS | 0 vulnerabilities |
| IaC Config (Trivy) | PASS | 0 misconfigurations |
| SAST (Semgrep) | PASS | 0 findings |
| Lint (Ruff) | PASS | clean |
| Tests (Pytest) | PASS | 295 passed, 0 failed |

## Image Vulnerabilities

Total: 10 (HIGH: 10, CRITICAL: 0)

┌─────────────────────────┬────────────────┬──────────┬──────────┬───────────────────┬─────────────────┬─────────────────────────────────────────────────────────────┐
│         Library         │ Vulnerability  │ Severity │  Status  │ Installed Version │  Fixed Version  │                            Title                            │
├─────────────────────────┼────────────────┼──────────┼──────────┼───────────────────┼─────────────────┼─────────────────────────────────────────────────────────────┤
│ libncursesw6            │ CVE-2025-69720 │ HIGH     │ affected │ 6.5+20250216-2    │                 │ ncurses: ncurses: Buffer overflow vulnerability may lead to │
│                         │                │          │          │                   │                 │ arbitrary code execution.                                   │
│                         │                │          │          │                   │                 │ https://avd.aquasec.com/nvd/cve-2025-69720                  │
├─────────────────────────┼────────────────┤          │          ├───────────────────┼─────────────────┼─────────────────────────────────────────────────────────────┤
│ libnghttp2-14           │ CVE-2026-27135 │          │          │ 1.64.0-1.1        │                 │ nghttp2: nghttp2: Denial of Service via malformed HTTP/2    │
│                         │                │          │          │                   │                 │ frames after session termination...                         │
│                         │                │          │          │                   │                 │ https://avd.aquasec.com/nvd/cve-2026-27135                  │
├─────────────────────────┼────────────────┤          ├──────────┼───────────────────┼─────────────────┼─────────────────────────────────────────────────────────────┤
│ libssl3t64              │ CVE-2026-28390 │          │ fixed    │ 3.5.5-1~deb13u1   │ 3.5.5-1~deb13u2 │ openssl: OpenSSL: Denial of Service due to NULL pointer     │
│                         │                │          │          │                   │                 │ dereference in CMS...                                       │
│                         │                │          │          │                   │                 │ https://avd.aquasec.com/nvd/cve-2026-28390                  │
├─────────────────────────┼────────────────┤          ├──────────┼───────────────────┼─────────────────┼─────────────────────────────────────────────────────────────┤
│ libsystemd0             │ CVE-2026-29111 │          │ affected │ 257.9-1~deb13u1   │                 │ systemd: systemd: Arbitrary code execution or Denial of     │
│                         │                │          │          │                   │                 │ Service via spurious IPC...                                 │
│                         │                │          │          │                   │                 │ https://avd.aquasec.com/nvd/cve-2026-29111                  │
├─────────────────────────┼────────────────┤          │          ├───────────────────┼─────────────────┼─────────────────────────────────────────────────────────────┤
│ libtinfo6               │ CVE-2025-69720 │          │          │ 6.5+20250216-2    │                 │ ncurses: ncurses: Buffer overflow vulnerability may lead to │
│                         │                │          │          │                   │                 │ arbitrary code execution.                                   │
│                         │                │          │          │                   │                 │ https://avd.aquasec.com/nvd/cve-2025-69720                  │
├─────────────────────────┼────────────────┤          │          ├───────────────────┼─────────────────┼─────────────────────────────────────────────────────────────┤
│ libudev1                │ CVE-2026-29111 │          │          │ 257.9-1~deb13u1   │                 │ systemd: systemd: Arbitrary code execution or Denial of     │
│                         │                │          │          │                   │                 │ Service via spurious IPC...                                 │
│                         │                │          │          │                   │                 │ https://avd.aquasec.com/nvd/cve-2026-29111                  │
├─────────────────────────┼────────────────┤          │          ├───────────────────┼─────────────────┼─────────────────────────────────────────────────────────────┤
│ ncurses-base            │ CVE-2025-69720 │          │          │ 6.5+20250216-2    │                 │ ncurses: ncurses: Buffer overflow vulnerability may lead to │

## Release Gate

**PASS** — Safe to release v2026.4.11
