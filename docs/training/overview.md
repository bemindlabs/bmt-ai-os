# On-Device Training Overview

BMT AI OS supports parameter-efficient fine-tuning (PEFT) of language models directly on ARM64 hardware. The training subsystem is designed to run without an internet connection after the initial model download.

## Supported Training Methods

| Method | Description | VRAM / RAM requirement |
|--------|-------------|------------------------|
| LoRA   | Low-Rank Adaptation — injects small trainable matrices into existing attention layers | ~8 GB RAM (7B model) |
| QLoRA  | Quantised LoRA — loads model in 4-bit or 8-bit precision before applying LoRA adapters | ~4 GB RAM (7B model) |

Both methods produce lightweight adapter files (typically 10–100 MB) that can be merged back into the base model or loaded on-the-fly with PEFT.

## Requirements

### Software

Install the training dependencies (available in the BMT Jupyter/training container image):

```bash
pip install torch transformers peft datasets tensorboard accelerate
# For QLoRA 4-bit / 8-bit:
pip install bitsandbytes
```

Or pull the pre-built training image:

```bash
docker pull ghcr.io/bemindtech/bmt-ai-os-train:latest
```

### Hardware

| Target | Notes |
|--------|-------|
| Apple Silicon (M3/M4) | CPU-only on Linux; use `mps` device on macOS |
| Jetson Orin Nano Super | CUDA available; fastest option for fine-tuning |
| RK3588 boards | CPU-only; use smaller models (1B–3B) |
| Raspberry Pi 5 + Hailo | CPU-only for training; Hailo is for inference only |

### Recommended Models for On-Device Training

- `Qwen/Qwen2.5-Coder-0.5B-Instruct` — fits on any target, fastest
- `Qwen/Qwen2.5-Coder-1.5B-Instruct` — good balance on 8 GB RAM
- `Qwen/Qwen2.5-Coder-7B-Instruct` — best quality; requires QLoRA on smaller devices

## Quick Start

### 1. Prepare your dataset

```bash
bmt-ai-os data-prepare \
  --input my_data.json \
  --output train.jsonl \
  --format alpaca
```

### 2. Start LoRA training

```bash
bmt-ai-os train lora \
  --model Qwen/Qwen2.5-Coder-1.5B-Instruct \
  --data train.jsonl \
  --epochs 3 \
  --lora-rank 16
```

### 3. Monitor with TensorBoard

```bash
tensorboard --logdir /var/lib/bmt/runs
```

Browse to `http://localhost:6006`.

### 4. Use the adapter

After training, the adapter is saved to `/var/lib/bmt/models/lora/{job_id}/adapter_final/`. Load it with PEFT:

```python
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

base = AutoModelForCausalLM.from_pretrained("Qwen/Qwen2.5-Coder-1.5B-Instruct")
model = PeftModel.from_pretrained(base, "/var/lib/bmt/models/lora/<job_id>/adapter_final")
```

## Architecture

```
bmt_ai_os/training/
├── __init__.py       Public API re-exports
├── lora.py           LoRATrainer class + LoRAConfig dataclass
└── data_prep.py      prepare_dataset() + format converters
```

The training module integrates with the CLI (`bmt-ai-os train`, `bmt-ai-os data-prepare`) and writes TensorBoard event files to `/var/lib/bmt/runs/{job_id}/`.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BMT_TRAINING_RUNS` | `/var/lib/bmt/runs` | Root directory for TensorBoard run logs |

## Limitations

- Training on CPU is slow. A 7B model with a 1000-example dataset can take hours on ARM64 without GPU.
- QLoRA requires `bitsandbytes`, which has limited ARM64 support outside of CUDA devices.
- Model merging (adapter → full weights) is not yet integrated into the CLI; use PEFT's `merge_and_unload()` directly.
