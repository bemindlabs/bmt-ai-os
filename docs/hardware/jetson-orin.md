# NVIDIA Jetson Orin Nano Super Setup

The Jetson Orin Nano Super is the only Tier 1 target with CUDA support, making it the best choice for GPU-accelerated inference and LoRA fine-tuning.

## Specifications

| Attribute | Value |
|-----------|-------|
| SoC | NVIDIA Jetson Orin (Ampere GPU) |
| Acceleration | 67 TOPS CUDA (1024 CUDA cores) |
| RAM | 8 GB unified (CPU + GPU shared) |
| Inference (7B Q4) | 15–22 tok/s |
| Training (LoRA 1.5B) | ~30 min with CUDA |
| Training (QLoRA 3B) | ~1 hr with CUDA |
| Price | ~$250 |

## Prerequisites

- Jetson Orin Nano Super Developer Kit
- microSD card (64GB+) or NVMe SSD (recommended)
- NVIDIA JetPack 6.x installed

## Installation

### 1. Flash JetPack

Download and flash JetPack 6.x using [SDK Manager](https://developer.nvidia.com/sdk-manager) or the command line:

```bash
# Using Balena Etcher or dd
sudo dd if=jetpack-6.x-arm64.img of=/dev/sdX bs=4M status=progress
```

### 2. Initial Setup

After first boot, complete the Ubuntu setup wizard. Then update the system:

```bash
sudo apt update && sudo apt upgrade -y
```

### 3. Install Docker with NVIDIA Runtime

JetPack includes `nvidia-container-runtime`. Enable it for Docker:

```bash
# Docker should already be installed with JetPack
sudo systemctl enable --now docker
sudo usermod -aG docker $USER

# Verify GPU access in containers
docker run --rm --runtime=nvidia nvcr.io/nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi
```

### 4. Deploy BMT AI OS

```bash
git clone https://github.com/bemindlabs/bmt-ai-os.git
cd bmt-ai-os

# Start with CUDA acceleration
docker compose -f docker-compose.dev.yml up -d
```

The dev compose automatically detects and uses the NVIDIA runtime.

### 5. Pull a Model

```bash
docker exec bmt-ollama ollama pull qwen2.5-coder:7b
```

## CUDA Configuration

Ollama uses CUDA automatically when running inside a container with `--runtime=nvidia`. No extra configuration is needed.

To verify GPU is being used:

```bash
# Check Ollama GPU usage
curl http://localhost:11434/api/tags | jq '.models[].details'

# Monitor GPU utilization during inference
tegrastats
```

## Performance Tips

- NVMe storage significantly improves model load time (vs. microSD)
- Use `OLLAMA_GPU_MEMORY_FRACTION=0.85` to leave headroom for the OS
- The 8GB unified memory limits you to 7B Q4 models comfortably
- For training, QLoRA 3B uses ~5-6GB VRAM — fits within the 8GB budget

## Training Workflow

```bash
# Start Jupyter Lab for interactive training
open http://localhost:8888  # token: bmtaios

# Or use the CLI
bmt_ai_os train --model qwen2.5-coder-1.5b --data ./my-dataset --method lora
```

## Known Issues

- JetPack 5.x is not supported; JetPack 6.x required
- Some PyTorch operations fall back to CPU if RKNN/Hailo drivers are missing (irrelevant here)
- `tegrastats` is the recommended monitoring tool (not `nvidia-smi`)
