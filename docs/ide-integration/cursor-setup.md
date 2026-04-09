# Cursor Setup Guide

Connect [Cursor](https://cursor.sh) to BMT AI OS so that all AI features
(chat, inline edit, code generation) run on your local device.

## Prerequisites

- BMT AI OS controller running (default port 8080)
- At least one model pulled (e.g. `qwen2.5-coder:7b`)

## Configuration

### 1. Open Cursor Settings

`Cmd+,` (macOS) or `Ctrl+,` (Linux) then search for **"OpenAI"**.

Alternatively, open Settings JSON and add the keys below directly.

### 2. Set the API Base URL

In Cursor Settings > Models > OpenAI API Base:

```
http://<device-ip>:8080/v1
```

Replace `<device-ip>` with your BMT AI OS device IP. Use `localhost` if
running on the same machine.

### 3. Set the API Key

If you have enabled authentication (`BMT_API_KEY`), enter the key in
Cursor Settings > Models > OpenAI API Key.

If authentication is disabled (default), enter any non-empty string
(e.g. `bmt`). Cursor requires the field to be non-empty.

### 4. Select a Model

In Cursor Settings > Models, add a custom model name matching one
available on your device:

```
qwen2.5-coder:7b
```

You can check available models at:

```bash
curl http://<device-ip>:8080/v1/models
```

## Settings JSON Example

```json
{
  "cursor.aiProvider": "openai",
  "cursor.openai.apiBase": "http://192.168.1.100:8080/v1",
  "cursor.openai.apiKey": "your-bmt-api-key",
  "cursor.openai.model": "qwen2.5-coder:7b"
}
```

## Verify Connection

1. Open Cursor chat (`Cmd+L` / `Ctrl+L`)
2. Type a message and confirm you get a response
3. Try inline code generation (`Cmd+K` / `Ctrl+K`)

## Streaming

Cursor uses SSE streaming by default. The BMT AI OS API supports this
natively -- no additional configuration is needed.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| "Connection refused" | Ensure controller is running: `curl http://localhost:8080/healthz` |
| "Invalid API key" | Check `BMT_API_KEY` matches what you entered in Cursor |
| Slow responses | Verify model is loaded: `curl http://localhost:8080/v1/models` |
| Empty completions | Check Ollama has the model: `docker exec bmt-ollama ollama list` |

## Continue.dev

The [Continue.dev](https://continue.dev) VS Code / JetBrains extension
uses the same OpenAI-compatible protocol. In `~/.continue/config.json`:

```json
{
  "models": [
    {
      "title": "BMT AI OS",
      "provider": "openai",
      "model": "qwen2.5-coder:7b",
      "apiBase": "http://<device-ip>:8080/v1",
      "apiKey": "your-bmt-api-key"
    }
  ]
}
```
