"""Data preparation tools for BMT AI OS training pipeline.

Converts raw datasets into a standardised JSONL format ready for LoRA/QLoRA
fine-tuning. Supported input formats:

- **alpaca**: JSON array of objects with ``instruction``, ``input`` (optional),
  and ``output`` fields.
- **sharegpt**: JSON array of objects with a ``conversations`` list where each
  entry has ``from`` (``"human"`` / ``"gpt"``) and ``value`` fields.
- **raw**: Plain-text file or JSONL where each line / object contains a
  ``"text"`` field (or is used as the raw text).

All formats are converted to a common JSONL output where every line is a JSON
object with a single ``"text"`` field formatted as a chat prompt.

Example::

    from bmt_ai_os.training.data_prep import prepare_dataset

    stats = prepare_dataset(
        input_path="data/alpaca_data.json",
        output_path="data/train.jsonl",
        format="alpaca",
    )
    print(stats)
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
from enum import Enum
from typing import Iterator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class DataFormat(str, Enum):
    """Supported input dataset formats."""

    ALPACA = "alpaca"
    SHAREGPT = "sharegpt"
    RAW = "raw"


@dataclasses.dataclass
class DataStats:
    """Statistics about a prepared dataset.

    Attributes:
        total_examples: Number of examples in the output file.
        skipped_examples: Examples that were dropped due to validation errors.
        format: The input format that was processed.
        input_path: Absolute path to the source file.
        output_path: Absolute path to the produced JSONL file.
        validation_errors: List of human-readable validation error messages.
    """

    total_examples: int
    skipped_examples: int
    format: str
    input_path: str
    output_path: str
    validation_errors: list[str] = dataclasses.field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"DataStats(format={self.format}, "
            f"total={self.total_examples}, "
            f"skipped={self.skipped_examples}, "
            f"errors={len(self.validation_errors)})"
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def prepare_dataset(
    input_path: str,
    output_path: str,
    format: str | DataFormat = DataFormat.ALPACA,  # noqa: A002  (shadow built-in intentionally)
) -> DataStats:
    """Convert a raw dataset file into a JSONL file ready for LoRA training.

    Parameters:
        input_path: Path to the source dataset file.
        output_path: Destination path for the output JSONL file. Parent
            directories are created automatically.
        format: One of ``"alpaca"``, ``"sharegpt"``, or ``"raw"``.

    Returns:
        A ``DataStats`` instance summarising conversion results.

    Raises:
        ValueError: If *format* is not recognised.
        FileNotFoundError: If *input_path* does not exist.
    """
    fmt = DataFormat(format) if not isinstance(format, DataFormat) else format

    abs_input = os.path.abspath(input_path)
    abs_output = os.path.abspath(output_path)

    if not os.path.exists(abs_input):
        raise FileNotFoundError(f"Input file not found: {abs_input}")

    os.makedirs(os.path.dirname(abs_output) or ".", exist_ok=True)

    logger.info("Preparing dataset: format=%s input=%s output=%s", fmt.value, abs_input, abs_output)

    errors: list[str] = []
    written = 0
    skipped = 0

    with open(abs_output, "w", encoding="utf-8") as out_fh:
        for idx, (text, err) in enumerate(_iter_examples(abs_input, fmt)):
            if err is not None:
                errors.append(f"example {idx}: {err}")
                skipped += 1
                continue
            if not text or not text.strip():
                errors.append(f"example {idx}: resulting text is empty after formatting")
                skipped += 1
                continue
            out_fh.write(json.dumps({"text": text}, ensure_ascii=False) + "\n")
            written += 1

    stats = DataStats(
        total_examples=written,
        skipped_examples=skipped,
        format=fmt.value,
        input_path=abs_input,
        output_path=abs_output,
        validation_errors=errors,
    )

    logger.info(
        "Dataset prepared: total=%d skipped=%d errors=%d",
        written,
        skipped,
        len(errors),
    )
    return stats


# ---------------------------------------------------------------------------
# Format-specific iterators
# ---------------------------------------------------------------------------


def _iter_examples(path: str, fmt: DataFormat) -> Iterator[tuple[str | None, str | None]]:
    """Yield ``(text, error)`` pairs for each example in the dataset file.

    Exactly one of *text* or *error* will be non-None per iteration.
    """
    if fmt == DataFormat.ALPACA:
        yield from _iter_alpaca(path)
    elif fmt == DataFormat.SHAREGPT:
        yield from _iter_sharegpt(path)
    elif fmt == DataFormat.RAW:
        yield from _iter_raw(path)
    else:
        raise ValueError(f"Unsupported format: {fmt}")


def _load_json_or_jsonl(path: str) -> list[dict]:
    """Load a file that is either a JSON array or a JSONL file."""
    with open(path, "r", encoding="utf-8") as fh:
        content = fh.read().strip()

    if content.startswith("["):
        # JSON array
        return json.loads(content)

    # JSONL — one JSON object per line
    records = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    return records


# ---------------------------------------------------------------------------
# Alpaca format
# ---------------------------------------------------------------------------

_ALPACA_PROMPT_WITH_INPUT = (
    "### Instruction:\n{instruction}\n\n### Input:\n{input}\n\n### Response:\n{output}"
)

_ALPACA_PROMPT_NO_INPUT = "### Instruction:\n{instruction}\n\n### Response:\n{output}"


def _iter_alpaca(path: str) -> Iterator[tuple[str | None, str | None]]:
    """Yield formatted text strings from an Alpaca-format dataset.

    Expected schema per record::

        {
            "instruction": "...",
            "input": "...",   // optional
            "output": "..."
        }
    """
    records = _load_json_or_jsonl(path)

    for record in records:
        instruction = (record.get("instruction") or "").strip()
        inp = (record.get("input") or "").strip()
        output = (record.get("output") or "").strip()

        # Validation
        if not instruction:
            yield None, "missing or empty 'instruction' field"
            continue
        if not output:
            yield None, "missing or empty 'output' field"
            continue

        if inp:
            text = _ALPACA_PROMPT_WITH_INPUT.format(
                instruction=instruction, input=inp, output=output
            )
        else:
            text = _ALPACA_PROMPT_NO_INPUT.format(instruction=instruction, output=output)

        yield text, None


# ---------------------------------------------------------------------------
# ShareGPT format
# ---------------------------------------------------------------------------


def _iter_sharegpt(path: str) -> Iterator[tuple[str | None, str | None]]:
    """Yield formatted text strings from a ShareGPT-format dataset.

    Expected schema per record::

        {
            "conversations": [
                {"from": "human", "value": "..."},
                {"from": "gpt",   "value": "..."},
                ...
            ]
        }
    """
    records = _load_json_or_jsonl(path)

    for record in records:
        conversations = record.get("conversations") or []

        if not conversations:
            yield None, "missing or empty 'conversations' field"
            continue

        parts: list[str] = []
        has_human = False
        has_gpt = False

        for turn in conversations:
            role = (turn.get("from") or turn.get("role") or "").strip().lower()
            value = (turn.get("value") or turn.get("content") or "").strip()

            if not role:
                continue
            if not value:
                continue

            if role in ("human", "user"):
                parts.append(f"### Human:\n{value}")
                has_human = True
            elif role in ("gpt", "assistant"):
                parts.append(f"### Assistant:\n{value}")
                has_gpt = True
            else:
                parts.append(f"### {role.capitalize()}:\n{value}")

        if not has_human:
            yield None, "conversation contains no human/user turn"
            continue
        if not has_gpt:
            yield None, "conversation contains no gpt/assistant turn"
            continue
        if not parts:
            yield None, "conversation produced no text after filtering"
            continue

        yield "\n\n".join(parts), None


# ---------------------------------------------------------------------------
# Raw format
# ---------------------------------------------------------------------------


def _iter_raw(path: str) -> Iterator[tuple[str | None, str | None]]:
    """Yield text strings from a raw text file or JSONL with a ``text`` field.

    If the file is a valid JSON array or JSONL, each record's ``"text"`` field
    is used. Otherwise, each non-empty line is treated as a separate example.
    """
    with open(path, "r", encoding="utf-8") as fh:
        content = fh.read().strip()

    # Try to parse as JSON / JSONL first
    try:
        records = _load_json_or_jsonl(path)
        for record in records:
            if isinstance(record, dict):
                text = (record.get("text") or "").strip()
                if not text:
                    yield None, "missing or empty 'text' field"
                    continue
                yield text, None
            elif isinstance(record, str):
                text = record.strip()
                if not text:
                    yield None, "empty string in JSON array"
                    continue
                yield text, None
            else:
                yield None, f"unexpected record type: {type(record).__name__}"
        return
    except (json.JSONDecodeError, ValueError):
        pass

    # Fall back to line-by-line text
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        yield line, None


# ---------------------------------------------------------------------------
# Validation helpers (exported for testing)
# ---------------------------------------------------------------------------


def validate_alpaca_record(record: dict) -> list[str]:
    """Return a list of validation error strings for an Alpaca record.

    An empty list means the record is valid.
    """
    errors: list[str] = []
    if not (record.get("instruction") or "").strip():
        errors.append("'instruction' field is missing or empty")
    if not (record.get("output") or "").strip():
        errors.append("'output' field is missing or empty")
    return errors


def validate_sharegpt_record(record: dict) -> list[str]:
    """Return a list of validation error strings for a ShareGPT record."""
    errors: list[str] = []
    conversations = record.get("conversations") or []
    if not conversations:
        errors.append("'conversations' field is missing or empty")
        return errors

    has_human = any(
        (t.get("from") or t.get("role") or "").lower() in ("human", "user") for t in conversations
    )
    has_gpt = any(
        (t.get("from") or t.get("role") or "").lower() in ("gpt", "assistant")
        for t in conversations
    )
    if not has_human:
        errors.append("no human/user turn found in conversation")
    if not has_gpt:
        errors.append("no gpt/assistant turn found in conversation")
    return errors
