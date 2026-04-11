# Dataset Preparation Guide

BMT AI OS includes a dataset preparation tool that converts common dataset formats into the JSONL format required by the LoRA training pipeline.

## Supported Formats

### Alpaca

The Alpaca format uses a JSON array where each object has:
- `instruction` (required) — the task description
- `input` (optional) — additional context or sample input
- `output` (required) — the expected response

```json
[
  {
    "instruction": "Write a Python function to reverse a string.",
    "input": "",
    "output": "def reverse_string(s: str) -> str:\n    return s[::-1]"
  },
  {
    "instruction": "Translate the following to French.",
    "input": "Good morning",
    "output": "Bonjour"
  }
]
```

Records with empty `instruction` or `output` fields are skipped and reported in the conversion stats.

### ShareGPT

The ShareGPT format stores multi-turn conversations. Each object has a `conversations` list where turns alternate between `human` and `gpt` roles:

```json
[
  {
    "conversations": [
      {"from": "human", "value": "How do I reverse a list in Python?"},
      {"from": "gpt",   "value": "You can reverse a list using `my_list[::-1]` or `my_list.reverse()`."},
      {"from": "human", "value": "What is the difference between the two?"},
      {"from": "gpt",   "value": "`[::-1]` creates a new list; `.reverse()` modifies in-place."}
    ]
  }
]
```

Accepted role names:
- Human turn: `human` or `user`
- Assistant turn: `gpt` or `assistant`

Records missing either role are skipped.

### Raw

The raw format is the most flexible. It accepts:

1. **Plain text file** — one training example per non-empty line:

   ```
   The quick brown fox jumps over the lazy dog.
   ARM64 is the target architecture for BMT AI OS.
   ```

2. **JSONL file** — one JSON object per line with a `text` field:

   ```jsonl
   {"text": "The quick brown fox jumps over the lazy dog."}
   {"text": "ARM64 is the target architecture for BMT AI OS."}
   ```

3. **JSON array** — an array of objects with `text` fields or plain strings.

## CLI Usage

```bash
bmt-ai-os data-prepare \
  --input  <input_file> \
  --output <output.jsonl> \
  --format <alpaca|sharegpt|raw>
```

### Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--input` | `-i` | (required) | Path to the source dataset file |
| `--output` | `-o` | (required) | Destination JSONL file path |
| `--format` | `-f` | `alpaca` | Dataset format (`alpaca`, `sharegpt`, `raw`) |

### Examples

```bash
# Alpaca format
bmt-ai-os data-prepare --input alpaca_data.json --output train.jsonl --format alpaca

# ShareGPT format
bmt-ai-os data-prepare --input sharegpt_data.json --output train.jsonl --format sharegpt

# Raw text file
bmt-ai-os data-prepare --input corpus.txt --output train.jsonl --format raw

# Inspect stats (printed to stdout)
bmt-ai-os data-prepare --input data.json --output /dev/null --format alpaca
```

### Output

```
Preparing dataset: format=alpaca
  Input  : /path/to/alpaca_data.json
  Output : /path/to/train.jsonl

Dataset prepared successfully.
  Examples written : 52002
  Examples skipped : 5
  Output file      : /path/to/train.jsonl
```

## Python API

```python
from bmt_ai_os.training.data_prep import prepare_dataset, DataStats

stats: DataStats = prepare_dataset(
    input_path="/path/to/raw_data.json",
    output_path="/var/lib/bmt/datasets/train.jsonl",
    format="alpaca",
)

print(f"Written  : {stats.total_examples}")
print(f"Skipped  : {stats.skipped_examples}")
print(f"Errors   : {len(stats.validation_errors)}")

# Inspect validation issues
for err in stats.validation_errors[:5]:
    print(f"  - {err}")
```

### Validation helpers

```python
from bmt_ai_os.training.data_prep import validate_alpaca_record, validate_sharegpt_record

# Returns a list of error strings (empty list = valid)
errors = validate_alpaca_record({
    "instruction": "Do something",
    "input": "",
    "output": "Done.",
})
# errors == []

errors = validate_alpaca_record({"instruction": "", "output": ""})
# errors == ["'instruction' field is missing or empty", "'output' field is missing or empty"]
```

## Output JSONL Format

Each line in the output file is a JSON object with a single `text` field:

```jsonl
{"text": "### Instruction:\nWrite a Python function to reverse a string.\n\n### Response:\ndef reverse_string(s: str) -> str:\n    return s[::-1]"}
{"text": "### Instruction:\nTranslate the following to French.\n\n### Input:\nGood morning\n\n### Response:\nBonjour"}
```

This format is consumed directly by `LoRATrainer` via the `datasets` library.

## Prompt Templates

### Alpaca — with input

```
### Instruction:
{instruction}

### Input:
{input}

### Response:
{output}
```

### Alpaca — without input

```
### Instruction:
{instruction}

### Response:
{output}
```

### ShareGPT

```
### Human:
{value}

### Assistant:
{value}

### Human:
{value}
...
```

## Best Practices

1. **Aim for at least 500–1000 examples** for meaningful fine-tuning results.
2. **Balance your dataset** — mix instruction types and avoid heavy repetition.
3. **Keep output length consistent** with your `--max-seq-length` setting. Longer outputs will be truncated during tokenisation.
4. **Review skipped examples** — a high skip rate indicates data quality issues in the source.
5. **Use the alpaca format** when starting out — it is the simplest to prepare and has broad community support.
6. **Validate before training** — run `data-prepare` and check the error report before starting a long training run.

## Creating a Dataset from Scratch

If you need to create an Alpaca dataset from scratch:

```python
import json

examples = [
    {
        "instruction": "Explain what LoRA is in one sentence.",
        "input": "",
        "output": "LoRA (Low-Rank Adaptation) is a PEFT technique that adds small trainable matrices to frozen model weights to enable efficient fine-tuning.",
    },
    # ... add more examples
]

with open("my_dataset.json", "w") as f:
    json.dump(examples, f, indent=2)
```

Then run:

```bash
bmt-ai-os data-prepare --input my_dataset.json --output train.jsonl --format alpaca
```
