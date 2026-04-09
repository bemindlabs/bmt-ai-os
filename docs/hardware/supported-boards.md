# Supported Hardware

## Tier 1 — Primary Targets

### Apple Silicon (M1-M4, Asahi Linux) — $800+
- **Acceleration:** CPU-only (ARM NEON) — no Metal/GPU on Linux
- **RAM:** 8-192GB unified memory
- **Inference:** 7B @ 30-50 tok/s (CPU), 13B @ 15-22 tok/s (16GB+)
- **Training:** LoRA 3B (~20 min CPU), QLoRA 3B (~30 min CPU)
- **Best for:** Fastest ARM64 CPU inference, large models (13B+ on 16GB), developer workstations
- **Limitation:** No GPU acceleration on Asahi Linux (Apple GPU driver incomplete)

### NVIDIA Jetson Orin Nano Super (~$250)
- **NPU/GPU:** 67 TOPS CUDA (1024 cores)
- **RAM:** 8GB unified
- **Inference:** 7B model @ 15-22 tok/s
- **Training:** LoRA 1.5B (~30 min), QLoRA 3B (~1 hr)
- **Acceleration:** CUDA, TensorRT-LLM
- **Best for:** GPU-accelerated training, embedded/edge deployments

### Rockchip RK3588 Boards (~$100-180)
*Orange Pi 5, Radxa ROCK 5B, and similar*
- **NPU:** 6 TOPS RKNN (3 cores)
- **RAM:** 8-32GB
- **Inference:** 1.1B @ 18 tok/s (NPU), 7B @ 4-6 tok/s (CPU)
- **Training:** LoRA 1.5B CPU (~3 hrs)
- **Acceleration:** RKNN (small models), CPU NEON (larger models)
- **Best for:** Best value, large RAM options

### Raspberry Pi 5 + AI HAT+ 2 (~$210)
- **NPU:** 40 TOPS Hailo-10H (8GB onboard RAM)
- **RAM:** 8GB
- **Inference:** 1.5B @ 9.5 tok/s (Hailo), 7B @ 2-4 tok/s (CPU)
- **Training:** LoRA <1B CPU only (~6 hrs)
- **Acceleration:** HailoRT (models up to 1.5B)
- **Best for:** Largest community, most accessible

## Tier 2 — Future

| Board | Notes |
|-------|-------|
| Raspberry Pi 5 (CPU-only, no Hailo) | Baseline, 1-3B models only |

## Not Supported

| Hardware | Reason |
|----------|--------|
| Qualcomm Snapdragon X | Linux NPU support dead (DSP headers not open-sourced) |
| MediaTek Dimensity | No Linux SBC path, Android-only |

## Choosing a Board

| Priority | Choose |
|----------|--------|
| Fastest inference | Apple Silicon (M1+ via Asahi Linux) |
| Best GPU training | Jetson Orin Nano Super |
| Best value | RK3588 (Orange Pi 5 16GB) |
| Largest community | Raspberry Pi 5 + AI HAT+ 2 |
| Large models (13B+) | Apple Silicon 16GB+ |
| Budget under $100 | RK3588 8GB (Orange Pi 5) |
