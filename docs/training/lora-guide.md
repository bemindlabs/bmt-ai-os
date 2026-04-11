# LoRA Fine-Tuning Guide

This guide walks through the full process of fine-tuning a language model on BMT AI OS using LoRA (Low-Rank Adaptation) or QLoRA (quantised LoRA for memory-constrained devices).

## Prerequisites

- BMT AI OS with the Jupyter/training image installed, **or** a Python environment with the training dependencies:

  ```bash
  pip install torch transformers peft datasets tensorboard accelerate
  ```

- A prepared dataset in JSONL format (see [Data Preparation Guide](data-preparation.md)).
- At least 8 GB RAM for a 7B model (4 GB with QLoRA).

## Step 1 — Choose a Base Model

Use a Qwen2.5-Coder model for code tasks or any HuggingFace-compatible Causal LM:

```bash
# Small (512 MB, fits anywhere)
MODEL="Qwen/Qwen2.5-Coder-0.5B-Instruct"

# Medium (3 GB, good quality)
MODEL="Qwen/Qwen2.5-Coder-1.5B-Instruct"

# Large (14 GB FP16, use QLoRA on edge)
MODEL="Qwen/Qwen2.5-Coder-7B-Instruct"
```

## Step 2 — Prepare the Dataset

```bash
bmt-ai-os data-prepare \
  --input /path/to/raw_data.json \
  --output /var/lib/bmt/datasets/train.jsonl \
  --format alpaca
```

Expected output:

```
Preparing dataset: format=alpaca
  Input  : /path/to/raw_data.json
  Output : /var/lib/bmt/datasets/train.jsonl

Dataset prepared successfully.
  Examples written : 1500
  Examples skipped : 3
  Output file      : /var/lib/bmt/datasets/train.jsonl
```

## Step 3 — Run LoRA Training

### Standard LoRA (FP16)

```bash
bmt-ai-os train lora \
  --model Qwen/Qwen2.5-Coder-1.5B-Instruct \
  --data /var/lib/bmt/datasets/train.jsonl \
  --epochs 3 \
  --lr 2e-4 \
  --lora-rank 16 \
  --lora-alpha 32 \
  --batch-size 4 \
  --max-seq-length 2048
```

### QLoRA (4-bit, memory-efficient)

Add `--use-4bit` for QLoRA on devices with limited RAM:

```bash
bmt-ai-os train lora \
  --model Qwen/Qwen2.5-Coder-7B-Instruct \
  --data /var/lib/bmt/datasets/train.jsonl \
  --epochs 3 \
  --use-4bit \
  --lora-rank 64 \
  --batch-size 2
```

> **Note:** `--use-4bit` requires `bitsandbytes`. Install with `pip install bitsandbytes`.

### Using a Config File

For repeatable experiments, store parameters in a YAML file:

```yaml
# lora_config.yaml
learning_rate: 1e-4
epochs: 5
lora_rank: 32
lora_alpha: 64
batch_size: 2
max_seq_length: 4096
log_steps: 5
eval_steps: 50
```

```bash
bmt-ai-os train lora \
  --model Qwen/Qwen2.5-Coder-1.5B-Instruct \
  --data train.jsonl \
  --config lora_config.yaml
```

### Programmatic Usage

Use the Python API for integration with Jupyter notebooks or scripts:

```python
from bmt_ai_os.training.lora import LoRAConfig, LoRATrainer

config = LoRAConfig(
    model="Qwen/Qwen2.5-Coder-1.5B-Instruct",
    dataset_path="/var/lib/bmt/datasets/train.jsonl",
    epochs=3,
    lora_rank=16,
    lora_alpha=32,
    learning_rate=2e-4,
    batch_size=4,
    max_seq_length=2048,
    log_steps=10,
)

trainer = LoRATrainer(config)
trainer.train()

# Check results
progress = trainer.get_status()
print(f"Job ID  : {progress.job_id}")
print(f"Status  : {progress.status}")
print(f"Loss    : {progress.loss:.4f}")
print(f"Elapsed : {progress.elapsed_seconds:.0f}s")
```

## Step 4 — Monitor Training

### TensorBoard

```bash
tensorboard --logdir /var/lib/bmt/runs
# Open http://localhost:6006
```

Tracked metrics:

| Metric | TensorBoard tag |
|--------|----------------|
| Training loss | `train/loss` |
| Learning rate | `train/learning_rate` |
| Memory usage (MB) | `train/memory_mb` |
| Throughput (tok/s) | `train/tok_per_sec` |
| Evaluation loss | `eval/loss` |

### CLI Status

```bash
bmt-ai-os train status
```

## Step 5 — Use the Trained Adapter

Adapters are saved to `/var/lib/bmt/models/lora/{job_id}/adapter_final/`.

**Load with PEFT:**

```python
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline

JOB_ID = "your-job-id-here"
ADAPTER_PATH = f"/var/lib/bmt/models/lora/{JOB_ID}/adapter_final"
BASE_MODEL = "Qwen/Qwen2.5-Coder-1.5B-Instruct"

tokenizer = AutoTokenizer.from_pretrained(ADAPTER_PATH)
base = AutoModelForCausalLM.from_pretrained(BASE_MODEL, torch_dtype="auto")
model = PeftModel.from_pretrained(base, ADAPTER_PATH)

pipe = pipeline("text-generation", model=model, tokenizer=tokenizer)
result = pipe("### Instruction:\nExplain LoRA\n\n### Response:\n", max_new_tokens=200)
print(result[0]["generated_text"])
```

**Merge adapter into base model (optional):**

```python
merged = model.merge_and_unload()
merged.save_pretrained("/var/lib/bmt/models/merged/my-fine-tuned")
tokenizer.save_pretrained("/var/lib/bmt/models/merged/my-fine-tuned")
```

## LoRA Hyperparameter Reference

| Parameter | CLI flag | Recommended range | Notes |
|-----------|----------|------------------|-------|
| Learning rate | `--lr` | `1e-4` – `3e-4` | Higher for small datasets |
| Epochs | `--epochs` | 1 – 5 | More epochs risk overfitting |
| LoRA rank | `--lora-rank` | 8 – 64 | Higher rank = more capacity, more VRAM |
| LoRA alpha | `--lora-alpha` | 2× rank | Controls effective learning rate scaling |
| Batch size | `--batch-size` | 2 – 8 | Reduce if OOM; use gradient accumulation |
| Max seq length | `--max-seq-length` | 512 – 4096 | Longer = more context, more VRAM |

## Troubleshooting

**Out of memory (OOM):**
- Reduce `--batch-size` to 1 or 2.
- Enable `--use-4bit` (QLoRA).
- Reduce `--max-seq-length`.
- Use a smaller base model.

**Loss not decreasing:**
- Increase `--epochs`.
- Increase `--lora-rank`.
- Check dataset quality with `bmt-ai-os data-prepare` stats.
- Lower `--lr` if loss is unstable (NaN or spikes).

**ImportError on torch/peft:**
- You are running in the base OS image. Start the training container:
  ```bash
  docker run --rm -it -v /var/lib/bmt:/var/lib/bmt ghcr.io/bemindtech/bmt-ai-os-train:latest bash
  ```
