---
name: scan
description: Run security scans (trivy + semgrep + ruff)
argument-hint: "[image|code|all]"
user-invocable: true
allowed-tools: "Bash Read Write"
---

# Security Scan

Run security scans on the project.

## Commands

Parse `$ARGUMENTS`:

- **image**: `trivy image --severity HIGH,CRITICAL bemindlab/bmt-ai-os:latest`
- **code**: `semgrep scan --config "p/python" --config "p/owasp-top-ten" --severity ERROR,WARNING bmt_ai_os/`
- **all** (default): Run full security report via `./scripts/security-report.sh`

## Quick Status

Ruff: !`uvx ruff check bmt_ai_os/ tests/ 2>&1 | tail -1`
Tests: !`python3 -m pytest tests/unit/ tests/smoke/ -q --tb=no 2>&1 | tail -1`
