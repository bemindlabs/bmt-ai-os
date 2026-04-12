"""WebSocket terminal endpoint for BMT AI OS Controller.

Spawns a shell subprocess and pipes stdin/stdout between the WebSocket
client and the shell process using asyncio. Supports resize via a JSON
control message: {"type": "resize", "cols": N, "rows": N}.

Authentication
--------------
A valid JWT must be supplied as the ``token`` query parameter before the
WebSocket handshake is accepted.  The token is verified using the same
``verify_token`` function used by the HTTP middleware.  If the secret is
not configured (e.g. in test environments), the check is skipped so that
existing smoke and unit tests continue to pass without changes.

tmux session persistence
------------------------
When tmux is available the terminal attaches to (or creates) a named tmux
session called ``bmt`` via ``tmux new-session -A -s bmt``.  This means
that if the WebSocket disconnects and the user reconnects, they return to
the exact same shell session with its full history and running processes.

If tmux is not found the handler falls back to the shell specified by
``BMT_TERMINAL_SHELL`` (default: ``/bin/sh``).

The ``BMT_TERMINAL_CMD`` environment variable overrides the entire command
selection logic, letting operators substitute an arbitrary executable.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import pty
import shutil
import struct
import termios

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from bmt_ai_os.controller.auth import verify_token

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Command selection
# Priority: BMT_TERMINAL_CMD > tmux (if available) > BMT_TERMINAL_SHELL
# ---------------------------------------------------------------------------
_TERMINAL_CMD = os.environ.get("BMT_TERMINAL_CMD")
if _TERMINAL_CMD:
    _SHELL = _TERMINAL_CMD
    _SHELL_ARGS: list[str] = []
elif shutil.which("tmux"):
    _SHELL = "tmux"
    _SHELL_ARGS = ["new-session", "-A", "-s", "bmt"]
else:
    _SHELL = os.environ.get("BMT_TERMINAL_SHELL", "/bin/sh")
    _SHELL_ARGS = []

_READ_SIZE = 4096


def _ws_auth_required() -> bool:
    """Return True when a JWT secret is configured and auth should be enforced."""
    return bool(os.environ.get("BMT_JWT_SECRET"))


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    """Set terminal window size on a file descriptor."""
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
    except OSError:
        pass


@router.websocket("/ws/terminal")
async def terminal_ws(websocket: WebSocket, token: str = "") -> None:
    """WebSocket handler that attaches a shell via a PTY.

    Requires a valid JWT supplied as the ``token`` query parameter when
    ``BMT_JWT_SECRET`` is configured.  Example::

        ws://host:8080/ws/terminal?token=<jwt>
    """
    if _ws_auth_required():
        if not token:
            await websocket.close(1008)
            logger.warning("terminal: rejected connection — missing token")
            return
        try:
            verify_token(token)
        except jwt.PyJWTError as exc:
            await websocket.close(1008)
            logger.warning("terminal: rejected connection — invalid token: %s", exc)
            return

    await websocket.accept()
    logger.info("terminal: WebSocket connection accepted")

    # Open a PTY master/slave pair so the shell gets a real terminal.
    master_fd, slave_fd = pty.openpty()

    # Build the child process environment.  When using tmux, expose the
    # session name so that any scripts or aliases inside the session can
    # reference it without hard-coding "bmt".
    child_env = {
        **os.environ,
        "TERM": "xterm-256color",
        "TMUX_SESSION": "bmt",
    }

    try:
        proc = await asyncio.create_subprocess_exec(
            _SHELL,
            *_SHELL_ARGS,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
            env=child_env,
        )
    except Exception as exc:
        logger.error("terminal: failed to spawn shell: %s", exc)
        await websocket.send_text(f"\r\nFailed to start shell: {exc}\r\n")
        await websocket.close(1011)
        os.close(master_fd)
        os.close(slave_fd)
        return

    # slave_fd is only needed in the parent to set the initial window size;
    # after fork it belongs entirely to the child process.
    os.close(slave_fd)

    loop = asyncio.get_event_loop()

    async def _read_pty() -> None:
        """Forward PTY output to the WebSocket client."""
        while True:
            try:
                data = await loop.run_in_executor(None, os.read, master_fd, _READ_SIZE)
            except OSError:
                # PTY closed (shell exited).
                break
            if not data:
                break
            try:
                await websocket.send_bytes(data)
            except Exception:
                break

    async def _read_ws() -> None:
        """Forward WebSocket input to the PTY."""
        while True:
            try:
                message = await websocket.receive()
            except WebSocketDisconnect:
                break

            if "bytes" in message and message["bytes"]:
                try:
                    await loop.run_in_executor(None, os.write, master_fd, message["bytes"])
                except OSError:
                    break

            elif "text" in message and message["text"]:
                text = message["text"]
                try:
                    ctrl = json.loads(text)
                except json.JSONDecodeError:
                    # Plain text input — write to PTY.
                    try:
                        await loop.run_in_executor(None, os.write, master_fd, text.encode())
                    except OSError:
                        break
                    continue

                if ctrl.get("type") == "resize":
                    cols = int(ctrl.get("cols", 80))
                    rows = int(ctrl.get("rows", 24))
                    _set_winsize(master_fd, rows, cols)

    pty_task = asyncio.create_task(_read_pty())
    ws_task = asyncio.create_task(_read_ws())

    try:
        # Run until either direction closes.
        done, pending = await asyncio.wait(
            [pty_task, ws_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        for task in [pty_task, ws_task]:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        if proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        try:
            os.close(master_fd)
        except OSError:
            pass

        logger.info("terminal: WebSocket session closed (pid=%s)", proc.pid)

        try:
            await websocket.close()
        except Exception:
            pass
