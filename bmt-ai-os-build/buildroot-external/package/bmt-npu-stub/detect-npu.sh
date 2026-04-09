#!/bin/sh
# /usr/lib/bmt-ai-os/detect-npu.sh
# Detect available NPU/GPU backend and export BMT_NPU_BACKEND.
# Sourced by the controller init script before launching main.py.
#
# Possible values: cuda | rknn | hailo | cpu

detect_backend() {
    # NVIDIA Jetson — check for CUDA device nodes
    if [ -e /dev/nvhost-ctrl ] || [ -e /dev/nvidia0 ]; then
        echo "cuda"
        return
    fi

    # Rockchip RK3588 — check for RKNPU device
    if [ -e /dev/rknpu ] || [ -e /dev/rknpu0 ]; then
        echo "rknn"
        return
    fi

    # Raspberry Pi 5 + Hailo AI HAT+ 2
    if [ -e /dev/hailo0 ]; then
        echo "hailo"
        return
    fi

    # CPU-only fallback (QEMU, Apple Silicon, unknown)
    echo "cpu"
}

BMT_NPU_BACKEND="$(detect_backend)"
export BMT_NPU_BACKEND

echo "[bmt-npu] Backend detected: ${BMT_NPU_BACKEND}"
