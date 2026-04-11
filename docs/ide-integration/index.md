# IDE Integration

BMT AI OS exposes an OpenAI-compatible API at `:8080`, which means any IDE or coding tool that supports OpenAI can use it as a drop-in local AI backend.

## Quick Setup

Point your IDE's AI settings to:

```
http://<device-ip>:8080
```

For local development (same machine):

```
http://localhost:8080
```

No API key is required (leave blank or use any string).

## Supported Tools

| Tool | Guide | Method |
|------|-------|--------|
| [Cursor](cursor-setup.md) | Direct API base URL override | OpenAI API compat |
| [GitHub Copilot](copilot-setup.md) | Custom API base | OpenAI API compat |
| Sourcegraph Cody | Custom OpenAI-compatible endpoint | OpenAI API compat |
| Continue.dev | `config.json` provider | OpenAI API compat |
| Aider | `--openai-api-base` flag | OpenAI API compat |

## Available Models

To see which models are available:

```bash
curl http://localhost:8080/v1/models | jq '.data[].id'
```

Use the model ID in your IDE's model selection (e.g. `qwen2.5-coder:7b`).
