"""LoRA/QLoRA fine-tuning module for BMT AI OS.

Provides the ``LoRATrainer`` class which wraps PyTorch + PEFT to run parameter-
efficient fine-tuning on ARM64 devices. All heavy dependencies (torch, peft,
transformers) are imported conditionally so the module can be imported in
environments where only the base OS image is installed.

TensorBoard metrics are written to ``/var/lib/bmt/runs/{job_id}/`` (override
with the ``BMT_TRAINING_RUNS`` environment variable).

Example::

    config = LoRAConfig(
        model="Qwen/Qwen2.5-Coder-7B-Instruct",
        dataset_path="/data/train.jsonl",
        epochs=3,
        lora_rank=16,
    )
    trainer = LoRATrainer(config)
    trainer.train()
    print(trainer.get_status())
"""

from __future__ import annotations

import dataclasses
import logging
import os
import time
import uuid
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional heavy-dependency imports
# ---------------------------------------------------------------------------

_TORCH_AVAILABLE = False
_PEFT_AVAILABLE = False
_TRANSFORMERS_AVAILABLE = False
_TENSORBOARD_AVAILABLE = False

try:
    import torch  # type: ignore[import-untyped]

    _TORCH_AVAILABLE = True
except ImportError:
    torch = None  # type: ignore[assignment]

try:
    import peft  # type: ignore[import-untyped]
    from peft import LoraConfig as PeftLoraConfig  # type: ignore[import-untyped]
    from peft import TaskType, get_peft_model  # type: ignore[import-untyped]

    _PEFT_AVAILABLE = True
except ImportError:
    peft = None  # type: ignore[assignment]
    PeftLoraConfig = None  # type: ignore[assignment]
    TaskType = None  # type: ignore[assignment]
    get_peft_model = None  # type: ignore[assignment]

try:
    import transformers  # type: ignore[import-untyped]
    from transformers import (  # type: ignore[import-untyped]
        AutoModelForCausalLM,
        AutoTokenizer,
        TrainingArguments,
    )

    _TRANSFORMERS_AVAILABLE = True
except ImportError:
    transformers = None  # type: ignore[assignment]
    AutoModelForCausalLM = None  # type: ignore[assignment]
    AutoTokenizer = None  # type: ignore[assignment]
    TrainingArguments = None  # type: ignore[assignment]

try:
    from torch.utils.tensorboard import SummaryWriter  # type: ignore[import-untyped]

    _TENSORBOARD_AVAILABLE = True
except ImportError:
    SummaryWriter = None  # type: ignore[assignment]


def _require_torch() -> None:
    """Raise a descriptive ImportError if torch/peft/transformers are missing."""
    missing = []
    if not _TORCH_AVAILABLE:
        missing.append("torch")
    if not _PEFT_AVAILABLE:
        missing.append("peft")
    if not _TRANSFORMERS_AVAILABLE:
        missing.append("transformers")
    if missing:
        pkg_list = " ".join(missing)
        raise ImportError(
            f"LoRA training requires: {pkg_list}. "
            "These packages are available in the BMT AI OS Jupyter/training image. "
            f"Install with: pip install {pkg_list}"
        )


# ---------------------------------------------------------------------------
# Data classes / enums
# ---------------------------------------------------------------------------


class JobStatus(str, Enum):
    """Possible states of a training job."""

    PENDING = "pending"
    CONFIGURING = "configuring"
    TRAINING = "training"
    EVALUATING = "evaluating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclasses.dataclass
class LoRAConfig:
    """Configuration for a LoRA/QLoRA training run.

    Attributes:
        model: HuggingFace model ID or local path (e.g. ``Qwen/Qwen2.5-Coder-7B-Instruct``).
        dataset_path: Path to a JSONL training file produced by ``prepare_dataset``.
        output_dir: Directory to save adapter weights and checkpoints.
        log_dir: Override TensorBoard log directory (defaults to BMT_TRAINING_RUNS/{job_id}).
        learning_rate: AdamW learning rate.
        epochs: Number of full passes over the dataset.
        lora_rank: LoRA rank ``r``.
        lora_alpha: LoRA scaling factor ``alpha``.
        lora_dropout: Dropout applied to LoRA layers.
        batch_size: Per-device training batch size.
        gradient_accumulation_steps: Steps before an optimiser update.
        max_seq_length: Maximum token sequence length (longer samples are truncated).
        eval_steps: Run evaluation every N steps (0 = no mid-training eval).
        log_steps: Log TensorBoard scalars every N steps.
        save_steps: Save checkpoint every N steps (0 = only at end).
        use_4bit: Enable QLoRA 4-bit quantisation (requires bitsandbytes).
        use_8bit: Enable 8-bit quantisation (requires bitsandbytes).
        target_modules: LoRA target module names (None = auto-detect).
        seed: Random seed for reproducibility.
    """

    model: str
    dataset_path: str
    output_dir: str = "/var/lib/bmt/models/lora"
    log_dir: str | None = None
    learning_rate: float = 2e-4
    epochs: int = 3
    lora_rank: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    batch_size: int = 4
    gradient_accumulation_steps: int = 4
    max_seq_length: int = 2048
    eval_steps: int = 0
    log_steps: int = 10
    save_steps: int = 0
    use_4bit: bool = False
    use_8bit: bool = False
    target_modules: list[str] | None = None
    seed: int = 42


@dataclasses.dataclass
class TrainingProgress:
    """Snapshot of training progress at a given moment.

    Attributes:
        job_id: Unique identifier for this training run.
        status: Current ``JobStatus``.
        current_step: Training steps completed so far.
        total_steps: Total steps planned for the run.
        current_epoch: Epoch currently being processed (1-indexed).
        total_epochs: Total epochs configured.
        loss: Most recent training loss (None before first log).
        eval_loss: Most recent evaluation loss (None if eval not run).
        learning_rate: Current learning rate.
        throughput_tok_per_sec: Token throughput (None until first measurement).
        memory_mb: Peak GPU/CPU memory in MB (None if unavailable).
        elapsed_seconds: Wall-clock seconds since training started.
        estimated_remaining_seconds: Estimated seconds until completion (None if unknown).
    """

    job_id: str
    status: JobStatus
    current_step: int = 0
    total_steps: int = 0
    current_epoch: int = 0
    total_epochs: int = 0
    loss: float | None = None
    eval_loss: float | None = None
    learning_rate: float | None = None
    throughput_tok_per_sec: float | None = None
    memory_mb: float | None = None
    elapsed_seconds: float = 0.0
    estimated_remaining_seconds: float | None = None


# ---------------------------------------------------------------------------
# LoRATrainer
# ---------------------------------------------------------------------------


class LoRATrainer:
    """Orchestrates LoRA/QLoRA fine-tuning using PyTorch + PEFT + Transformers.

    The trainer follows a simple lifecycle::

        trainer = LoRATrainer(config)
        trainer.configure(model_obj, dataset_obj, config)  # optional manual setup
        trainer.train()
        status = trainer.get_status()

    If ``configure`` is not called explicitly, ``train()`` will call it
    automatically using the paths in ``LoRAConfig``.

    All TensorBoard logs are written by the private ``_writer`` attribute so
    the SummaryWriter lifecycle is tied to this object.
    """

    def __init__(self, config: LoRAConfig) -> None:
        self._config = config
        self._job_id: str = str(uuid.uuid4())
        self._status: JobStatus = JobStatus.PENDING
        self._progress: TrainingProgress = TrainingProgress(
            job_id=self._job_id,
            status=self._status,
            total_epochs=config.epochs,
        )
        self._start_time: float | None = None
        self._writer: Any = None  # SummaryWriter when available
        self._model: Any = None
        self._tokenizer: Any = None
        self._dataset: Any = None
        self._is_configured: bool = False

        logger.info("LoRATrainer created job_id=%s model=%s", self._job_id, config.model)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def job_id(self) -> str:
        """Unique ID assigned to this training run."""
        return self._job_id

    def configure(
        self,
        model: Any | None = None,
        dataset: Any | None = None,
        config: LoRAConfig | None = None,
    ) -> None:
        """Prepare the model, tokenizer, PEFT adapter, and TensorBoard writer.

        Parameters:
            model: Pre-loaded HuggingFace model object (None = load from config.model).
            dataset: Pre-loaded dataset object (None = load from config.dataset_path).
            config: Alternate config to use instead of the one passed at construction.

        Raises:
            ImportError: If torch, peft, or transformers are not installed.
        """
        _require_torch()

        if config is not None:
            self._config = config

        self._set_status(JobStatus.CONFIGURING)
        cfg = self._config

        # --- TensorBoard writer --------------------------------------------
        runs_root = os.environ.get("BMT_TRAINING_RUNS", "/var/lib/bmt/runs")
        log_dir = cfg.log_dir or os.path.join(runs_root, self._job_id)
        os.makedirs(log_dir, exist_ok=True)

        if _TENSORBOARD_AVAILABLE:
            self._writer = SummaryWriter(log_dir=log_dir)
            logger.info("TensorBoard logs -> %s", log_dir)
        else:
            logger.warning(
                "tensorboard not installed; metrics will not be persisted. "
                "Install with: pip install tensorboard"
            )

        # --- Tokenizer -----------------------------------------------------
        if self._tokenizer is None:
            logger.info("Loading tokenizer for %s", cfg.model)
            self._tokenizer = AutoTokenizer.from_pretrained(
                cfg.model,
                trust_remote_code=True,
                padding_side="right",
            )
            if self._tokenizer.pad_token is None:
                self._tokenizer.pad_token = self._tokenizer.eos_token

        # --- Base model ----------------------------------------------------
        if model is not None:
            self._model = model
        elif self._model is None:
            logger.info("Loading base model %s", cfg.model)
            load_kwargs: dict[str, Any] = {
                "trust_remote_code": True,
                "torch_dtype": torch.float16 if torch is not None else None,
            }
            if cfg.use_4bit:
                try:
                    from transformers import BitsAndBytesConfig  # type: ignore[import-untyped]

                    load_kwargs["quantization_config"] = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_use_double_quant=True,
                        bnb_4bit_quant_type="nf4",
                        bnb_4bit_compute_dtype=torch.bfloat16,
                    )
                except ImportError as exc:
                    raise ImportError(
                        "4-bit quantisation requires bitsandbytes: pip install bitsandbytes"
                    ) from exc
            elif cfg.use_8bit:
                load_kwargs["load_in_8bit"] = True

            self._model = AutoModelForCausalLM.from_pretrained(cfg.model, **load_kwargs)

        # --- PEFT / LoRA adapter -------------------------------------------
        target_modules = cfg.target_modules or _auto_target_modules(self._model)
        peft_config = PeftLoraConfig(
            task_type=TaskType.CAUSAL_LM,
            r=cfg.lora_rank,
            lora_alpha=cfg.lora_alpha,
            lora_dropout=cfg.lora_dropout,
            target_modules=target_modules,
            bias="none",
        )
        self._model = get_peft_model(self._model, peft_config)
        self._model.print_trainable_parameters()

        # --- Dataset -------------------------------------------------------
        if dataset is not None:
            self._dataset = dataset
        elif self._dataset is None:
            self._dataset = _load_jsonl_dataset(cfg.dataset_path, self._tokenizer, cfg)

        self._is_configured = True
        logger.info("LoRATrainer configured — job_id=%s", self._job_id)

    def train(self) -> None:
        """Execute the training loop.

        Calls ``configure()`` automatically if not already done.

        Raises:
            ImportError: If torch/peft/transformers are not installed.
            RuntimeError: If the trainer encounters an unrecoverable error.
        """
        _require_torch()

        if not self._is_configured:
            self.configure()

        self._start_time = time.monotonic()

        try:
            self._set_status(JobStatus.TRAINING)
            self._run_training_loop()
            self._set_status(JobStatus.COMPLETED)
            logger.info("Training completed — job_id=%s", self._job_id)
        except Exception as exc:
            self._set_status(JobStatus.FAILED)
            logger.error("Training failed job_id=%s: %s", self._job_id, exc, exc_info=True)
            raise
        finally:
            if self._writer is not None:
                try:
                    self._writer.close()
                except Exception:
                    pass

    def get_status(self) -> TrainingProgress:
        """Return a snapshot of current training progress.

        Returns:
            A ``TrainingProgress`` dataclass with all available metrics.
        """
        if self._start_time is not None:
            self._progress.elapsed_seconds = time.monotonic() - self._start_time

            # Estimate remaining time
            step = self._progress.current_step
            total = self._progress.total_steps
            elapsed = self._progress.elapsed_seconds
            if step > 0 and total > 0 and elapsed > 0:
                rate = step / elapsed  # steps/sec
                remaining_steps = total - step
                self._progress.estimated_remaining_seconds = (
                    remaining_steps / rate if rate > 0 else None
                )

        self._progress.status = self._status
        return self._progress

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _set_status(self, status: JobStatus) -> None:
        self._status = status
        self._progress.status = status

    def _run_training_loop(self) -> None:
        """Inner training loop using HuggingFace Trainer."""
        cfg = self._config

        output_dir = os.path.join(cfg.output_dir, self._job_id)
        os.makedirs(output_dir, exist_ok=True)

        training_args = TrainingArguments(
            output_dir=output_dir,
            num_train_epochs=cfg.epochs,
            per_device_train_batch_size=cfg.batch_size,
            gradient_accumulation_steps=cfg.gradient_accumulation_steps,
            learning_rate=cfg.learning_rate,
            fp16=True,
            logging_steps=cfg.log_steps,
            save_steps=cfg.save_steps if cfg.save_steps > 0 else cfg.epochs * 9999,
            eval_steps=cfg.eval_steps if cfg.eval_steps > 0 else None,
            evaluation_strategy="steps" if cfg.eval_steps > 0 else "no",
            seed=cfg.seed,
            report_to=[],  # disable HF integrations; we write TensorBoard manually
            dataloader_drop_last=True,
        )

        # Split dataset for eval if eval_steps configured
        train_dataset = self._dataset
        eval_dataset = None
        if cfg.eval_steps > 0 and hasattr(self._dataset, "train_test_split"):
            split = self._dataset.train_test_split(test_size=0.1, seed=cfg.seed)
            train_dataset = split["train"]
            eval_dataset = split["test"]

        # Estimate total steps
        steps_per_epoch = max(
            1,
            len(train_dataset) // (cfg.batch_size * cfg.gradient_accumulation_steps),
        )
        total_steps = steps_per_epoch * cfg.epochs
        self._progress.total_steps = total_steps
        self._progress.total_epochs = cfg.epochs

        logger.info(
            "Training: steps_per_epoch=%d total_steps=%d",
            steps_per_epoch,
            total_steps,
        )

        try:
            from transformers import (
                DataCollatorForSeq2Seq,  # type: ignore[import-untyped]
                Trainer,  # type: ignore[import-untyped]
            )
        except ImportError as exc:
            raise ImportError("transformers Trainer not available") from exc

        data_collator = DataCollatorForSeq2Seq(
            tokenizer=self._tokenizer,
            model=self._model,
            padding=True,
            pad_to_multiple_of=8,
        )

        # Wrap the HF Trainer with our progress-tracking callback
        callback = _ProgressCallback(
            trainer_obj=self,
            log_steps=cfg.log_steps,
        )

        trainer = Trainer(
            model=self._model,
            args=training_args,
            train_dataset=train_dataset,
            eval_dataset=eval_dataset,
            data_collator=data_collator,
            callbacks=[callback],
        )

        trainer.train()

        # Save final adapter
        adapter_path = os.path.join(output_dir, "adapter_final")
        self._model.save_pretrained(adapter_path)
        self._tokenizer.save_pretrained(adapter_path)
        logger.info("Adapter saved -> %s", adapter_path)

        # Write hparams summary to TensorBoard
        if self._writer is not None:
            self._writer.add_hparams(
                hparam_dict={
                    "model": cfg.model,
                    "learning_rate": cfg.learning_rate,
                    "epochs": cfg.epochs,
                    "lora_rank": cfg.lora_rank,
                    "lora_alpha": cfg.lora_alpha,
                    "batch_size": cfg.batch_size,
                    "max_seq_length": cfg.max_seq_length,
                    "use_4bit": cfg.use_4bit,
                    "use_8bit": cfg.use_8bit,
                },
                metric_dict={
                    "final_loss": self._progress.loss or 0.0,
                    "final_eval_loss": self._progress.eval_loss or 0.0,
                },
            )
            self._writer.flush()

    def _log_step_metrics(
        self,
        step: int,
        loss: float,
        lr: float,
        tok_per_sec: float | None,
        memory_mb: float | None,
    ) -> None:
        """Write scalar metrics to TensorBoard and update progress."""
        self._progress.current_step = step
        self._progress.loss = loss
        self._progress.learning_rate = lr
        self._progress.throughput_tok_per_sec = tok_per_sec
        self._progress.memory_mb = memory_mb

        if self._writer is not None:
            self._writer.add_scalar("train/loss", loss, step)
            self._writer.add_scalar("train/learning_rate", lr, step)
            if memory_mb is not None:
                self._writer.add_scalar("train/memory_mb", memory_mb, step)
            if tok_per_sec is not None:
                self._writer.add_scalar("train/tok_per_sec", tok_per_sec, step)

    def _log_eval_metrics(self, step: int, eval_loss: float) -> None:
        """Write evaluation loss to TensorBoard and update progress."""
        self._progress.eval_loss = eval_loss
        if self._writer is not None:
            self._writer.add_scalar("eval/loss", eval_loss, step)


# ---------------------------------------------------------------------------
# HuggingFace Trainer callback
# ---------------------------------------------------------------------------


class _ProgressCallback:
    """HuggingFace TrainerCallback that updates LoRATrainer's progress."""

    def __init__(self, trainer_obj: LoRATrainer, log_steps: int) -> None:
        self._trainer_obj = trainer_obj
        self._log_steps = log_steps
        self._step_start_time: float = time.monotonic()
        self._step_start_tokens: int = 0

    def on_log(
        self, args: Any, state: Any, control: Any, logs: dict | None = None, **kwargs: Any
    ) -> None:
        """Called by HF Trainer each time logs are emitted."""
        if logs is None:
            return

        step = state.global_step
        loss = logs.get("loss", 0.0)
        lr = logs.get("learning_rate", 0.0)

        # Throughput estimation
        now = time.monotonic()
        tok_per_sec: float | None = None
        if _TORCH_AVAILABLE and torch is not None:
            elapsed = now - self._step_start_time
            if elapsed > 0:
                # approximate: batch_size * log_steps * max_seq_length tokens
                cfg = self._trainer_obj._config
                tokens = cfg.batch_size * self._log_steps * cfg.max_seq_length
                tok_per_sec = tokens / elapsed
        self._step_start_time = now

        # Memory usage
        memory_mb: float | None = None
        if _TORCH_AVAILABLE and torch is not None and torch.cuda.is_available():
            memory_mb = torch.cuda.max_memory_allocated() / 1_048_576

        # Epoch tracking
        self._trainer_obj._progress.current_epoch = int(state.epoch or 0)

        self._trainer_obj._log_step_metrics(step, loss, lr, tok_per_sec, memory_mb)

    def on_evaluate(
        self,
        args: Any,
        state: Any,
        control: Any,
        metrics: dict | None = None,
        **kwargs: Any,
    ) -> None:
        """Called by HF Trainer after each evaluation pass."""
        if metrics is None:
            return
        eval_loss = metrics.get("eval_loss", 0.0)
        self._trainer_obj._set_status(JobStatus.EVALUATING)
        self._trainer_obj._log_eval_metrics(state.global_step, eval_loss)
        self._trainer_obj._set_status(JobStatus.TRAINING)


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def _auto_target_modules(model: Any) -> list[str]:
    """Heuristically detect LoRA target module names from the model architecture.

    Falls back to common Qwen/LLaMA names if detection fails.
    """
    defaults = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
    if model is None:
        return defaults
    try:
        names = {name for name, _ in model.named_modules()}
        candidates = ["q_proj", "k_proj", "v_proj", "o_proj", "query_key_value", "dense"]
        found = [c for c in candidates if any(c in n for n in names)]
        return found if found else defaults
    except Exception:
        return defaults


def _load_jsonl_dataset(path: str, tokenizer: Any, cfg: LoRAConfig) -> Any:
    """Load a JSONL file into a HuggingFace Dataset and tokenize it.

    The JSONL file must contain objects with a ``"text"`` field (as produced by
    ``prepare_dataset``).

    Raises:
        ImportError: If ``datasets`` package is not installed.
        FileNotFoundError: If *path* does not exist.
    """
    import os as _os

    if not _os.path.exists(path):
        raise FileNotFoundError(f"Dataset not found: {path}")

    try:
        from datasets import load_dataset  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "The 'datasets' package is required for training: pip install datasets"
        ) from exc

    raw = load_dataset("json", data_files={"train": path}, split="train")

    def _tokenize(examples: dict) -> dict:
        return tokenizer(
            examples["text"],
            truncation=True,
            max_length=cfg.max_seq_length,
            padding=False,
        )

    tokenized = raw.map(_tokenize, batched=True, remove_columns=raw.column_names)
    tokenized = tokenized.map(lambda ex: {"labels": ex["input_ids"]}, batched=True)
    return tokenized
