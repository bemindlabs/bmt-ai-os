"""WebSocket terminal endpoint for BMT AI OS Controller.

Spawns a shell subprocess and pipes stdin/stdout between the WebSocket
client and the shell process using asyncio. Supports resize via a JSON
control message: {"type": "resize", "cols": N, "rows": N}.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import pty
import struct
import termios

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()

_SHELL = os.environ.get("BMT_TERMINAL_SHELL", "/bin/sh")
_READ_SIZE = 4096


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    """Set terminal window size on a file descriptor."""
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
    except OSError:
        pass


@router.websocket("/ws/terminal")
async def terminal_ws(websocket: WebSocket) -> None:
    """WebSocket handler that attaches a shell via a PTY."""
    await websocket.accept()
    logger.info("terminal: WebSocket connection accepted")

    # Open a PTY master/slave pair so the shell gets a real terminal.
    master_fd, slave_fd = pty.openpty()

    try:
        proc = await asyncio.create_subprocess_exec(
            _SHELL,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
            env={**os.environ, "TERM": "xterm-256color"},
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
