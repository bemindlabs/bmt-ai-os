# Apple Silicon Setup (M1–M4, Asahi Linux)

Apple Silicon is the fastest ARM64 CPU inference platform supported by BMT AI OS. It runs under Asahi Linux (CPU-only — no Metal GPU support on Linux yet).

## Specifications

| Attribute | Value |
|-----------|-------|
| Architecture | ARM64 (aarch64) |
| Acceleration | CPU-only (ARM NEON) |
| RAM | 8–192 GB unified memory |
| Inference (7B Q4) | 30–50 tok/s |
| Inference (13B Q4, 16GB+) | 15–22 tok/s |
| Training (LoRA 3B) | ~20 min CPU |
| Training (QLoRA 3B) | ~30 min CPU |

!!! note "GPU acceleration"
    Apple's GPU driver for Linux (Asahi DRM) does not yet support compute workloads. All inference runs on CPU via ARM NEON SIMD. Despite this, Apple Silicon CPUs are the fastest option for ARM64 CPU inference due to their unified memory bandwidth.

## Prerequisites

- Apple Silicon Mac (M1, M2, M3, or M4 chip)
- [Asahi Linux](https://asahilinux.org/) installed (minimal or desktop)
- 16GB+ RAM recommended for 7B models; 32GB+ for 13B models

## Installation

### 1. Install Asahi Linux

Follow the [Asahi Linux installer guide](https://asahilinux.org/). The minimal install is sufficient for BMT AI OS.

```bash
curl https://alx.sh | sh
```

### 2. Install Docker

Asahi Linux ships with Fedora. Install Docker using the official repository:

```bash
sudo dnf install -y docker docker-compose
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```

### 3. Deploy BMT AI OS

```bash
git clone https://github.com/bemindlabs/bmt-ai-os.git
cd bmt-ai-os

# Start the full stack
docker compose -f docker-compose.dev.yml up -d
```

### 4. Pull a Model

Apple Silicon can run larger models comfortably:

```bash
# 7B — recommended for 8GB RAM
docker exec bmt-ollama ollama pull qwen2.5-coder:7b

# 13B — recommended for 16GB+ RAM
docker exec bmt-ollama ollama pull qwen2.5-coder:14b
```

## Performance Tips

- Use Q4_K_M quantization for best quality/size trade-off
- Unified memory means no VRAM cap — use as much RAM as your model needs
- Set `OLLAMA_NUM_PARALLEL=1` on 8GB to avoid OOM with concurrent requests
- For 32GB+ machines, Q8_0 quantization improves quality with minimal speed penalty

## Model Presets

| Preset | Model | Size | RAM Required |
|--------|-------|------|--------------|
| Lite | Qwen3.5-9B Q4 | ~6GB | 8GB |
| Standard | Qwen2.5-Coder-7B Q4 + embedding | ~8GB | 16GB |
| Full | Qwen3.5-27B Q4 + embedding | ~18GB | 32GB |

## Known Limitations

- No GPU compute — Apple GPU driver is incomplete for Linux
- No NPU passthrough — Neural Engine not exposed to Linux userspace
- Power management may be aggressive; pin CPU frequency for stable inference benchmarks
