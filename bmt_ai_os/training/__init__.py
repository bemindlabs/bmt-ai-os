"""BMT AI OS Training module.

Provides LoRA/QLoRA fine-tuning, data preparation, and training orchestration
for on-device model training. Requires the Jupyter/training image with PyTorch,
Hugging Face Transformers, and PEFT installed.

Typical usage::

    from bmt_ai_os.training.lora import LoRATrainer, LoRAConfig
    from bmt_ai_os.training.data_prep import prepare_dataset

    # Prepare data
    stats = prepare_dataset("data/raw.json", "data/train.jsonl", format="alpaca")

    # Configure and run training
    config = LoRAConfig(model="qwen2.5-coder:7b", dataset_path="data/train.jsonl")
    trainer = LoRATrainer(config)
    trainer.train()
"""

from bmt_ai_os.training.data_prep import DataFormat, DataStats, prepare_dataset
from bmt_ai_os.training.lora import JobStatus, LoRAConfig, LoRATrainer, TrainingProgress

__all__ = [
    "DataFormat",
    "DataStats",
    "JobStatus",
    "LoRAConfig",
    "LoRATrainer",
    "TrainingProgress",
    "prepare_dataset",
]
