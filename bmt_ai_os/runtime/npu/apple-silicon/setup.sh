#!/bin/sh
# /usr/lib/bmt-ai-os/apple-silicon/setup.sh
# Configure BMT AI OS for CPU-only inference on Apple Silicon (Asahi Linux).
#
# Apple Silicon specifics:
#   - No Metal/GPU compute on Linux (display-only DRM via Asahi AGX driver)
#   - Fastest ARM64 CPU inference target: 8-128 GB unified memory, big.LITTLE
#     P-core (Firestorm/Everest) + E-core (Icestorm/Sawtooth) topology
#   - NEON/ASIMD SIMD on all cores; no SVE on M-series (Apple proprietary ISA)
#   - llama.cpp, Ollama use GGML CPU backend with BLAS acceleration
#   - Unified memory: no copy overhead between CPU and "GPU" — all RAM is
#     accessible to CPU inference at full bandwidth
#
# This script:
#   1. Detects core topology (P-cores vs E-cores) for thread pinning
#   2. Sets OLLAMA_NUM_THREADS to P-core count for best latency
#   3. Configures OpenBLAS thread affinity
#   4. Writes /run/bmt-ai-os/apple-silicon-setup.env
#   5. Generates the Apple Silicon compose override
#
# Called by: bmt-firstboot init script, passthrough.sh
# BMTOS-43 | Epic: BMTOS-EPIC-4 (Hardware Board Support Packages)

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AI_STACK_DIR="${SCRIPT_DIR}/../../../ai-stack"
BMT_RUNTIME_DIR="${BMT_RUNTIME_DIR:-/run/bmt-ai-os}"
LOG_TAG="[bmt-apple-setup]"

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
log_info()  { echo "${LOG_TAG} INFO:  $*"; }
log_warn()  { echo "${LOG_TAG} WARN:  $*" >&2; }
log_error() { echo "${LOG_TAG} ERROR: $*" >&2; }

# ---------------------------------------------------------------------------
# Load detection results if available
# ---------------------------------------------------------------------------
load_detection_env() {
    if [ -f "${BMT_RUNTIME_DIR}/apple-silicon.env" ]; then
        # shellcheck source=/dev/null
        . "${BMT_RUNTIME_DIR}/apple-silicon.env"
        log_info "Loaded detection env: chip=${BMT_CHIP:-unknown}, cores=${BMT_CPU_CORES:-?}"
    else
        log_warn "Detection env not found — running detect.sh first"
        "${SCRIPT_DIR}/detect.sh" >/dev/null 2>&1 || true
        if [ -f "${BMT_RUNTIME_DIR}/apple-silicon.env" ]; then
            # shellcheck source=/dev/null
            . "${BMT_RUNTIME_DIR}/apple-silicon.env"
        fi
    fi

    # Defaults if detection did not run
    BMT_CHIP="${BMT_CHIP:-unknown}"
    BMT_CPU_CORES="${BMT_CPU_CORES:-$(nproc 2>/dev/null || echo 4)}"
    BMT_CPU_SIMD="${BMT_CPU_SIMD:-NEON/ASIMD}"
    BMT_MEMORY_GB="${BMT_MEMORY_GB:-8}"
}

# ---------------------------------------------------------------------------
# Determine P-core (performance core) count for thread configuration.
#
# M-series core counts by chip family (P-cores : E-cores):
#   M1:           4P + 4E  =  8 total
#   M1 Pro:       8P + 2E  = 10 total
#   M1 Max/Ultra: 8P + 2E  = 10 (or 20 for Ultra)
#   M2:           4P + 4E  =  8 total
#   M2 Pro:       8P + 4E  = 12 total
#   M2 Max/Ultra: 8P + 4E  = 12 (or 24 for Ultra)
#   M3:           4P + 4E  =  8 total
#   M3 Pro:       5P + 6E  = 11 total
#   M3 Max/Ultra: 8P + 4E  = 12 (or 24 for Ultra)
#   M4:           4P + 6E  = 10 total
#   M4 Pro:       8P + 4E  = 14 total (Apple announced 14-core)
#   M4 Max/Ultra: 10P+ 4E  = 14 (or 28 for Ultra)
#
# Heuristic: P-cores are typically 40-60% of total. We fall back to
# total_cores - 4 (reserve E-cores for OS tasks) with a minimum of 4.
# ---------------------------------------------------------------------------
calculate_p_cores() {
    TOTAL="${BMT_CPU_CORES}"
    CHIP_NAME="${BMT_CHIP}"

    # Try to read actual P-core count from cpufreq topology
    # P-cores typically run at higher max frequency than E-cores
    P_CORE_COUNT=0
    if [ -d /sys/devices/system/cpu ]; then
        # Find unique max frequencies; highest-freq cluster = P-cores
        MAX_FREQ=0
        for policy_dir in /sys/devices/system/cpu/cpufreq/policy*/; do
            if [ -f "${policy_dir}cpuinfo_max_freq" ]; then
                FREQ="$(cat "${policy_dir}cpuinfo_max_freq" 2>/dev/null || echo 0)"
                if [ "${FREQ}" -gt "${MAX_FREQ}" ]; then
                    MAX_FREQ="${FREQ}"
                fi
            fi
        done

        if [ "${MAX_FREQ}" -gt 0 ]; then
            for policy_dir in /sys/devices/system/cpu/cpufreq/policy*/; do
                if [ -f "${policy_dir}cpuinfo_max_freq" ]; then
                    FREQ="$(cat "${policy_dir}cpuinfo_max_freq" 2>/dev/null || echo 0)"
                    if [ "${FREQ}" -eq "${MAX_FREQ}" ]; then
                        # Count CPUs in this policy (related_cpus)
                        if [ -f "${policy_dir}related_cpus" ]; then
                            N="$(wc -w < "${policy_dir}related_cpus" 2>/dev/null || echo 0)"
                            P_CORE_COUNT=$(( P_CORE_COUNT + N ))
                        fi
                    fi
                fi
            done
        fi
    fi

    if [ "${P_CORE_COUNT}" -gt 0 ]; then
        log_info "P-core count from cpufreq topology: ${P_CORE_COUNT}"
        echo "${P_CORE_COUNT}"
        return
    fi

    # Chip-name heuristic fallback
    case "${CHIP_NAME}" in
        "M1")            echo 4  ;;
        "M1 Pro/Max")    echo 8  ;;
        "M1 Ultra")      echo 16 ;;
        "M2")            echo 4  ;;
        "M2 Pro/Max")    echo 8  ;;
        "M2 Ultra")      echo 16 ;;
        "M3")            echo 4  ;;
        "M3 Pro/Max")    echo 6  ;;
        "M3 Ultra")      echo 16 ;;
        "M4")            echo 4  ;;
        "M4 Pro/Max")    echo 10 ;;
        "M4 Ultra")      echo 20 ;;
        *)
            # Generic: reserve 4 E-cores for OS, use rest for inference
            HEURISTIC=$(( TOTAL - 4 ))
            if [ "${HEURISTIC}" -lt 4 ]; then
                HEURISTIC=4
            fi
            log_warn "Unknown chip '${CHIP_NAME}' — using heuristic P-core count: ${HEURISTIC}"
            echo "${HEURISTIC}"
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Calculate optimal memory limits for inference containers.
# Apple Silicon unified memory — leave ~2 GB for OS + containers overhead.
# ---------------------------------------------------------------------------
calculate_memory_limits() {
    MEM_GB="${BMT_MEMORY_GB:-8}"

    # Attempt to parse as integer
    MEM_INT="${MEM_GB%%.*}"
    case "${MEM_INT}" in
        ''|*[!0-9]*) MEM_INT=8 ;;
    esac

    if [ "${MEM_INT}" -ge 64 ]; then
        OLLAMA_MEM="56g"
        CHROMA_MEM="4g"
    elif [ "${MEM_INT}" -ge 32 ]; then
        OLLAMA_MEM="28g"
        CHROMA_MEM="2g"
    elif [ "${MEM_INT}" -ge 16 ]; then
        OLLAMA_MEM="13g"
        CHROMA_MEM="1g"
    else
        # 8 GB — minimum viable for 7B model with 4-bit quant (~4.5 GB)
        OLLAMA_MEM="6g"
        CHROMA_MEM="512m"
    fi

    echo "${OLLAMA_MEM}:${CHROMA_MEM}"
}

# ---------------------------------------------------------------------------
# Configure OpenBLAS thread count for GGML/llama.cpp CPU backend
# ---------------------------------------------------------------------------
configure_openblas() {
    P_CORES="$1"
    export OPENBLAS_NUM_THREADS="${P_CORES}"
    export GOTO_NUM_THREADS="${P_CORES}"
    export OMP_NUM_THREADS="${P_CORES}"
    log_info "OpenBLAS/OMP thread count: ${P_CORES} (P-cores)"
}

# ---------------------------------------------------------------------------
# Configure CPU governor to performance mode for inference workloads.
# Asahi Linux exposes cpufreq scaling via the standard sysfs interface.
# ---------------------------------------------------------------------------
configure_cpu_governor() {
    GOVERNOR_SET=0
    for cpu_dir in /sys/devices/system/cpu/cpu*/cpufreq/; do
        SCALING_GOV="${cpu_dir}scaling_governor"
        if [ -w "${SCALING_GOV}" ]; then
            echo "performance" > "${SCALING_GOV}" 2>/dev/null && GOVERNOR_SET=$(( GOVERNOR_SET + 1 )) || true
        fi
    done

    if [ "${GOVERNOR_SET}" -gt 0 ]; then
        log_info "Set 'performance' governor on ${GOVERNOR_SET} CPU(s)"
    else
        log_warn "Could not set CPU governor (needs root or cpufreq write access)"
        log_warn "Run as root for best inference throughput, or set manually:"
        log_warn "  echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor"
    fi
}

# ---------------------------------------------------------------------------
# Write setup environment file consumed by controller and compose
# ---------------------------------------------------------------------------
write_setup_env() {
    P_CORES="$1"
    MEM_LIMITS="$2"
    OLLAMA_MEM="${MEM_LIMITS%%:*}"
    CHROMA_MEM="${MEM_LIMITS##*:}"

    mkdir -p "${BMT_RUNTIME_DIR}" 2>/dev/null || true

    cat > "${BMT_RUNTIME_DIR}/apple-silicon-setup.env" <<EOF
# BMT AI OS — Apple Silicon CPU inference setup
# Generated by setup.sh on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
BMT_PLATFORM=apple-silicon
BMT_CHIP=${BMT_CHIP}
BMT_CPU_CORES=${BMT_CPU_CORES}
BMT_P_CORES=${P_CORES}
BMT_CPU_SIMD=${BMT_CPU_SIMD}
BMT_MEMORY_GB=${BMT_MEMORY_GB}
BMT_ACCEL=cpu
BMT_NPU_BACKEND=cpu
BMT_GPU_COMPUTE=none
OLLAMA_NUM_THREADS=${P_CORES}
OLLAMA_NUM_GPU=0
OLLAMA_FLASH_ATTENTION=1
OLLAMA_KV_CACHE_TYPE=q8_0
OPENBLAS_NUM_THREADS=${P_CORES}
OMP_NUM_THREADS=${P_CORES}
OLLAMA_MEMORY_LIMIT=${OLLAMA_MEM}
CHROMADB_MEMORY_LIMIT=${CHROMA_MEM}
EOF
    log_info "Setup env written to ${BMT_RUNTIME_DIR}/apple-silicon-setup.env"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    log_info "Configuring BMT AI OS for Apple Silicon (CPU-only, Asahi Linux)"
    log_info "NOTE: No Metal/GPU compute on Linux. Using NEON/ASIMD SIMD path."

    load_detection_env

    log_info "Chip: ${BMT_CHIP}, Total cores: ${BMT_CPU_CORES}, SIMD: ${BMT_CPU_SIMD}"
    log_info "Unified memory: ${BMT_MEMORY_GB} GB"

    P_CORES="$(calculate_p_cores)"
    log_info "Using ${P_CORES} P-cores for inference threads"

    MEM_LIMITS="$(calculate_memory_limits)"
    OLLAMA_MEM="${MEM_LIMITS%%:*}"
    CHROMA_MEM="${MEM_LIMITS##*:}"
    log_info "Memory limits — Ollama: ${OLLAMA_MEM}, ChromaDB: ${CHROMA_MEM}"

    configure_openblas "${P_CORES}"
    configure_cpu_governor

    write_setup_env "${P_CORES}" "${MEM_LIMITS}"

    log_info "Apple Silicon CPU inference setup complete."
    log_info "Recommended models for this platform:"
    log_info "  8 GB:  qwen2.5-coder:7b-instruct-q4_K_M  (~4.5 GB)"
    log_info "  16 GB: qwen2.5-coder:14b-instruct-q4_K_M (~8.5 GB)"
    log_info "  32 GB: qwen2.5-coder:32b-instruct-q4_K_M (~19 GB)"
    log_info "  64 GB: qwen2.5-coder:72b-instruct-q4_K_M (~44 GB)"
}

main "$@"
