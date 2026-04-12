"""Tool executor for AI function calling.

Defines available tools and executes them when the AI requests them.
Tools: read_file, list_directory, search_code, run_command

Security constraints:
- All file operations are scoped to the workspace directory.
- run_command has a 30-second timeout and 10 KB output limit.
- Destructive shell patterns are rejected before execution.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions (OpenAI function-calling schema)
# ---------------------------------------------------------------------------

AVAILABLE_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "File path to read"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and directories at a path",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Directory path"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search for a pattern in files using grep",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Search pattern (regex)",
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search in",
                        "default": ".",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command and return output",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute",
                    }
                },
                "required": ["command"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Security: blocklist for run_command
# ---------------------------------------------------------------------------

# Patterns that must never appear in a shell command passed to run_command.
_CMD_BLOCKLIST: list[re.Pattern[str]] = [
    re.compile(r"\brm\s+-[^\s]*r", re.IGNORECASE),  # rm -r / rm -rf
    re.compile(r"\brm\b.*\*"),  # rm with glob
    re.compile(r">\s*/dev/sd"),  # overwrite block devices
    re.compile(r"\bdd\b.*of=/dev/"),  # dd to device
    re.compile(r"\bmkfs\b"),  # filesystem format
    re.compile(r"\bfdisk\b"),  # partition editor
    re.compile(r"\bshutdown\b"),  # system shutdown
    re.compile(r"\breboot\b"),  # system reboot
    re.compile(r"\bpoweroff\b"),  # system power-off
    re.compile(r"\bchmod\s+777\b"),  # world-writable chmod
    re.compile(r"\bcurl\b.*\|\s*(bash|sh)\b"),  # piped shell execution
    re.compile(r"\bwget\b.*\|\s*(bash|sh)\b"),  # piped shell execution
    re.compile(r":\(\)\s*\{.*\}"),  # fork bomb pattern
]

_MAX_OUTPUT_BYTES = 10 * 1024  # 10 KB
_CMD_TIMEOUT_S = 30
_READ_MAX_BYTES = 100 * 1024  # 100 KB
_SEARCH_MAX_LINES = 200


def _resolve_workspace() -> Path:
    """Return the workspace root path from environment, defaulting to CWD."""
    env = os.environ.get("BMT_ENV", "production")
    default = str(Path.home() / "workspace") if env == "dev" else "/data/workspace"
    workspace = os.environ.get("BMT_WORKSPACE_DIR", default)
    return Path(workspace).resolve()


def _safe_path(raw: str) -> Path:
    """Resolve *raw* relative to the workspace and guard against path traversal.

    Raises ValueError when the resolved path escapes the workspace root.
    """
    workspace = _resolve_workspace()
    # Allow absolute paths that already live inside the workspace.
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError:
        raise ValueError(
            f"Path '{raw}' resolves outside the workspace ({workspace}). "
            "Only paths within the workspace are permitted."
        )
    return resolved


def _is_blocked_command(command: str) -> bool:
    """Return True if *command* matches any entry in the destructive blocklist."""
    for pattern in _CMD_BLOCKLIST:
        if pattern.search(command):
            return True
    return False


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def _tool_read_file(path: str) -> str:
    try:
        resolved = _safe_path(path)
    except ValueError as exc:
        return f"[error] {exc}"

    if not resolved.exists():
        return f"[error] File not found: {path}"
    if resolved.is_dir():
        return f"[error] Path is a directory: {path}"

    try:
        raw = resolved.read_bytes()
        if len(raw) > _READ_MAX_BYTES:
            raw = raw[:_READ_MAX_BYTES]
            text = raw.decode("utf-8", errors="replace")
            lines = text.splitlines()
            return f"[truncated to 100 KB — {len(lines)} lines shown]\n" + "\n".join(lines)
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        return f"[{len(lines)} lines]\n" + "\n".join(lines)
    except OSError as exc:
        return f"[error] Could not read file: {exc}"


async def _tool_list_directory(path: str) -> str:
    try:
        resolved = _safe_path(path)
    except ValueError as exc:
        return f"[error] {exc}"

    if not resolved.exists():
        return f"[error] Path not found: {path}"
    if not resolved.is_dir():
        return f"[error] Not a directory: {path}"

    try:
        entries = sorted(resolved.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        lines: list[str] = []
        for entry in entries:
            try:
                stat = entry.stat()
                size = stat.st_size
                kind = "dir " if entry.is_dir() else "file"
                lines.append(f"{kind}  {entry.name}  ({size} bytes)")
            except OSError:
                lines.append(f"????  {entry.name}")
        return f"[{len(lines)} entries in {path}]\n" + "\n".join(lines)
    except OSError as exc:
        return f"[error] Could not list directory: {exc}"


async def _tool_search_code(pattern: str, path: str = ".") -> str:
    try:
        resolved = _safe_path(path)
    except ValueError as exc:
        return f"[error] {exc}"

    cmd = ["grep", "-rn", "--include=*", pattern, str(resolved)]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_CMD_TIMEOUT_S)
        except asyncio.TimeoutError:
            proc.kill()
            return "[error] Search timed out"

        output = stdout.decode("utf-8", errors="replace")
        lines = output.splitlines()
        if len(lines) > _SEARCH_MAX_LINES:
            lines = lines[:_SEARCH_MAX_LINES]
            return "\n".join(lines) + f"\n[truncated — showing first {_SEARCH_MAX_LINES} matches]"
        if not lines:
            return "[no matches found]"
        return "\n".join(lines)
    except OSError as exc:
        return f"[error] Search failed: {exc}"


async def _tool_run_command(command: str) -> str:
    if _is_blocked_command(command):
        return "[error] Command blocked by security policy (destructive operation detected)"

    workspace = _resolve_workspace()
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(workspace),
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_CMD_TIMEOUT_S)
        except asyncio.TimeoutError:
            proc.kill()
            return f"[error] Command timed out after {_CMD_TIMEOUT_S}s"

        output = stdout[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
        if len(stdout) > _MAX_OUTPUT_BYTES:
            output += "\n[truncated — output exceeded 10 KB]"
        return output or "[no output]"
    except OSError as exc:
        return f"[error] Failed to run command: {exc}"


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


async def execute_tool(name: str, arguments: dict[str, Any]) -> str:
    """Execute a named tool with *arguments* and return the result as a string.

    Never raises — all errors are returned as ``[error] ...`` strings so the
    LLM can see what went wrong and decide how to continue.
    """
    logger.debug("Tool call: %s(%s)", name, arguments)
    try:
        if name == "read_file":
            return await _tool_read_file(arguments.get("path", ""))
        if name == "list_directory":
            return await _tool_list_directory(arguments.get("path", "."))
        if name == "search_code":
            return await _tool_search_code(
                arguments.get("pattern", ""),
                arguments.get("path", "."),
            )
        if name == "run_command":
            return await _tool_run_command(arguments.get("command", ""))
        return f"[error] Unknown tool: {name}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tool '%s' raised an unexpected error: %s", name, exc)
        return f"[error] {exc}"
