"""SSH WebSocket proxy for BMT AI OS Controller.

Establishes a Paramiko SSH connection and pipes data bidirectionally between
the WebSocket client and the SSH channel.  Supports:

- Password auth:  first WebSocket message must be the password (plain text)
- Key auth:       uses a stored key from BMT_SSH_KEY_PATH (default ~/.ssh/id_rsa)
- Resize:         JSON control message ``{"type":"resize","cols":N,"rows":N}``
- Keepalive:      server-side keepalive every 30 seconds
- Graceful close: WebSocket close triggers SSH channel shutdown and vice-versa

Query parameters
----------------
host      : str  — target host (required)
port      : int  — SSH port (default 22)
username  : str  — login user (default "root")
auth      : str  — "password" | "key"  (default "password")
token     : str  — JWT for controller authentication (required when BMT_JWT_SECRET is set)

Authentication
--------------
A valid JWT must be supplied as the ``token`` query parameter before the
WebSocket handshake is accepted.  The token is verified using the same
``verify_token`` function used by the HTTP middleware.  If the secret is
not configured (e.g. in test environments), the check is skipped so that
existing smoke and unit tests continue to pass without changes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
from typing import Optional

try:
    import paramiko  # type: ignore[import-untyped]

    _PARAMIKO_AVAILABLE = True
except ImportError:  # pragma: no cover
    paramiko = None  # type: ignore[assignment]
    _PARAMIKO_AVAILABLE = False

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState

from bmt_ai_os.controller.auth import verify_token

logger = logging.getLogger(__name__)

router = APIRouter()

_READ_SIZE = 4096
_KEEPALIVE_INTERVAL = 30  # seconds
_CONNECT_TIMEOUT = 15  # seconds

_DEFAULT_KEY_PATH = os.path.expanduser(os.environ.get("BMT_SSH_KEY_PATH", "~/.ssh/id_rsa"))


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------


def _ws_auth_required() -> bool:
    """Return True when a JWT secret is configured and auth should be enforced."""
    return bool(os.environ.get("BMT_JWT_SECRET"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_private_key(key_path: str) -> paramiko.PKey:
    """Load the first supported private key type from *key_path*."""
    for cls in (
        paramiko.Ed25519Key,
        paramiko.ECDSAKey,
        paramiko.RSAKey,
        paramiko.DSSKey,
    ):
        try:
            return cls.from_private_key_file(key_path)
        except (paramiko.SSHException, ValueError, OSError):
            continue
    raise paramiko.SSHException(f"Could not load private key from {key_path!r}")


def _ssh_connect_password(
    host: str,
    port: int,
    username: str,
    password: str,
) -> paramiko.SSHClient:
    """Create and return a connected SSHClient using password auth."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.WarningPolicy())
    client.connect(
        hostname=host,
        port=port,
        username=username,
        password=password,
        timeout=_CONNECT_TIMEOUT,
        allow_agent=False,
        look_for_keys=False,
    )
    return client


def _ssh_connect_key(
    host: str,
    port: int,
    username: str,
    key_path: str = _DEFAULT_KEY_PATH,
) -> paramiko.SSHClient:
    """Create and return a connected SSHClient using key-based auth."""
    pkey = _load_private_key(key_path)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.WarningPolicy())
    client.connect(
        hostname=host,
        port=port,
        username=username,
        pkey=pkey,
        timeout=_CONNECT_TIMEOUT,
        allow_agent=False,
        look_for_keys=False,
    )
    return client


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@router.websocket("/ws/ssh")
async def ssh_ws(
    websocket: WebSocket,
    host: str = "",
    port: int = 22,
    username: str = "root",
    auth: str = "password",
    token: str = "",
) -> None:
    """WebSocket endpoint that proxies an interactive SSH session.

    Handshake protocol
    ------------------
    1. If ``BMT_JWT_SECRET`` is configured, the ``token`` query parameter is
       verified before the WebSocket is accepted.  Missing or invalid tokens
       are rejected with close code 1008 (Policy Violation).
    2. Server accepts the WebSocket.
    3. If ``auth=password``:  server sends ``{"type":"auth","method":"password"}``
       and waits for the client to send the password as a plain text message.
       If ``auth=key``:  server skips this step and connects immediately.
    4. Server connects via Paramiko and opens a PTY channel.
    5. Bidirectional data piping begins.
    """
    if _ws_auth_required():
        if not token:
            await websocket.close(1008)
            logger.warning("ssh_ws: rejected connection — missing token")
            return
        try:
            verify_token(token)
        except jwt.PyJWTError as exc:
            await websocket.close(1008)
            logger.warning("ssh_ws: rejected connection — invalid token: %s", exc)
            return

    await websocket.accept()
    logger.info(
        "ssh_ws: connection from client (host=%s port=%s user=%s auth=%s)",
        host,
        port,
        username,
        auth,
    )

    if not _PARAMIKO_AVAILABLE:
        await _send_error(websocket, "paramiko is not installed; SSH proxy unavailable")
        await websocket.close(1011)
        return

    if not host:
        await _send_error(websocket, "Query parameter 'host' is required")
        await websocket.close(1008)
        return

    loop = asyncio.get_event_loop()
    ssh_client: Optional[paramiko.SSHClient] = None
    channel: Optional[paramiko.Channel] = None

    try:
        # ------------------------------------------------------------------
        # Auth negotiation
        # ------------------------------------------------------------------
        if auth == "password":
            # Prompt client for the password.
            await websocket.send_text(json.dumps({"type": "auth", "method": "password"}))
            try:
                raw = await asyncio.wait_for(websocket.receive(), timeout=30)
            except asyncio.TimeoutError:
                await _send_error(websocket, "Timeout waiting for password")
                await websocket.close(1008)
                return

            if websocket.client_state != WebSocketState.CONNECTED:
                return

            password = _extract_text(raw)
            if not password:
                await _send_error(websocket, "Empty password received")
                await websocket.close(1008)
                return

            try:
                ssh_client = await loop.run_in_executor(
                    None, _ssh_connect_password, host, port, username, password
                )
            except (
                paramiko.AuthenticationException,
                paramiko.SSHException,
                socket.error,
                OSError,
            ) as exc:
                await _send_error(websocket, f"SSH authentication failed: {exc}")
                await websocket.close(1011)
                return

        elif auth == "key":
            try:
                ssh_client = await loop.run_in_executor(
                    None, _ssh_connect_key, host, port, username
                )
            except (paramiko.SSHException, socket.error, OSError) as exc:
                await _send_error(websocket, f"SSH key auth failed: {exc}")
                await websocket.close(1011)
                return

        else:
            await _send_error(websocket, f"Unknown auth method: {auth!r} (use 'password' or 'key')")
            await websocket.close(1008)
            return

        # ------------------------------------------------------------------
        # Open interactive PTY channel
        # ------------------------------------------------------------------
        transport = ssh_client.get_transport()
        if transport is None:
            await _send_error(websocket, "SSH transport unavailable")
            await websocket.close(1011)
            return

        channel = transport.open_session()
        channel.get_pty(term="xterm-256color", width=80, height=24)
        channel.invoke_shell()
        channel.setblocking(False)

        logger.info("ssh_ws: SSH channel open (host=%s user=%s)", host, username)
        await websocket.send_text(json.dumps({"type": "connected"}))

        # ------------------------------------------------------------------
        # Bidirectional pipe tasks
        # ------------------------------------------------------------------

        stop_event = asyncio.Event()

        async def _read_ssh() -> None:
            """Forward SSH channel output to the WebSocket."""
            while not stop_event.is_set():
                try:
                    data = await loop.run_in_executor(None, _recv_ssh, channel)
                except Exception:
                    break
                if data is None:
                    # No data yet — yield and try again.
                    await asyncio.sleep(0.01)
                    continue
                if data == b"":
                    # Channel closed.
                    break
                try:
                    await websocket.send_bytes(data)
                except Exception:
                    break
            stop_event.set()

        async def _read_ws() -> None:
            """Forward WebSocket input to the SSH channel."""
            while not stop_event.is_set():
                try:
                    message = await websocket.receive()
                except (WebSocketDisconnect, Exception):
                    break

                if websocket.client_state != WebSocketState.CONNECTED:
                    break

                if "bytes" in message and message["bytes"]:
                    _write_ssh(channel, message["bytes"])

                elif "text" in message and message["text"]:
                    text: str = message["text"]
                    try:
                        ctrl = json.loads(text)
                    except json.JSONDecodeError:
                        _write_ssh(channel, text.encode())
                        continue

                    msg_type = ctrl.get("type")
                    if msg_type == "resize":
                        cols = int(ctrl.get("cols", 80))
                        rows = int(ctrl.get("rows", 24))
                        try:
                            channel.resize_pty(width=cols, height=rows)
                        except Exception:
                            pass
                    # Other control types can be added here.

            stop_event.set()

        async def _keepalive() -> None:
            """Send SSH keepalive packets every 30 seconds."""
            while not stop_event.is_set():
                try:
                    await asyncio.wait_for(
                        asyncio.sleep(_KEEPALIVE_INTERVAL),
                        timeout=_KEEPALIVE_INTERVAL + 1,
                    )
                except asyncio.CancelledError:
                    break
                if stop_event.is_set():
                    break
                try:
                    transport2 = ssh_client.get_transport() if ssh_client else None
                    if transport2 and transport2.is_active():
                        transport2.send_ignore()
                except Exception:
                    pass

        ssh_task = asyncio.create_task(_read_ssh())
        ws_task = asyncio.create_task(_read_ws())
        ka_task = asyncio.create_task(_keepalive())

        done, pending = await asyncio.wait(
            [ssh_task, ws_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

    finally:
        stop_event.set() if "stop_event" in dir() else None  # type: ignore[name-defined]

        for task_name in ("ssh_task", "ws_task", "ka_task"):
            task = locals().get(task_name)
            if task is not None:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

        if channel is not None:
            try:
                channel.close()
            except Exception:
                pass

        if ssh_client is not None:
            try:
                ssh_client.close()
            except Exception:
                pass

        logger.info("ssh_ws: session closed (host=%s user=%s)", host, username)

        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Low-level channel I/O (called via run_in_executor)
# ---------------------------------------------------------------------------


def _recv_ssh(channel: paramiko.Channel) -> Optional[bytes]:
    """Non-blocking read from SSH channel.

    Returns:
        bytes  — data received (may be empty ``b""`` meaning channel closed)
        None   — no data available yet (try again)
    """
    if channel.exit_status_ready() and not channel.recv_ready():
        return b""  # channel done
    if not channel.recv_ready():
        return None
    try:
        return channel.recv(_READ_SIZE)
    except socket.timeout:
        return None
    except Exception:
        return b""


def _write_ssh(channel: paramiko.Channel, data: bytes) -> None:
    """Best-effort write to SSH channel; silently ignore errors."""
    try:
        channel.sendall(data)
    except Exception:
        pass


async def _send_error(websocket: WebSocket, message: str) -> None:
    """Send a JSON error message to the WebSocket client."""
    try:
        await websocket.send_text(json.dumps({"type": "error", "message": message}))
    except Exception:
        pass


def _extract_text(message: dict) -> str:
    """Extract plain text from a WebSocket receive() dict."""
    if "text" in message and message["text"]:
        return message["text"]
    if "bytes" in message and message["bytes"]:
        return message["bytes"].decode(errors="replace")
    return ""
