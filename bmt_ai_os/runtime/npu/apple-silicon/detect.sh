#!/bin/sh
# /usr/lib/bmt-ai-os/apple-silicon/detect.sh
# Detect Apple Silicon hardware under Asahi Linux.
#
# Returns 0 (success) if running on Apple Silicon, 1 otherwise.
# Prints a JSON-compatible summary of detected capabilities to stdout.
#
# Detection strategy (in order):
#   1. /proc/device-tree/compatible — contains "apple,<chip>" entries on Asahi
#   2. /sys/firmware/devicetree/base/compatible — fallback DT path
#   3. CPU model string via /proc/cpuinfo  — "Apple M" prefix
#   4. Architecture guard (arm64 / aarch64 required)
#
# BMTOS-43 | Epic: BMTOS-EPIC-4 (Hardware Board Support Packages)

set -eu

LOG_TAG="[bmt-apple-detect]"

log_info()  { echo "${LOG_TAG} INFO:  $*"; }
log_warn()  { echo "${LOG_TAG} WARN:  $*" >&2; }
log_error() { echo "${LOG_TAG} ERROR: $*" >&2; }

# ---------------------------------------------------------------------------
# Architecture guard — Apple Silicon is arm64 only
# ---------------------------------------------------------------------------
check_arch() {
    ARCH="$(uname -m)"
    case "${ARCH}" in
        aarch64|arm64) return 0 ;;
        *)
            log_warn "Architecture ${ARCH} is not arm64 — cannot be Apple Silicon"
            return 1
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Device-tree compatible check
# Asahi Linux exposes: apple,t8103 (M1), apple,t6000 (M1 Pro/Max),
#                      apple,t6020 (M2 Pro/Max), apple,t8112 (M2),
#                      apple,t8122 (M3), apple,t8132 (M4), etc.
# ---------------------------------------------------------------------------
check_device_tree() {
    for dt_path in \
        /proc/device-tree/compatible \
        /sys/firmware/devicetree/base/compatible; do
        if [ -f "${dt_path}" ]; then
            # compatible is NUL-delimited; tr converts to newlines for grep
            if tr '\0' '\n' < "${dt_path}" 2>/dev/null | grep -qi "^apple,"; then
                return 0
            fi
        fi
    done
    return 1
}

# ---------------------------------------------------------------------------
# CPU model string check (Asahi Linux exposes this in /proc/cpuinfo)
# ---------------------------------------------------------------------------
check_cpuinfo() {
    if [ -f /proc/cpuinfo ]; then
        if grep -qi "apple m[0-9]" /proc/cpuinfo 2>/dev/null; then
            return 0
        fi
        # Some Asahi kernels expose the SoC die name (e.g. "Apple T8103")
        if grep -qi "apple t[0-9]" /proc/cpuinfo 2>/dev/null; then
            return 0
        fi
    fi
    return 1
}

# ---------------------------------------------------------------------------
# Identify specific Apple Silicon chip from device-tree or cpuinfo
# ---------------------------------------------------------------------------
identify_chip() {
    CHIP="unknown"
    for dt_path in \
        /proc/device-tree/compatible \
        /sys/firmware/devicetree/base/compatible; do
        if [ -f "${dt_path}" ]; then
            COMPAT="$(tr '\0' '\n' < "${dt_path}" 2>/dev/null | grep -i "^apple," | head -1)"
            if [ -n "${COMPAT}" ]; then
                case "${COMPAT}" in
                    apple,t8103*)  CHIP="M1" ;;
                    apple,t6000*)  CHIP="M1 Pro/Max" ;;
                    apple,t6001*)  CHIP="M1 Ultra" ;;
                    apple,t8112*)  CHIP="M2" ;;
                    apple,t6020*)  CHIP="M2 Pro/Max" ;;
                    apple,t6021*)  CHIP="M2 Ultra" ;;
                    apple,t8122*)  CHIP="M3" ;;
                    apple,t6030*)  CHIP="M3 Pro/Max" ;;
                    apple,t6031*)  CHIP="M3 Ultra" ;;
                    apple,t8132*)  CHIP="M4" ;;
                    apple,t6040*)  CHIP="M4 Pro/Max" ;;
                    apple,t6041*)  CHIP="M4 Ultra" ;;
                    *)             CHIP="${COMPAT}" ;;
                esac
                break
            fi
        fi
    done
    echo "${CHIP}"
}

# ---------------------------------------------------------------------------
# Detect CPU core count and SIMD capabilities
# ---------------------------------------------------------------------------
detect_cpu_capabilities() {
    NPROC="$(nproc 2>/dev/null || echo 4)"

    SIMD="NEON/ASIMD"  # All Apple Silicon has NEON; SVE is not exposed on M-series
    if grep -q "^Features.*\bsve\b" /proc/cpuinfo 2>/dev/null; then
        SIMD="NEON/ASIMD+SVE"
    fi

    echo "${NPROC}:${SIMD}"
}

# ---------------------------------------------------------------------------
# Detect unified memory size (best-effort via /proc/meminfo)
# ---------------------------------------------------------------------------
detect_memory_gb() {
    if [ -f /proc/meminfo ]; then
        MEM_KB="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)"
        MEM_GB=$(( MEM_KB / 1048576 ))
        echo "${MEM_GB}"
    else
        echo "unknown"
    fi
}

# ---------------------------------------------------------------------------
# Confirm absence of Metal/GPU compute — expected on Asahi Linux
# ---------------------------------------------------------------------------
check_no_gpu_compute() {
    # Asahi Linux has DRM for display (SimpleDRM / AppleDRM) but no
    # Metal compute or OpenCL. Verify no GPGPU device nodes exist.
    if [ -e /dev/dri/renderD128 ]; then
        # DRI render node may exist for display (AgX driver), but it
        # does NOT support OpenCL or Vulkan compute on Asahi Linux yet.
        log_warn "/dev/dri/renderD128 found — display DRM only, no GPU compute"
        log_warn "Inference will use CPU-only path (NEON/ASIMD). This is expected."
    fi
    # No CUDA, no ROCm, no Metal on Linux — always CPU-only
    return 0
}

# ---------------------------------------------------------------------------
# Main detection logic
# ---------------------------------------------------------------------------
main() {
    if ! check_arch; then
        echo '{"apple_silicon":false,"reason":"wrong_arch"}'
        exit 1
    fi

    if check_device_tree || check_cpuinfo; then
        CHIP="$(identify_chip)"
        CPU_CAPS="$(detect_cpu_capabilities)"
        NPROC="${CPU_CAPS%%:*}"
        SIMD="${CPU_CAPS##*:}"
        MEM_GB="$(detect_memory_gb)"

        check_no_gpu_compute

        log_info "Apple Silicon detected: ${CHIP}"
        log_info "CPU cores: ${NPROC}, SIMD: ${SIMD}, Memory: ${MEM_GB}GB"
        log_info "Inference mode: CPU-only (no Metal/GPU on Asahi Linux)"

        # Write runtime environment for controller and passthrough.sh
        BMT_RUNTIME_DIR="${BMT_RUNTIME_DIR:-/run/bmt-ai-os}"
        if [ -d "${BMT_RUNTIME_DIR}" ] || mkdir -p "${BMT_RUNTIME_DIR}" 2>/dev/null; then
            cat > "${BMT_RUNTIME_DIR}/apple-silicon.env" <<EOF
BMT_PLATFORM=apple-silicon
BMT_CHIP=${CHIP}
BMT_CPU_CORES=${NPROC}
BMT_CPU_SIMD=${SIMD}
BMT_MEMORY_GB=${MEM_GB}
BMT_ACCEL=cpu
BMT_NPU_BACKEND=cpu
BMT_GPU_COMPUTE=none
EOF
        fi

        # JSON summary to stdout for machine-readable consumers
        printf '{"apple_silicon":true,"chip":"%s","cpu_cores":%s,"simd":"%s","memory_gb":"%s","accel":"cpu","gpu_compute":false}\n' \
            "${CHIP}" "${NPROC}" "${SIMD}" "${MEM_GB}"
        exit 0
    fi

    log_warn "Apple Silicon not detected"
    echo '{"apple_silicon":false,"reason":"not_apple_hardware"}'
    exit 1
}

main "$@"
