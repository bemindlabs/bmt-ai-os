# AI Workspace

The BMT AI OS workspace transforms the dashboard into a full browser-based IDE experience with AI-assisted coding, terminal access, file management, and knowledge vaults.

## Layout

The workspace uses a resizable 3-panel layout:

- **Left panel** — Agent/session browser, file tree, knowledge navigation
- **Center panel** — Tabbed work area (chat, code editor, terminal, training studio)
- **Right panel** — RAG sources, memory context, tool outputs

Panels resize with drag handles and persist their sizes in localStorage.

## Components

### Code Editor (Monaco)

Full Monaco editor with syntax highlighting, AI-assisted inline completions, and file save to device filesystem.

- Multi-provider AI coding: Claude, Codex, Gemini, local Ollama
- Slash commands: `/fix`, `/refactor`, `/explain`, `/test`, `/doc`, `/optimize`
- Diff preview before applying AI-generated changes
- Multi-file edit workflow from a single prompt
- Git integration: status, diff, stage, commit

### Terminal (xterm.js)

WebSocket-based terminal emulator in the browser.

- Local PTY mode for device shell access
- SSH mode for connecting to fleet devices (via paramiko proxy)
- tmux session management (persists across reconnects)
- Multi-tab with split panes
- Embedded in Code Editor as bottom panel (VS Code-style)
- SSH key management in Settings

### File Manager

Browse and manage device filesystem with tree view.

- Upload/download files
- Drag files into chat for context
- File preview (code, markdown, images)

### Training Studio

Visual training pipeline with live metrics.

- Dataset preview and validation
- Real-time training metrics via WebSocket
- TensorBoard embedding

### Fleet Dashboard

Grid view of all fleet devices with health status.

- Per-device monitoring cards
- Remote model deployment
- SSH connect button (opens terminal)
- Fleet-wide command broadcast

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+`` | Toggle terminal panel |
| `Ctrl+S` | Save current file |
| `Ctrl+P` | Quick file open |

## Notifications

Real-time WebSocket notifications for:

- Training job completion
- Fleet status changes
- OTA updates
- System alerts

Bell icon in header with unread count and toast popups.
