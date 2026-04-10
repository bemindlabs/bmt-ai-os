#!/bin/sh
# /usr/lib/bmt_ai_os/passthrough.sh
# GPU/NPU device passthrough setup for BMT AI OS containers.
# Auto-detects hardware accelerator and generates a docker-compose.override.yml
# with the appropriate device mappings, runtime, and environment variables.
#
# Tier 1 targets:
#   - Jetson Orin Nano Super (CUDA)
#   - RK3588 boards (RKNN)
#   - Raspberry Pi 5 + Hailo AI HAT+ 2 (HailoRT)
#   - Apple Silicon / Asahi Linux (CPU-only, NEON)
#   - Generic ARM64 (CPU-only fallback)
#
# BMTOS-2b | Epic: BMTOS-EPIC-4 (Hardware Board Support Packages)

set -eu

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AI_STACK_DIR="${SCRIPT_DIR}/../../ai-stack"
OVERRIDE_OUT="${AI_STACK_DIR}/docker-compose.override.yml"
LOG_TAG="[bmt-passthrough]"

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
log_info()  { echo "${LOG_TAG} INFO:  $*"; }
log_warn()  { echo "${LOG_TAG} WARN:  $*" >&2; }
log_error() { echo "${LOG_TAG} ERROR: $*" >&2; }

# ---------------------------------------------------------------------------
# Hardware detection
# ---------------------------------------------------------------------------
detect_platform() {
    # Jetson Orin / NVIDIA Tegra — CUDA device nodes
    if [ -e /dev/nvhost-ctrl ] || [ -e /dev/nvidia0 ]; then
        echo "jetson"
        return
    fi

    # Rockchip RK3588 — RKNPU device node
    if [ -e /dev/rknpu ] || [ -e /dev/rknpu0 ]; then
        echo "rk3588"
        return
    fi

    # Raspberry Pi 5 + Hailo AI HAT+ — Hailo device node
    if [ -e /dev/hailo0 ]; then
        echo "hailo"
        return
    fi

    # Apple Silicon (Asahi Linux) — CPU-only, no GPU/NPU on Linux
    if grep -qi "apple" /proc/device-tree/compatible 2>/dev/null ||
       [ "$(uname -m)" = "arm64" ] && sysctl -n machdep.cpu.brand_string 2>/dev/null | grep -qi "apple"; then
        echo "apple"
        return
    fi

    # Generic CPU-only fallback
    echo "cpu"
}

# ---------------------------------------------------------------------------
# CPU capability detection (NEON / SVE)
# ---------------------------------------------------------------------------
detect_cpu_features() {
    FEATURES=""
    if grep -q "neon\|asimd" /proc/cpuinfo 2>/dev/null; then
        FEATURES="${FEATURES} NEON/ASIMD"
    fi
    if grep -q "sve" /proc/cpuinfo 2>/dev/null; then
        FEATURES="${FEATURES} SVE"
    fi
    NPROC=$(nproc 2>/dev/null || echo "4")
    echo "${FEATURES:- none detected} (${NPROC} cores)"
}

# ---------------------------------------------------------------------------
# Generate override: Jetson Orin (CUDA / NVIDIA Container Runtime)
# ---------------------------------------------------------------------------
generate_jetson_override() {
    log_info "Jetson Orin detected — configuring NVIDIA runtime + CUDA passthrough"
    cp "${SCRIPT_DIR}/docker-compose.override.jetson.yml" "${OVERRIDE_OUT}"
    export BMT_ACCEL="cuda"
    export BMT_NPU_BACKEND="cuda"
}

# ---------------------------------------------------------------------------
# Generate override: RK3588 (RKNN NPU)
# ---------------------------------------------------------------------------
generate_rk3588_override() {
    log_info "RK3588 detected — configuring RKNN NPU passthrough"

    # Verify required device nodes
    for dev in /dev/rknpu /dev/mpp_service; do
        if [ ! -e "${dev}" ]; then
            log_warn "Expected device ${dev} not found — RKNN may not work correctly"
        fi
    done

    cp "${SCRIPT_DIR}/docker-compose.override.rk3588.yml" "${OVERRIDE_OUT}"
    export BMT_ACCEL="rknn"
    export BMT_NPU_BACKEND="rknn"
}

# ---------------------------------------------------------------------------
# Generate override: Pi 5 + Hailo AI HAT+ 2 (HailoRT)
# ---------------------------------------------------------------------------
generate_hailo_override() {
    log_info "Hailo AI HAT+ detected — configuring HailoRT passthrough"

    if [ ! -e /dev/hailo0 ]; then
        log_warn "/dev/hailo0 not found — HailoRT may not function"
    fi

    cp "${SCRIPT_DIR}/docker-compose.override.hailo.yml" "${OVERRIDE_OUT}"
    export BMT_ACCEL="hailo"
    export BMT_NPU_BACKEND="hailo"
}

# ---------------------------------------------------------------------------
# Generate override: Apple Silicon (CPU-only)
# ---------------------------------------------------------------------------
generate_apple_override() {
    CPU_FEATURES="$(detect_cpu_features)"
    log_info "Apple Silicon detected — CPU-only mode (Asahi Linux, no Metal/GPU)"
    log_info "CPU features: ${CPU_FEATURES}"

    cp "${SCRIPT_DIR}/docker-compose.override.cpu.yml" "${OVERRIDE_OUT}"
    export BMT_ACCEL="cpu"
    export BMT_NPU_BACKEND="cpu"
}

# ---------------------------------------------------------------------------
# Generate override: CPU-only fallback
# ---------------------------------------------------------------------------
generate_cpu_override() {
    CPU_FEATURES="$(detect_cpu_features)"
    log_warn "No GPU/NPU accelerator detected — falling back to CPU-only inference"
    log_info "CPU features: ${CPU_FEATURES}"
    log_info "Tip: llama.cpp will use NEON/SVE SIMD for best CPU performance"

    cp "${SCRIPT_DIR}/docker-compose.override.cpu.yml" "${OVERRIDE_OUT}"
    export BMT_ACCEL="cpu"
    export BMT_NPU_BACKEND="cpu"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    log_info "Starting GPU/NPU passthrough configuration..."

    PLATFORM="$(detect_platform)"
    log_info "Detected platform: ${PLATFORM}"

    case "${PLATFORM}" in
        jetson) generate_jetson_override ;;
        rk3588) generate_rk3588_override ;;
        hailo)  generate_hailo_override  ;;
        apple)  generate_apple_override  ;;
        cpu)    generate_cpu_override    ;;
        *)
            log_error "Unknown platform: ${PLATFORM}"
            exit 1
            ;;
    esac

    log_info "Override written to: ${OVERRIDE_OUT}"
    log_info "BMT_ACCEL=${BMT_ACCEL}"
    log_info "Passthrough configuration complete."

    # Export for downstream consumers (controller, systemd/OpenRC env)
    echo "BMT_ACCEL=${BMT_ACCEL}" > /run/bmt_ai_os/accel.env 2>/dev/null || true
    echo "BMT_NPU_BACKEND=${BMT_NPU_BACKEND}" >> /run/bmt_ai_os/accel.env 2>/dev/null || true
}

main "$@"
