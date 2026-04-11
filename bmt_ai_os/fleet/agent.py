"""Fleet agent for BMT AI OS.

Runs on each managed device.  When ``run()`` is called it starts a
background daemon thread that sends a heartbeat to the fleet server every
``heartbeat_interval`` seconds and processes any command returned in the
response.

The agent can also be invoked in one-shot mode via ``send_heartbeat()``.

Configuration is read from environment variables:

``BMT_FLEET_SERVER``
    URL of the fleet server (e.g. ``https://fleet.example.com``).
    Required.  No default.

``BMT_FLEET_DEVICE_ID``
    Override the auto-detected device ID.

``BMT_FLEET_OS_VERSION``
    Override the OS version string reported in heartbeats.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from typing import Any

import requests

from .collector import (
    get_device_id,
    get_hardware_info,
    get_loaded_models,
    get_resource_usage,
    get_service_health,
)
from .models import DeviceHeartbeat, FleetCommand

logger = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL = 60  # seconds
_REQUEST_TIMEOUT = 10  # seconds
_OS_VERSION_FILE = "/etc/bmt-os-version"


def _read_os_version() -> str:
    """Return the OS version string, falling back to a placeholder."""
    env_ver = os.environ.get("BMT_FLEET_OS_VERSION")
    if env_ver:
        return env_ver
    try:
        from pathlib import Path

        content = Path(_OS_VERSION_FILE).read_text().strip()
        if content:
            return content
    except OSError:
        pass
    try:
        from pathlib import Path

        content = Path("/etc/os-release").read_text()
        for line in content.splitlines():
            if line.startswith("VERSION_ID="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "unknown"


class FleetAgent:
    """Manages heartbeat loop and command execution for one device.

    Parameters
    ----------
    server_url:
        Base URL of the fleet server, e.g. ``https://fleet.example.com``.
    device_id:
        Stable unique identifier for this device.  When ``None``, the
        value is read from ``/etc/machine-id`` via :func:`get_device_id`.
    heartbeat_interval:
        Seconds between successive heartbeats (default 60).
    """

    def __init__(
        self,
        server_url: str,
        device_id: str | None = None,
        heartbeat_interval: int = _HEARTBEAT_INTERVAL,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.device_id = device_id or os.environ.get("BMT_FLEET_DEVICE_ID") or get_device_id()
        self.heartbeat_interval = heartbeat_interval
        self.os_version = _read_os_version()
        self._hardware: dict[str, Any] = {}
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_heartbeat_ok: bool | None = None
        self._last_error: str = ""

    # ------------------------------------------------------------------
    # One-shot helpers (used by CLI and run loop)
    # ------------------------------------------------------------------

    def _build_heartbeat(self) -> DeviceHeartbeat:
        """Collect current system state and return a heartbeat object."""
        if not self._hardware:
            self._hardware = get_hardware_info()

        resources = get_resource_usage()
        return DeviceHeartbeat.now(
            device_id=self.device_id,
            os_version=self.os_version,
            hardware=self._hardware,
            loaded_models=get_loaded_models(),
            service_health=get_service_health(),
            cpu_percent=resources["cpu_percent"],
            memory_percent=resources["memory_percent"],
            disk_percent=resources["disk_percent"],
        )

    def send_heartbeat(self) -> FleetCommand:
        """Send one heartbeat to the fleet server and return any command.

        Returns a no-op :class:`FleetCommand` (``action=None``) when the
        server does not send a command or is unreachable.

        Raises
        ------
        requests.RequestException
            On any network-level failure (caller decides how to handle).
        """
        heartbeat = self._build_heartbeat()
        payload = heartbeat.to_dict()

        url = f"{self.server_url}/api/v1/fleet/heartbeat"
        logger.debug("Sending heartbeat to %s (device=%s)", url, self.device_id)

        resp = requests.post(url, json=payload, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()

        try:
            body: dict[str, Any] = resp.json()
        except Exception:
            body = {}

        return FleetCommand.from_dict(body)

    # ------------------------------------------------------------------
    # Command execution
    # ------------------------------------------------------------------

    def execute_command(self, cmd: FleetCommand) -> None:
        """Execute a :class:`FleetCommand` received from the fleet server.

        Unknown actions are logged and ignored — they are never fatal so
        the agent stays alive.
        """
        if cmd.is_noop():
            return

        logger.info("Executing fleet command: action=%s params=%s", cmd.action, cmd.params)

        try:
            if cmd.action == "update":
                self._cmd_update(cmd.params)
            elif cmd.action == "pull-model":
                self._cmd_pull_model(cmd.params)
            elif cmd.action == "restart-service":
                self._cmd_restart_service(cmd.params)
            else:
                logger.warning("Unknown fleet command action: %r — ignoring", cmd.action)
        except Exception as exc:
            logger.error("Fleet command %r failed: %s", cmd.action, exc)

    def _cmd_update(self, params: dict[str, Any]) -> None:
        """Trigger a system update (apk upgrade on Alpine or no-op)."""
        version = params.get("version", "")
        logger.info("Fleet update requested (target_version=%r)", version)
        # On Alpine Linux the standard update is: apk update && apk upgrade
        result = subprocess.run(
            ["apk", "update"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"apk update failed: {result.stderr.strip()}")
        result = subprocess.run(
            ["apk", "upgrade"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(f"apk upgrade failed: {result.stderr.strip()}")
        logger.info("System update completed.")

    def _cmd_pull_model(self, params: dict[str, Any]) -> None:
        """Pull an Ollama model by name."""
        model = params.get("model", "").strip()
        if not model:
            raise ValueError("pull-model command missing required param 'model'")
        logger.info("Pulling Ollama model: %s", model)
        resp = requests.post(
            "http://localhost:11434/api/pull",
            json={"name": model},
            stream=True,
            timeout=3600,
        )
        resp.raise_for_status()
        # Drain the stream so the pull completes; log final status line.
        last_status = ""
        for raw in resp.iter_lines():
            if raw:
                try:
                    evt = json.loads(raw)
                    last_status = evt.get("status", "")
                except Exception:
                    pass
        logger.info("Model pull finished: %s (last_status=%r)", model, last_status)

    def _cmd_restart_service(self, params: dict[str, Any]) -> None:
        """Restart a named AI-stack service via docker compose."""
        service = params.get("service", "").strip()
        if not service:
            raise ValueError("restart-service command missing required param 'service'")
        logger.info("Restarting AI-stack service: %s", service)

        from bmt_ai_os.controller.config import load_config

        try:
            cfg = load_config()
            compose_file = cfg.compose_file
        except Exception:
            compose_file = "/opt/bmt_ai_os/ai-stack/docker-compose.yml"

        result = subprocess.run(
            ["docker", "compose", "-f", compose_file, "restart", service],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"docker compose restart {service!r} failed: {result.stderr.strip()}"
            )
        logger.info("Service %r restarted.", service)

    # ------------------------------------------------------------------
    # Background heartbeat loop
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        """Main heartbeat loop, runs in a daemon thread."""
        logger.info(
            "Fleet agent started (device=%s, server=%s, interval=%ds)",
            self.device_id,
            self.server_url,
            self.heartbeat_interval,
        )
        while not self._stop_event.is_set():
            try:
                cmd = self.send_heartbeat()
                self._last_heartbeat_ok = True
                self._last_error = ""
                self.execute_command(cmd)
            except requests.exceptions.RequestException as exc:
                self._last_heartbeat_ok = False
                self._last_error = str(exc)
                logger.warning("Fleet heartbeat failed: %s", exc)
            except Exception as exc:
                self._last_heartbeat_ok = False
                self._last_error = str(exc)
                logger.error("Unexpected error in fleet agent loop: %s", exc)

            # Wait for the next interval, but wake immediately on stop.
            self._stop_event.wait(timeout=self.heartbeat_interval)

        logger.info("Fleet agent stopped.")

    def run(self) -> None:
        """Start the heartbeat loop in a background daemon thread.

        Safe to call multiple times — subsequent calls are no-ops if the
        agent is already running.
        """
        if self._thread is not None and self._thread.is_alive():
            logger.debug("Fleet agent already running.")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="fleet-agent")
        self._thread.start()

    def stop(self) -> None:
        """Signal the background loop to stop and wait for it to finish."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    # ------------------------------------------------------------------
    # Status reporting
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return a status dict suitable for CLI display.

        Keys: device_id, server_url, running, last_ok, last_error.
        """
        return {
            "device_id": self.device_id,
            "server_url": self.server_url,
            "running": self._thread is not None and self._thread.is_alive(),
            "last_ok": self._last_heartbeat_ok,
            "last_error": self._last_error,
        }
