#!/usr/bin/env bash
# BMT AI OS — AI Stack Validation Script
# Validates Docker Compose config, volumes, service health, and versions.
#
# Usage:
#   ./scripts/validate-stack.sh          # validate config only
#   ./scripts/validate-stack.sh --live   # also check running services

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$STACK_DIR/docker-compose.yml"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

ERRORS=0
WARNINGS=0

pass() { echo -e "  ${GREEN}[PASS]${NC} $1"; }
fail() { echo -e "  ${RED}[FAIL]${NC} $1"; ERRORS=$((ERRORS + 1)); }
warn() { echo -e "  ${YELLOW}[WARN]${NC} $1"; WARNINGS=$((WARNINGS + 1)); }

echo "=== BMT AI OS — AI Stack Validation ==="
echo ""

# --- 1. Compose config validation ---
echo "--- Compose Configuration ---"

if [ ! -f "$COMPOSE_FILE" ]; then
    fail "docker-compose.yml not found at $COMPOSE_FILE"
    exit 1
fi
pass "docker-compose.yml exists"

if docker compose -f "$COMPOSE_FILE" config --quiet 2>/dev/null; then
    pass "Compose config is valid"
else
    fail "Compose config validation failed"
fi

# Check required services
for svc in ollama chromadb; do
    if docker compose -f "$COMPOSE_FILE" config --services 2>/dev/null | grep -q "^${svc}$"; then
        pass "Service '$svc' defined"
    else
        fail "Service '$svc' not found in compose config"
    fi
done

# --- 2. Environment file ---
echo ""
echo "--- Environment ---"

if [ -f "$STACK_DIR/.env" ]; then
    pass ".env file exists"
else
    warn ".env file not found — defaults will be used"
fi

# --- 3. Volume directories ---
echo ""
echo "--- Volumes ---"

for vol_path in /var/lib/ollama/models /var/lib/chromadb; do
    if [ -d "$vol_path" ]; then
        pass "Host path $vol_path exists"
    else
        warn "Host path $vol_path does not exist (will use Docker named volumes)"
    fi
done

# --- 4. Network check ---
echo ""
echo "--- Network ---"

if docker network ls --format '{{.Name}}' 2>/dev/null | grep -q "^bmt-ai-net$"; then
    pass "Network 'bmt-ai-net' exists"
else
    warn "Network 'bmt-ai-net' not yet created (will be created on first 'up')"
fi

# --- 5. Live service checks (optional) ---
if [ "${1:-}" = "--live" ]; then
    echo ""
    echo "--- Live Service Health ---"

    for svc in bmt-ollama bmt-chromadb; do
        status=$(docker inspect --format='{{.State.Health.Status}}' "$svc" 2>/dev/null || echo "not_found")
        case "$status" in
            healthy)   pass "$svc is healthy" ;;
            unhealthy) fail "$svc is unhealthy" ;;
            starting)  warn "$svc is still starting" ;;
            *)         warn "$svc container not found or not running" ;;
        esac
    done

    echo ""
    echo "--- Service Versions ---"

    # Ollama version
    ollama_ver=$(docker exec bmt-ollama ollama --version 2>/dev/null || echo "unavailable")
    echo "  Ollama: $ollama_ver"

    # ChromaDB version
    chromadb_ver=$(curl -sf http://localhost:8000/api/v1/heartbeat 2>/dev/null | grep -o '"nanosecond heartbeat":[0-9]*' || echo "unavailable")
    if [ "$chromadb_ver" != "unavailable" ]; then
        pass "ChromaDB responding on port 8000"
    else
        warn "ChromaDB not responding on port 8000"
    fi

    # Ollama API check
    if curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
        pass "Ollama API responding on port 11434"
    else
        warn "Ollama API not responding on port 11434"
    fi
fi

# --- Summary ---
echo ""
echo "=== Validation Complete ==="
if [ $ERRORS -gt 0 ]; then
    echo -e "${RED}$ERRORS error(s)${NC}, $WARNINGS warning(s)"
    exit 1
elif [ $WARNINGS -gt 0 ]; then
    echo -e "${GREEN}0 errors${NC}, ${YELLOW}$WARNINGS warning(s)${NC}"
    exit 0
else
    echo -e "${GREEN}All checks passed${NC}"
    exit 0
fi
