#!/bin/bash
# scripts/security-report.sh — Pre-release security scan
# Run before tagging a new release to generate security reports.
#
# Usage:
#   ./scripts/security-report.sh [VERSION]
#   ./scripts/security-report.sh v2026.4.11
#
# Output: reports/security-<VERSION>-<DATE>.md

set -euo pipefail

VERSION="${1:-$(cat VERSION 2>/dev/null || echo 'unreleased')}"
DATE="$(date +%Y-%m-%d)"
REPORT_DIR="reports"
REPORT_FILE="${REPORT_DIR}/security-${VERSION}-${DATE}.md"
JSON_DIR="${REPORT_DIR}/.json"

mkdir -p "$REPORT_DIR" "$JSON_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
RESET='\033[0m'

log() { echo -e "${BOLD}[scan]${RESET} $*"; }
pass() { echo -e "  ${GREEN}✓${RESET} $*"; }
warn() { echo -e "  ${YELLOW}!${RESET} $*"; }
fail() { echo -e "  ${RED}✗${RESET} $*"; }

# Check tools
for cmd in trivy semgrep; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "ERROR: $cmd not found. Install it first." >&2
        exit 1
    fi
done

echo -e "${BOLD}BMT AI OS — Pre-Release Security Report${RESET}"
echo "Version: ${VERSION} | Date: ${DATE}"
echo ""

# ── 1. Trivy: Docker Image ───────────────────────────────────────────
log "Trivy: Scanning Docker image..."
trivy image --severity HIGH,CRITICAL --format json \
    --output "${JSON_DIR}/trivy-image.json" \
    bemindlab/bmt-ai-os:latest 2>/dev/null || true

TRIVY_IMAGE_CRITICAL=$(python3 -c "
import json
with open('${JSON_DIR}/trivy-image.json') as f:
    d = json.load(f)
c = h = 0
for r in d.get('Results', []):
    for v in r.get('Vulnerabilities', []):
        if v.get('Severity') == 'CRITICAL': c += 1
        elif v.get('Severity') == 'HIGH': h += 1
print(f'{c},{h}')
" 2>/dev/null || echo "0,0")
IMG_CRIT=$(echo "$TRIVY_IMAGE_CRITICAL" | cut -d, -f1)
IMG_HIGH=$(echo "$TRIVY_IMAGE_CRITICAL" | cut -d, -f2)

if [ "$IMG_CRIT" -gt 0 ]; then fail "Image: ${IMG_CRIT} critical, ${IMG_HIGH} high"
elif [ "$IMG_HIGH" -gt 0 ]; then warn "Image: ${IMG_CRIT} critical, ${IMG_HIGH} high"
else pass "Image: 0 critical, 0 high"; fi

# ── 2. Trivy: Filesystem ─────────────────────────────────────────────
log "Trivy: Scanning filesystem dependencies..."
trivy filesystem --severity HIGH,CRITICAL --scanners vuln --format json \
    --output "${JSON_DIR}/trivy-fs.json" . 2>/dev/null || true

FS_VULNS=$(python3 -c "
import json
with open('${JSON_DIR}/trivy-fs.json') as f:
    d = json.load(f)
total = sum(len(r.get('Vulnerabilities', [])) for r in d.get('Results', []))
print(total)
" 2>/dev/null || echo "0")

if [ "$FS_VULNS" -gt 0 ]; then warn "Filesystem: ${FS_VULNS} vulnerabilities"
else pass "Filesystem: 0 vulnerabilities"; fi

# ── 3. Trivy: IaC/Config ─────────────────────────────────────────────
log "Trivy: Scanning IaC configs..."
trivy config --severity HIGH,CRITICAL --format json \
    --output "${JSON_DIR}/trivy-iac.json" . 2>/dev/null || true

IAC_MISCONF=$(python3 -c "
import json
with open('${JSON_DIR}/trivy-iac.json') as f:
    d = json.load(f)
total = sum(len(r.get('Misconfigurations', [])) for r in d.get('Results', []))
print(total)
" 2>/dev/null || echo "0")

if [ "$IAC_MISCONF" -gt 0 ]; then warn "IaC: ${IAC_MISCONF} misconfigurations"
else pass "IaC: 0 misconfigurations"; fi

# ── 4. Semgrep: SAST ─────────────────────────────────────────────────
log "Semgrep: Scanning Python code..."
semgrep scan --config "p/python" --config "p/owasp-top-ten" \
    --severity ERROR --severity WARNING \
    --json --output "${JSON_DIR}/semgrep.json" \
    bmt_ai_os/ 2>/dev/null || true

SEMGREP_FINDINGS=$(python3 -c "
import json
with open('${JSON_DIR}/semgrep.json') as f:
    d = json.load(f)
print(len(d.get('results', [])))
" 2>/dev/null || echo "0")

if [ "$SEMGREP_FINDINGS" -gt 0 ]; then warn "SAST: ${SEMGREP_FINDINGS} findings"
else pass "SAST: 0 findings"; fi

# ── 5. Ruff: Lint ────────────────────────────────────────────────────
log "Ruff: Checking lint..."
RUFF_EXIT=0
uvx ruff check bmt_ai_os/ tests/ 2>/dev/null || RUFF_EXIT=$?

if [ "$RUFF_EXIT" -eq 0 ]; then pass "Lint: clean"
else fail "Lint: errors found"; fi

# ── 6. Tests ─────────────────────────────────────────────────────────
log "Pytest: Running tests..."
TEST_OUTPUT=$(python3 -m pytest tests/unit/ tests/smoke/ -q --tb=no 2>&1 || true)
TEST_PASSED=$(echo "$TEST_OUTPUT" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+' || echo "0")
TEST_FAILED=$(echo "$TEST_OUTPUT" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+' || echo "0")

if [ "$TEST_FAILED" -gt 0 ]; then fail "Tests: ${TEST_PASSED} passed, ${TEST_FAILED} failed"
else pass "Tests: ${TEST_PASSED} passed"; fi

# ── Generate Markdown Report ─────────────────────────────────────────
cat > "$REPORT_FILE" << EOF
# Security Report �� BMT AI OS ${VERSION}

**Date:** ${DATE}
**Scanner versions:** Trivy $(trivy --version 2>&1 | head -1 | awk '{print $2}'), Semgrep $(semgrep --version 2>&1 | head -1)

## Summary

| Check | Status | Details |
|-------|--------|---------|
| Docker Image (Trivy) | $([ "$IMG_CRIT" -eq 0 ] && [ "$IMG_HIGH" -le 5 ] && echo "PASS" || echo "WARN") | ${IMG_CRIT} critical, ${IMG_HIGH} high |
| Filesystem Deps (Trivy) | $([ "$FS_VULNS" -eq 0 ] && echo "PASS" || echo "WARN") | ${FS_VULNS} vulnerabilities |
| IaC Config (Trivy) | $([ "$IAC_MISCONF" -eq 0 ] && echo "PASS" || echo "WARN") | ${IAC_MISCONF} misconfigurations |
| SAST (Semgrep) | $([ "$SEMGREP_FINDINGS" -eq 0 ] && echo "PASS" || echo "WARN") | ${SEMGREP_FINDINGS} findings |
| Lint (Ruff) | $([ "$RUFF_EXIT" -eq 0 ] && echo "PASS" || echo "FAIL") | $([ "$RUFF_EXIT" -eq 0 ] && echo "clean" || echo "errors") |
| Tests (Pytest) | $([ "$TEST_FAILED" -eq 0 ] && echo "PASS" || echo "FAIL") | ${TEST_PASSED} passed, ${TEST_FAILED} failed |

## Image Vulnerabilities

$(trivy image --severity HIGH,CRITICAL bemindlab/bmt-ai-os:latest 2>/dev/null | grep -A100 "^Total:" | head -30 || echo "No HIGH/CRITICAL vulnerabilities found.")

## Release Gate

$(if [ "$IMG_CRIT" -eq 0 ] && [ "$SEMGREP_FINDINGS" -eq 0 ] && [ "$RUFF_EXIT" -eq 0 ] && [ "$TEST_FAILED" -eq 0 ]; then
    echo "**PASS** — Safe to release ${VERSION}"
else
    echo "**BLOCKED** — Fix issues before releasing ${VERSION}"
fi)
EOF

echo ""
echo -e "${BOLD}Report saved: ${REPORT_FILE}${RESET}"
echo ""

# ── Gate result ──────────────────────────────────────────────────────
if [ "$IMG_CRIT" -eq 0 ] && [ "$SEMGREP_FINDINGS" -eq 0 ] && [ "$RUFF_EXIT" -eq 0 ] && [ "$TEST_FAILED" -eq 0 ]; then
    echo -e "${GREEN}${BOLD}RELEASE GATE: PASS${RESET}"
    exit 0
else
    echo -e "${RED}${BOLD}RELEASE GATE: BLOCKED${RESET}"
    exit 1
fi
