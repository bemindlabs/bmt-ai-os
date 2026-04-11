# CLI Reference

The `bmt_ai_os` CLI provides a unified interface for managing models, querying the RAG pipeline, managing providers, and controlling the stack.

## Global Options

```
bmt_ai_os [--help] [--version] [--verbose] <command>
```

| Flag | Description |
|------|-------------|
| `--help` | Show help and exit |
| `--version` | Print version and exit |
| `--verbose` | Enable debug logging |

## Commands

### `status`

Show the health status of all services.

```bash
bmt_ai_os status
```

Output:
```
ollama     healthy    :11434
chromadb   healthy    :8000
controller healthy    :8080
dashboard  healthy    :9090
```

### `query`

Run a RAG-augmented query.

```bash
bmt_ai_os query <question> [--collection <name>] [--top-k <n>] [--code-mode]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--collection` | `default` | ChromaDB collection to search |
| `--top-k` | `5` | Number of context chunks to retrieve |
| `--code-mode` | `false` | Use a code-optimised prompt template |

```bash
# Basic query
bmt_ai_os query "How do I configure the fallback chain?"

# Query a specific collection
bmt_ai_os query "What does main.py do?" --collection my-project --code-mode
```

### `ingest`

Ingest documents into a ChromaDB collection.

```bash
bmt_ai_os ingest <path> [--collection <name>] [--no-recursive]
```

```bash
# Ingest a directory
bmt_ai_os ingest ./my-project --collection my-project

# Ingest a single file
bmt_ai_os ingest ./README.md
```

### `models`

Manage Ollama models.

```bash
bmt_ai_os models <subcommand>
```

| Subcommand | Description |
|-----------|-------------|
| `list` | List installed models |
| `install <preset>` | Install a preset (`auto`, `lite`, `standard`, `full`) |
| `install <model>` | Install a specific Ollama model |
| `remove <model>` | Remove a model |

```bash
bmt_ai_os models list
bmt_ai_os models install auto        # auto-detect hardware
bmt_ai_os models install standard    # Qwen2.5-Coder-7B + embedding
bmt_ai_os models install qwen2.5-coder:7b
```

### `provider`

Manage LLM providers.

```bash
bmt_ai_os provider <subcommand>
```

| Subcommand | Description |
|-----------|-------------|
| `list` | List all providers and their status |
| `set <name>` | Set the active provider |
| `test <name>` | Run a health check on a provider |

```bash
bmt_ai_os provider list
bmt_ai_os provider set ollama
bmt_ai_os provider test openai
```

### `tui`

Open the terminal UI.

```bash
bmt_ai_os tui
```

### `logs`

Stream live logs from a service.

```bash
bmt_ai_os logs [--service <name>] [--follow]
```

```bash
bmt_ai_os logs --service ollama --follow
bmt_ai_os logs --service controller
```

### `train`

Start a LoRA fine-tuning job.

```bash
bmt_ai_os train --model <base-model> --data <path> [--method lora|qlora] [--epochs <n>]
```

```bash
bmt_ai_os train \
  --model qwen2.5-coder:1.5b \
  --data ./my-dataset \
  --method lora \
  --epochs 3
```
