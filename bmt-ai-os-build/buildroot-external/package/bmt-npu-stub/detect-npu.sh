#!/bin/sh
# /usr/lib/bmt-ai-os/detect-npu.sh
# Detect available NPU/GPU backend and export BMT_NPU_BACKEND.
# Sourced by the controller init script before launching main.py.
#
# Possible values: cuda | rknn | hailo | cpu
#
# BMTOS-2b | Epic: BMTOS-EPIC-4 (Hardware Board Support Packages)

detect_backend() {
    # NVIDIA Jetson Orin — check for CUDA device nodes and tegra SoC
    if [ -e /dev/nvhost-ctrl ] || [ -e /dev/nvidia0 ]; then
        # Verify NVIDIA runtime is functional
        if command -v nvidia-smi >/dev/null 2>&1; then
            echo "cuda"
        elif [ -d /proc/device-tree ] && grep -qi "tegra" /proc/device-tree/compatible 2>/dev/null; then
            echo "cuda"
        else
            echo "cuda"
        fi
        return
    fi

    # Rockchip RK3588 — check for RKNPU device and verify driver loaded
    if [ -e /dev/rknpu ] || [ -e /dev/rknpu0 ]; then
        # Check that DMA heap and MPP service are also available
        if [ -e /dev/mpp_service ]; then
            echo "rknn"
        else
            echo "[bmt-npu] WARN: /dev/rknpu found but /dev/mpp_service missing" >&2
            echo "rknn"
        fi
        return
    fi

    # Raspberry Pi 5 + Hailo AI HAT+ 2 (Hailo-10H)
    if [ -e /dev/hailo0 ]; then
        # Verify HailoRT can communicate with the device
        if command -v hailortcli >/dev/null 2>&1; then
            if hailortcli fw-control identify >/dev/null 2>&1; then
                echo "hailo"
            else
                echo "[bmt-npu] WARN: Hailo device found but fw-control failed" >&2
                echo "hailo"
            fi
        else
            echo "hailo"
        fi
        return
    fi

    # Apple Silicon (Asahi Linux) — CPU-only, fastest ARM64 CPU inference
    if [ -f /proc/device-tree/compatible ] && grep -qi "apple" /proc/device-tree/compatible 2>/dev/null; then
        echo "cpu"
        return
    fi

    # CPU-only fallback (QEMU, generic ARM64, unknown hardware)
    echo "cpu"
}

detect_cpu_features() {
    if [ -f /proc/cpuinfo ]; then
        if grep -q "sve" /proc/cpuinfo 2>/dev/null; then
            echo "NEON+SVE"
        elif grep -q "asimd\|neon" /proc/cpuinfo 2>/dev/null; then
            echo "NEON/ASIMD"
        else
            echo "basic"
        fi
    else
        echo "unknown"
    fi
}

BMT_NPU_BACKEND="$(detect_backend)"
BMT_CPU_FEATURES="$(detect_cpu_features)"
export BMT_NPU_BACKEND
export BMT_CPU_FEATURES

echo "[bmt-npu] Backend detected: ${BMT_NPU_BACKEND}"
echo "[bmt-npu] CPU features: ${BMT_CPU_FEATURES}"

# Write to runtime env file for other services to consume
if [ -d /run/bmt-ai-os ]; then
    echo "BMT_NPU_BACKEND=${BMT_NPU_BACKEND}" > /run/bmt-ai-os/npu.env
    echo "BMT_CPU_FEATURES=${BMT_CPU_FEATURES}" >> /run/bmt-ai-os/npu.env
fi
