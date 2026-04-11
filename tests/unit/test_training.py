"""Unit tests for bmt_ai_os.training.data_prep and bmt_ai_os.training.lora.

Covers the data preparation pipeline (BMTOS-81) and the LoRATrainer
configuration/status API (BMTOS-76) without requiring torch/peft/transformers.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from bmt_ai_os.training.data_prep import (
    DataFormat,
    prepare_dataset,
    validate_alpaca_record,
    validate_sharegpt_record,
)
from bmt_ai_os.training.lora import JobStatus, LoRAConfig, LoRATrainer, TrainingProgress

# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture()
def tmp_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture()
def alpaca_file(tmp_dir: Path) -> Path:
    """Write a small valid Alpaca JSON file and return its path."""
    data = [
        {"instruction": "Say hello", "input": "", "output": "Hello!"},
        {"instruction": "Add two numbers", "input": "2 + 3", "output": "5"},
        {"instruction": "Translate to French", "input": "cat", "output": "chat"},
    ]
    p = tmp_dir / "alpaca.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


@pytest.fixture()
def sharegpt_file(tmp_dir: Path) -> Path:
    """Write a small valid ShareGPT JSON file and return its path."""
    data = [
        {
            "conversations": [
                {"from": "human", "value": "What is 2+2?"},
                {"from": "gpt", "value": "4"},
            ]
        },
        {
            "conversations": [
                {"from": "human", "value": "Tell me a joke."},
                {"from": "gpt", "value": "Why did the chicken cross the road?"},
                {"from": "human", "value": "Why?"},
                {"from": "gpt", "value": "To get to the other side!"},
            ]
        },
    ]
    p = tmp_dir / "sharegpt.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


@pytest.fixture()
def raw_text_file(tmp_dir: Path) -> Path:
    """Write a plain-text file with one sentence per line."""
    lines = ["The quick brown fox.", "Jumps over the lazy dog.", "ARM64 is great."]
    p = tmp_dir / "raw.txt"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


@pytest.fixture()
def raw_jsonl_file(tmp_dir: Path) -> Path:
    """Write a JSONL file with 'text' fields."""
    records = [{"text": "Hello world"}, {"text": "BMT AI OS training"}]
    lines = [json.dumps(r) for r in records]
    p = tmp_dir / "raw.jsonl"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


# ===========================================================================
# Test 1 — prepare_dataset: alpaca format produces correct output
# ===========================================================================


def test_prepare_dataset_alpaca_basic(alpaca_file: Path, tmp_dir: Path) -> None:
    """prepare_dataset with alpaca format writes one JSONL line per example."""
    out = tmp_dir / "out.jsonl"
    stats = prepare_dataset(str(alpaca_file), str(out), format="alpaca")

    assert out.exists(), "Output file was not created"
    lines = [json.loads(ln) for ln in out.read_text().splitlines() if ln.strip()]
    assert len(lines) == 3
    assert stats.total_examples == 3
    assert stats.skipped_examples == 0
    assert all("text" in ln for ln in lines)


# ===========================================================================
# Test 2 — prepare_dataset: alpaca with input field uses correct template
# ===========================================================================


def test_prepare_dataset_alpaca_with_input_uses_template(alpaca_file: Path, tmp_dir: Path) -> None:
    """Records with a non-empty input field include '### Input:' in the prompt."""
    out = tmp_dir / "out.jsonl"
    prepare_dataset(str(alpaca_file), str(out), format="alpaca")
    lines = [json.loads(ln) for ln in out.read_text().splitlines() if ln.strip()]

    # Second record has "input": "2 + 3"
    assert "### Input:" in lines[1]["text"]
    assert "2 + 3" in lines[1]["text"]


# ===========================================================================
# Test 3 — prepare_dataset: alpaca without input omits Input section
# ===========================================================================


def test_prepare_dataset_alpaca_without_input_no_input_section(
    alpaca_file: Path, tmp_dir: Path
) -> None:
    """Records with empty input do not include '### Input:' in the prompt."""
    out = tmp_dir / "out.jsonl"
    prepare_dataset(str(alpaca_file), str(out), format="alpaca")
    lines = [json.loads(ln) for ln in out.read_text().splitlines() if ln.strip()]

    # First record has "input": ""
    assert "### Input:" not in lines[0]["text"]


# ===========================================================================
# Test 4 — prepare_dataset: sharegpt format
# ===========================================================================


def test_prepare_dataset_sharegpt(sharegpt_file: Path, tmp_dir: Path) -> None:
    """prepare_dataset with sharegpt format converts conversations correctly."""
    out = tmp_dir / "out.jsonl"
    stats = prepare_dataset(str(sharegpt_file), str(out), format="sharegpt")

    assert out.exists()
    lines = [json.loads(ln) for ln in out.read_text().splitlines() if ln.strip()]
    assert stats.total_examples == 2
    assert stats.skipped_examples == 0
    assert "### Human:" in lines[0]["text"]
    assert "### Assistant:" in lines[0]["text"]


# ===========================================================================
# Test 5 — prepare_dataset: raw plain-text format
# ===========================================================================


def test_prepare_dataset_raw_text(raw_text_file: Path, tmp_dir: Path) -> None:
    """prepare_dataset with raw format reads one example per non-empty line."""
    out = tmp_dir / "out.jsonl"
    stats = prepare_dataset(str(raw_text_file), str(out), format="raw")

    lines = [json.loads(ln) for ln in out.read_text().splitlines() if ln.strip()]
    assert stats.total_examples == 3
    assert lines[0]["text"] == "The quick brown fox."


# ===========================================================================
# Test 6 — prepare_dataset: raw JSONL format
# ===========================================================================


def test_prepare_dataset_raw_jsonl(raw_jsonl_file: Path, tmp_dir: Path) -> None:
    """prepare_dataset with raw format reads 'text' from JSONL records."""
    out = tmp_dir / "out.jsonl"
    stats = prepare_dataset(str(raw_jsonl_file), str(out), format="raw")

    lines = [json.loads(ln) for ln in out.read_text().splitlines() if ln.strip()]
    assert stats.total_examples == 2
    assert lines[0]["text"] == "Hello world"


# ===========================================================================
# Test 7 — prepare_dataset: skips invalid alpaca records and reports errors
# ===========================================================================


def test_prepare_dataset_skips_invalid_alpaca(tmp_dir: Path) -> None:
    """Records missing required fields are skipped and counted in skipped_examples."""
    data = [
        {"instruction": "Valid", "output": "response"},
        {"instruction": "", "output": "no instruction"},  # invalid
        {"instruction": "Missing output", "output": ""},  # invalid
        {"output": "no instruction key"},  # invalid
    ]
    in_file = tmp_dir / "bad.json"
    in_file.write_text(json.dumps(data))
    out = tmp_dir / "out.jsonl"

    stats = prepare_dataset(str(in_file), str(out), format="alpaca")

    assert stats.total_examples == 1
    assert stats.skipped_examples == 3
    assert len(stats.validation_errors) == 3


# ===========================================================================
# Test 8 — prepare_dataset: raises FileNotFoundError for missing input
# ===========================================================================


def test_prepare_dataset_raises_on_missing_file(tmp_dir: Path) -> None:
    """prepare_dataset raises FileNotFoundError when the input file does not exist."""
    with pytest.raises(FileNotFoundError, match="not found"):
        prepare_dataset("/nonexistent/path/data.json", str(tmp_dir / "out.jsonl"))


# ===========================================================================
# Test 9 — validate_alpaca_record: valid record returns no errors
# ===========================================================================


def test_validate_alpaca_record_valid() -> None:
    """A complete alpaca record produces no validation errors."""
    record = {"instruction": "Do something", "input": "context", "output": "result"}
    assert validate_alpaca_record(record) == []


# ===========================================================================
# Test 10 — validate_alpaca_record: detects missing fields
# ===========================================================================


def test_validate_alpaca_record_detects_missing_fields() -> None:
    """validate_alpaca_record flags missing instruction and output."""
    errors = validate_alpaca_record({"instruction": "", "output": ""})
    assert any("instruction" in e for e in errors)
    assert any("output" in e for e in errors)


# ===========================================================================
# Test 11 — validate_sharegpt_record: valid record returns no errors
# ===========================================================================


def test_validate_sharegpt_record_valid() -> None:
    """A valid ShareGPT record with human+gpt turns returns no errors."""
    record = {
        "conversations": [
            {"from": "human", "value": "Hi"},
            {"from": "gpt", "value": "Hello!"},
        ]
    }
    assert validate_sharegpt_record(record) == []


# ===========================================================================
# Test 12 — validate_sharegpt_record: flags missing gpt turn
# ===========================================================================


def test_validate_sharegpt_record_flags_missing_gpt() -> None:
    """validate_sharegpt_record flags records with only human turns."""
    record = {"conversations": [{"from": "human", "value": "Hi"}]}
    errors = validate_sharegpt_record(record)
    assert any("gpt" in e or "assistant" in e for e in errors)


# ===========================================================================
# Test 13 — DataFormat enum values
# ===========================================================================


def test_data_format_enum_values() -> None:
    """DataFormat enum exposes the three expected string values."""
    assert DataFormat.ALPACA.value == "alpaca"
    assert DataFormat.SHAREGPT.value == "sharegpt"
    assert DataFormat.RAW.value == "raw"


# ===========================================================================
# Test 14 — DataStats string representation
# ===========================================================================


def test_data_stats_str(tmp_dir: Path, alpaca_file: Path) -> None:
    """DataStats __str__ includes key counts and format name."""
    out = tmp_dir / "out.jsonl"
    stats = prepare_dataset(str(alpaca_file), str(out), format="alpaca")
    s = str(stats)
    assert "alpaca" in s
    assert "3" in s  # total examples


# ===========================================================================
# Test 15 — LoRAConfig defaults
# ===========================================================================


def test_lora_config_defaults() -> None:
    """LoRAConfig should have sensible default values."""
    cfg = LoRAConfig(model="test-model", dataset_path="/tmp/data.jsonl")
    assert cfg.learning_rate == pytest.approx(2e-4)
    assert cfg.epochs == 3
    assert cfg.lora_rank == 16
    assert cfg.lora_alpha == 32
    assert cfg.batch_size == 4
    assert cfg.max_seq_length == 2048
    assert cfg.use_4bit is False
    assert cfg.use_8bit is False


# ===========================================================================
# Test 16 — LoRATrainer initial status
# ===========================================================================


def test_lora_trainer_initial_status() -> None:
    """A freshly constructed LoRATrainer reports PENDING status."""
    cfg = LoRAConfig(model="test-model", dataset_path="/tmp/data.jsonl")
    trainer = LoRATrainer(cfg)
    progress = trainer.get_status()

    assert isinstance(progress, TrainingProgress)
    assert progress.status == JobStatus.PENDING
    assert progress.current_step == 0
    assert progress.loss is None
    assert progress.elapsed_seconds == pytest.approx(0.0, abs=0.5)


# ===========================================================================
# Test 17 — LoRATrainer job_id is a valid UUID string
# ===========================================================================


def test_lora_trainer_job_id_is_uuid() -> None:
    """LoRATrainer.job_id should be a non-empty string (UUID format)."""
    import re

    cfg = LoRAConfig(model="test-model", dataset_path="/tmp/data.jsonl")
    trainer = LoRATrainer(cfg)
    uuid_pattern = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    assert uuid_pattern.match(trainer.job_id), f"job_id is not a UUID: {trainer.job_id}"


# ===========================================================================
# Test 18 — LoRATrainer.train() raises ImportError when torch is missing
# ===========================================================================


def test_lora_trainer_train_raises_import_error_without_torch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LoRATrainer.train() raises ImportError with a helpful message when torch is unavailable."""
    import bmt_ai_os.training.lora as lora_mod

    monkeypatch.setattr(lora_mod, "_TORCH_AVAILABLE", False)
    monkeypatch.setattr(lora_mod, "_PEFT_AVAILABLE", False)
    monkeypatch.setattr(lora_mod, "_TRANSFORMERS_AVAILABLE", False)

    cfg = LoRAConfig(model="test-model", dataset_path="/tmp/data.jsonl")
    trainer = LoRATrainer(cfg)

    with pytest.raises(ImportError, match="pip install"):
        trainer.train()


# ===========================================================================
# Test 19 — prepare_dataset: output directory is created automatically
# ===========================================================================


def test_prepare_dataset_creates_output_directory(tmp_dir: Path, alpaca_file: Path) -> None:
    """prepare_dataset creates the parent directory of output_path if missing."""
    nested_out = tmp_dir / "nested" / "deep" / "out.jsonl"
    stats = prepare_dataset(str(alpaca_file), str(nested_out), format="alpaca")
    assert nested_out.exists()
    assert stats.total_examples > 0


# ===========================================================================
# Test 20 — prepare_dataset: DataStats contains correct paths
# ===========================================================================


def test_prepare_dataset_stats_paths(alpaca_file: Path, tmp_dir: Path) -> None:
    """DataStats.input_path and output_path should be absolute."""
    out = tmp_dir / "out.jsonl"
    stats = prepare_dataset(str(alpaca_file), str(out), format="alpaca")
    assert os.path.isabs(stats.input_path)
    assert os.path.isabs(stats.output_path)
    assert stats.format == "alpaca"


# ===========================================================================
# Test 21 — sharegpt with only human turns is skipped
# ===========================================================================


def test_sharegpt_human_only_turn_is_skipped(tmp_dir: Path) -> None:
    """ShareGPT records that only have human turns are skipped."""
    data = [
        {"conversations": [{"from": "human", "value": "Hello"}]},
    ]
    in_file = tmp_dir / "bad_sharegpt.json"
    in_file.write_text(json.dumps(data))
    out = tmp_dir / "out.jsonl"

    stats = prepare_dataset(str(in_file), str(out), format="sharegpt")
    assert stats.total_examples == 0
    assert stats.skipped_examples == 1


# ===========================================================================
# Test 22 — multi-turn sharegpt conversation formats correctly
# ===========================================================================


def test_sharegpt_multi_turn_conversation(tmp_dir: Path) -> None:
    """Multi-turn ShareGPT conversations produce all turns in the output text."""
    data = [
        {
            "conversations": [
                {"from": "human", "value": "Turn 1"},
                {"from": "gpt", "value": "Reply 1"},
                {"from": "human", "value": "Turn 2"},
                {"from": "gpt", "value": "Reply 2"},
            ]
        }
    ]
    in_file = tmp_dir / "multi.json"
    in_file.write_text(json.dumps(data))
    out = tmp_dir / "out.jsonl"
    stats = prepare_dataset(str(in_file), str(out), format="sharegpt")

    assert stats.total_examples == 1
    line = json.loads(out.read_text().splitlines()[0])
    assert "Turn 1" in line["text"]
    assert "Reply 2" in line["text"]
