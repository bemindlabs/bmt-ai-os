# Hardware

BMT AI OS targets four Tier 1 ARM64 boards, each with different accelerator support and price points.

## Tier 1 Comparison

| Board | Accelerator | Inference (7B) | Training | RAM | Price |
|-------|-------------|----------------|----------|-----|-------|
| [Apple Silicon](apple-silicon.md) | CPU (NEON) | 30-50 tok/s | LoRA 3B ~20 min | 8-192 GB | $800+ |
| [Jetson Orin Nano Super](jetson-orin.md) | 67 TOPS CUDA | 15-22 tok/s | LoRA 1.5B ~30 min | 8 GB | ~$250 |
| [RK3588 boards](rk3588.md) | 6 TOPS RKNN | 4-6 tok/s (CPU) | LoRA 1.5B ~3 hrs | 8-32 GB | $100-180 |
| [Raspberry Pi 5 + AI HAT+ 2](pi5-hailo.md) | 40 TOPS Hailo | 9.5 tok/s (1.5B) | LoRA <1B CPU | 8 GB | ~$210 |

## Choosing a Board

| Priority | Recommendation |
|----------|----------------|
| Fastest inference overall | Apple Silicon (M1+ via Asahi Linux) |
| GPU-accelerated training | Jetson Orin Nano Super |
| Best value per dollar | RK3588 (Orange Pi 5 16GB ~$120) |
| Largest community support | Raspberry Pi 5 + AI HAT+ 2 |
| Large models (13B+) | Apple Silicon 16GB+ |
| Budget under $100 | RK3588 8GB (Orange Pi 5) |

See [Supported Boards](supported-boards.md) for full specifications.
