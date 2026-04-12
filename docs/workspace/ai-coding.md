# AI Coding Workflow

The Code Editor includes an integrated AI coding assistant inspired by Claude Code (Claw-Code). It supports multiple providers, slash commands, tool use, and IDE-grade editing workflows.

## Multi-Provider Support

The AI panel supports multiple coding providers:

| Provider | Models | Notes |
|----------|--------|-------|
| Ollama (local) | Qwen, CodeLlama, DeepSeek | Default, fully offline |
| Claude (Anthropic) | Claude 4.6 Opus/Sonnet | Requires API key |
| Codex (OpenAI) | GPT-4o, o3 | Requires API key |
| Gemini (Google) | Gemini 2.5 Pro/Flash | Requires API key |

Switch providers via the dropdown in the AI panel. API keys can be configured inline or in Settings.

## Slash Commands

Type `/` in the AI prompt to open the command palette:

| Command | Action |
|---------|--------|
| `/fix` | Fix bugs in selected code |
| `/refactor` | Improve code structure |
| `/explain` | Explain what the code does |
| `/test` | Generate unit tests |
| `/doc` | Add documentation/docstrings |
| `/optimize` | Improve performance |

Each command pre-fills a specialized system prompt optimized for that task.

## Diff Preview

Before applying AI-generated code changes:

1. A unified diff view shows additions (green) and removals (red)
2. Review changes side-by-side or inline
3. Click **Apply** to accept or **Reject** to discard

## Multi-File Edits

The AI can suggest edits across multiple files from a single prompt:

- Response shows a file tree of all proposed changes
- Each file shows its own diff
- Apply all changes at once or select individual files

## Tool Use

The AI assistant can use tools during code generation:

- `read_file` — Read file contents for context
- `write_file` — Write changes to files
- `run_command` — Execute shell commands
- `search_code` — Search codebase for patterns

Tool invocations appear inline in the response as collapsible blocks.

## Git Integration

The Code Editor includes a git panel:

- File status indicators (modified, staged, untracked)
- View diffs for changed files
- Stage and unstage files
- Commit with message
- Uses the workspace directory as git root

## Model Comparison (A/B Testing)

Send the same prompt to two or more models side by side:

- Responses displayed in split columns
- Compare speed, token count, and output quality
- Useful for evaluating which model works best for a task
