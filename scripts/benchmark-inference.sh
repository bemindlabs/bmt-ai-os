#!/bin/sh
# scripts/benchmark-inference.sh
# Performance benchmark: measure tok/s for Qwen2.5-Coder-7B Q4 via Ollama.
#
# Usage:
#   ./scripts/benchmark-inference.sh [--model MODEL] [--passes N] [--json]
#
# Outputs a summary to stdout. With --json, emits machine-readable JSON
# suitable for CI consumption.
#
# BMTOS-2b | Epic: BMTOS-EPIC-4

set -eu

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
MODEL="${BMT_BENCH_MODEL:-qwen2.5-coder:7b-q4_K_M}"
PASSES=10
JSON_OUTPUT=false
OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"
PROMPT="Write a Python function that implements binary search on a sorted list."

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
while [ $# -gt 0 ]; do
    case "$1" in
        --model)  MODEL="$2";  shift 2 ;;
        --passes) PASSES="$2"; shift 2 ;;
        --json)   JSON_OUTPUT=true; shift ;;
        -h|--help)
            echo "Usage: $0 [--model MODEL] [--passes N] [--json]"
            exit 0
            ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

LOG_TAG="[bmt-bench]"
log_info() { echo "${LOG_TAG} $*"; }

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------
if ! command -v curl >/dev/null 2>&1; then
    echo "${LOG_TAG} ERROR: curl is required" >&2
    exit 1
fi

if ! command -v jq >/dev/null 2>&1 && [ "${JSON_OUTPUT}" = "true" ]; then
    echo "${LOG_TAG} ERROR: jq is required for --json output" >&2
    exit 1
fi

# Wait for Ollama to be ready
log_info "Waiting for Ollama at ${OLLAMA_HOST}..."
RETRIES=0
while ! curl -sf "${OLLAMA_HOST}/api/tags" >/dev/null 2>&1; do
    RETRIES=$((RETRIES + 1))
    if [ "${RETRIES}" -ge 30 ]; then
        echo "${LOG_TAG} ERROR: Ollama not reachable after 30 attempts" >&2
        exit 1
    fi
    sleep 2
done
log_info "Ollama is ready."

# ---------------------------------------------------------------------------
# Pull model if not present
# ---------------------------------------------------------------------------
log_info "Ensuring model '${MODEL}' is available..."
curl -sf -X POST "${OLLAMA_HOST}/api/pull" \
    -H "Content-Type: application/json" \
    -d "{\"name\": \"${MODEL}\", \"stream\": false}" >/dev/null 2>&1 || {
    log_info "Pull request sent (may take a while for first download)."
    # Stream pull to wait for completion
    curl -sN -X POST "${OLLAMA_HOST}/api/pull" \
        -H "Content-Type: application/json" \
        -d "{\"name\": \"${MODEL}\", \"stream\": true}" | while read -r line; do
        STATUS=$(echo "${line}" | jq -r '.status // empty' 2>/dev/null)
        [ -n "${STATUS}" ] && printf "\r${LOG_TAG} Pull: %s" "${STATUS}"
    done
    echo ""
}

# ---------------------------------------------------------------------------
# Detect accelerator
# ---------------------------------------------------------------------------
ACCEL="${BMT_ACCEL:-unknown}"
if [ "${ACCEL}" = "unknown" ]; then
    if [ -e /dev/nvhost-ctrl ] || [ -e /dev/nvidia0 ]; then ACCEL="cuda"
    elif [ -e /dev/rknpu ]; then ACCEL="rknn"
    elif [ -e /dev/hailo0 ]; then ACCEL="hailo"
    else ACCEL="cpu"
    fi
fi

# ---------------------------------------------------------------------------
# Run inference benchmark passes
# ---------------------------------------------------------------------------
log_info "Running ${PASSES} inference passes with ${MODEL} (accel=${ACCEL})..."

TOTAL_TOKS=0
TOTAL_DURATION_NS=0
TOTAL_EVAL_TOKS=0
TOTAL_EVAL_DURATION_NS=0
PASS=0

while [ "${PASS}" -lt "${PASSES}" ]; do
    PASS=$((PASS + 1))

    RESPONSE=$(curl -sf -X POST "${OLLAMA_HOST}/api/generate" \
        -H "Content-Type: application/json" \
        -d "{
            \"model\": \"${MODEL}\",
            \"prompt\": \"${PROMPT}\",
            \"stream\": false,
            \"options\": {\"num_predict\": 256}
        }" 2>/dev/null) || {
        log_info "WARN: Pass ${PASS} failed, skipping"
        continue
    }

    EVAL_COUNT=$(echo "${RESPONSE}" | jq -r '.eval_count // 0')
    EVAL_DURATION=$(echo "${RESPONSE}" | jq -r '.eval_duration // 0')
    TOTAL_DURATION=$(echo "${RESPONSE}" | jq -r '.total_duration // 0')

    TOTAL_EVAL_TOKS=$((TOTAL_EVAL_TOKS + EVAL_COUNT))
    TOTAL_EVAL_DURATION_NS=$((TOTAL_EVAL_DURATION_NS + EVAL_DURATION))
    TOTAL_DURATION_NS=$((TOTAL_DURATION_NS + TOTAL_DURATION))

    if [ "${EVAL_DURATION}" -gt 0 ]; then
        # tok/s = eval_count / (eval_duration_ns / 1e9)
        PASS_TOKS=$(echo "${EVAL_COUNT} ${EVAL_DURATION}" | awk '{printf "%.2f", $1 / ($2 / 1000000000)}')
    else
        PASS_TOKS="N/A"
    fi

    log_info "  Pass ${PASS}/${PASSES}: ${EVAL_COUNT} tokens, ${PASS_TOKS} tok/s"
done

# ---------------------------------------------------------------------------
# Compute averages
# ---------------------------------------------------------------------------
if [ "${TOTAL_EVAL_DURATION_NS}" -gt 0 ]; then
    AVG_TOKS=$(echo "${TOTAL_EVAL_TOKS} ${TOTAL_EVAL_DURATION_NS}" | awk '{printf "%.2f", $1 / ($2 / 1000000000)}')
else
    AVG_TOKS="0.00"
fi

AVG_EVAL_TOKS=$((TOTAL_EVAL_TOKS / PASSES))

# Memory usage (best-effort, reads from Ollama ps)
MEM_USAGE=$(curl -sf "${OLLAMA_HOST}/api/ps" 2>/dev/null | jq -r '.models[0].size_vram // 0' 2>/dev/null || echo "0")
MEM_MB=$(echo "${MEM_USAGE}" | awk '{printf "%.0f", $1 / 1048576}')

# ---------------------------------------------------------------------------
# Output results
# ---------------------------------------------------------------------------
HOSTNAME_STR=$(hostname 2>/dev/null || echo "unknown")
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date)

if [ "${JSON_OUTPUT}" = "true" ]; then
    cat <<ENDJSON
{
  "benchmark": "bmt-inference",
  "timestamp": "${TIMESTAMP}",
  "host": "${HOSTNAME_STR}",
  "model": "${MODEL}",
  "quantization": "Q4_K_M",
  "accelerator": "${ACCEL}",
  "passes": ${PASSES},
  "total_eval_tokens": ${TOTAL_EVAL_TOKS},
  "avg_tokens_per_pass": ${AVG_EVAL_TOKS},
  "avg_tok_per_sec": ${AVG_TOKS},
  "vram_mb": ${MEM_MB}
}
ENDJSON
else
    echo ""
    echo "========================================"
    echo "  BMT AI OS — Inference Benchmark"
    echo "========================================"
    echo "  Host:          ${HOSTNAME_STR}"
    echo "  Timestamp:     ${TIMESTAMP}"
    echo "  Model:         ${MODEL}"
    echo "  Quantization:  Q4_K_M"
    echo "  Accelerator:   ${ACCEL}"
    echo "  Passes:        ${PASSES}"
    echo "  Total tokens:  ${TOTAL_EVAL_TOKS}"
    echo "  Avg tok/s:     ${AVG_TOKS}"
    echo "  VRAM/RAM:      ${MEM_MB} MB"
    echo "========================================"
fi
