#!/bin/sh
# /usr/lib/bmt-ai-os/npu/jetson-orin/detect.sh
# Detect Jetson Orin Nano Super (Tegra234 / p3767) hardware.
#
# Exits 0 if running on a Jetson Orin Nano Super (or compatible Orin board).
# Exits 1 on any other platform so callers can guard Jetson-specific setup.
#
# Detection strategy (ordered, most-specific first):
#   1. /proc/device-tree/compatible   — presence of "nvidia,p3767" (Orin Nano)
#   2. /proc/device-tree/compatible   — "nvidia,tegra234" (any Orin SoC)
#   3. Tegra chip-id via sysfs        — NVIDIA-exported chip ID 0x23 (Tegra234)
#   4. CUDA device nodes              — /dev/nvhost-ctrl, /dev/nvidia0
#
# BMTOS-26 | Epic: BMTOS-EPIC-4 (Hardware Board Support Packages)

set -eu

LOG_TAG="[bmt-jetson-detect]"

log_info()  { echo "${LOG_TAG} INFO:  $*"; }
log_warn()  { echo "${LOG_TAG} WARN:  $*" >&2; }
log_error() { echo "${LOG_TAG} ERROR: $*" >&2; }

# ---------------------------------------------------------------------------
# 1. Device-tree compatible string — most reliable check on JetPack/L4T
# ---------------------------------------------------------------------------
check_device_tree() {
    local compat_file="/proc/device-tree/compatible"

    if [ ! -f "${compat_file}" ]; then
        return 1
    fi

    # The compatible string is NUL-delimited; tr converts to newlines for grep.
    # Expected strings for Jetson Orin Nano Super (p3767-0005):
    #   nvidia,p3767-0000  (Orin NX 16GB)
    #   nvidia,p3767-0001  (Orin NX 8GB)
    #   nvidia,p3767-0003  (Orin Nano 8GB)
    #   nvidia,p3767-0004  (Orin Nano 4GB)
    #   nvidia,p3767-0005  (Orin Nano Super 8GB) <-- primary target
    if tr '\0' '\n' < "${compat_file}" | grep -q "nvidia,p3767"; then
        log_info "Detected nvidia,p3767 (Jetson Orin Nano family) via device-tree"
        return 0
    fi

    # Broader Tegra234 match — covers all Orin SKUs
    if tr '\0' '\n' < "${compat_file}" | grep -q "nvidia,tegra234"; then
        log_info "Detected nvidia,tegra234 (Jetson Orin SoC) via device-tree"
        return 0
    fi

    return 1
}

# ---------------------------------------------------------------------------
# 2. Tegra chip-id sysfs node (exported by nvidia-tegra driver on L4T 36.x)
#    Chip ID 0x23 == Tegra234 (Orin)
# ---------------------------------------------------------------------------
check_chip_id() {
    local chip_id_path="/sys/bus/platform/devices/chip_id/chip_id"

    if [ -r "${chip_id_path}" ]; then
        local chip_id
        chip_id="$(cat "${chip_id_path}" 2>/dev/null || true)"
        if [ "${chip_id}" = "0x23" ]; then
            log_info "Detected Tegra234 chip ID (0x23) via sysfs"
            return 0
        fi
    fi

    # Alternative path exported by tegra-fuse driver
    local fuse_path="/sys/module/tegra_fuse/parameters/tegra_chip_id"
    if [ -r "${fuse_path}" ]; then
        local chip_id
        chip_id="$(cat "${fuse_path}" 2>/dev/null || true)"
        # Tegra234 decimal value = 35
        if [ "${chip_id}" = "35" ]; then
            log_info "Detected Tegra234 chip ID (35) via tegra-fuse"
            return 0
        fi
    fi

    return 1
}

# ---------------------------------------------------------------------------
# 3. CUDA device nodes — present when nvidia-tegra + nvgpu driver is loaded
# ---------------------------------------------------------------------------
check_cuda_devices() {
    if [ -e /dev/nvhost-ctrl ] && [ -e /dev/nvhost-gpu ]; then
        log_info "Detected Jetson CUDA device nodes (/dev/nvhost-ctrl, /dev/nvhost-gpu)"
        return 0
    fi

    # nvidia0 appears when the proprietary CUDA driver stack is active
    if [ -e /dev/nvidia0 ]; then
        log_info "Detected /dev/nvidia0 (NVIDIA GPU node)"
        return 0
    fi

    return 1
}

# ---------------------------------------------------------------------------
# 4. JetPack / L4T release file
# ---------------------------------------------------------------------------
check_l4t_release() {
    if [ -f /etc/nv_tegra_release ]; then
        log_info "Found /etc/nv_tegra_release — L4T OS confirmed"
        return 0
    fi

    if [ -f /etc/jetpack_version ]; then
        log_info "Found /etc/jetpack_version — JetPack confirmed"
        return 0
    fi

    return 1
}

# ---------------------------------------------------------------------------
# Main detection logic
# ---------------------------------------------------------------------------
detect_jetson_orin() {
    if check_device_tree; then
        return 0
    fi

    if check_chip_id; then
        return 0
    fi

    if check_cuda_devices; then
        # CUDA nodes alone could be a discrete GPU; require L4T confirmation
        if check_l4t_release; then
            return 0
        fi
        log_warn "CUDA device nodes found but no L4T marker — not treating as Jetson"
    fi

    return 1
}

# ---------------------------------------------------------------------------
# Export hardware info to runtime env file
# ---------------------------------------------------------------------------
write_env_file() {
    local env_dir="/run/bmt-ai-os"
    if [ -d "${env_dir}" ]; then
        {
            echo "BMT_JETSON_DETECTED=1"
            echo "BMT_JETSON_SOC=tegra234"
            echo "BMT_JETSON_TOPS=67"
            echo "BMT_JETSON_RAM_GB=8"
            echo "BMT_NPU_BACKEND=cuda"
            echo "BMT_ACCEL=cuda"
        } > "${env_dir}/jetson.env"
        log_info "Runtime env written to ${env_dir}/jetson.env"
    fi
}

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
main() {
    log_info "Detecting Jetson Orin Nano Super (Tegra234 / p3767)..."

    if detect_jetson_orin; then
        log_info "Jetson Orin confirmed — 67 TOPS CUDA, Tegra234, 8 GB LPDDR5"
        write_env_file
        exit 0
    else
        log_warn "Jetson Orin NOT detected on this platform"
        exit 1
    fi
}

main "$@"
