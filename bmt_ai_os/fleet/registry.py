"""Central fleet registry — server-side device tracking.

Maintains an in-memory store of all registered devices and their most-recent
heartbeat snapshots.  The registry is a singleton (``get_registry()``) shared
across all FastAPI request handlers.

Design notes
------------
- Pure in-memory; no external database required for single-node deployments.
- All public methods are thread-safe via a single ``threading.Lock``.
- Pending commands are queued per-device and dequeued one at a time when the
  device sends its next heartbeat, enabling reliable fleet-wide operations
  even when devices are temporarily offline.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any

from .models import DeviceHeartbeat, FleetCommand

logger = logging.getLogger(__name__)

# How many seconds of silence before a device is considered "offline".
_STALE_THRESHOLD_SECONDS = 300  # 5 minutes


class DeviceRecord:
    """Runtime record kept for one registered device.

    Parameters
    ----------
    device_id:
        Stable unique identifier for the device.
    hostname:
        Human-readable hostname, extracted from the registration payload.
    arch:
        CPU architecture string (e.g. ``aarch64``).
    board:
        Board identifier (e.g. ``rk3588``, ``apple-silicon``).
    hardware:
        Full hardware dict as reported in the registration/heartbeat payload.
    registered_at:
        UTC timestamp of initial registration (ISO 8601 string).
    """

    def __init__(
        self,
        device_id: str,
        hostname: str = "",
        arch: str = "",
        board: str = "",
        hardware: dict[str, Any] | None = None,
        registered_at: str = "",
    ) -> None:
        self.device_id = device_id
        self.hostname = hostname
        self.arch = arch
        self.board = board
        self.hardware: dict[str, Any] = hardware or {}
        self.registered_at = registered_at or datetime.now(timezone.utc).isoformat()

        # Mutable state — updated on every heartbeat.
        self.last_heartbeat: DeviceHeartbeat | None = None
        self.last_seen: str = ""
        self.loaded_models: list[str] = []
        self.service_health: dict[str, str] = {}
        self.cpu_percent: float = 0.0
        self.memory_percent: float = 0.0
        self.disk_percent: float = 0.0
        self.os_version: str = ""

        # Pending command queue for this device (FIFO).
        self._command_queue: deque[FleetCommand] = deque()

    # ------------------------------------------------------------------
    # Heartbeat update
    # ------------------------------------------------------------------

    def apply_heartbeat(self, hb: DeviceHeartbeat) -> None:
        """Update mutable state from a fresh heartbeat."""
        self.last_heartbeat = hb
        self.last_seen = hb.timestamp
        self.os_version = hb.os_version
        self.loaded_models = list(hb.loaded_models)
        self.service_health = dict(hb.service_health)
        self.cpu_percent = hb.cpu_percent
        self.memory_percent = hb.memory_percent
        self.disk_percent = hb.disk_percent
        # Merge hardware if the heartbeat carries richer info.
        if hb.hardware:
            self.hardware.update(hb.hardware)
            self.hostname = hb.hardware.get("hostname", self.hostname) or self.hostname
            self.arch = hb.hardware.get("arch", self.arch) or self.arch
            self.board = hb.hardware.get("board", self.board) or self.board

    # ------------------------------------------------------------------
    # Command queue
    # ------------------------------------------------------------------

    def enqueue_command(self, cmd: FleetCommand) -> None:
        """Add *cmd* to the pending queue for this device."""
        self._command_queue.append(cmd)
        logger.debug("Enqueued command %r for device %s", cmd.action, self.device_id)

    def dequeue_command(self) -> FleetCommand:
        """Pop and return the next pending command, or a no-op if the queue is empty."""
        if self._command_queue:
            return self._command_queue.popleft()
        return FleetCommand(action=None)

    def pending_command_count(self) -> int:
        """Return the number of commands waiting to be dispatched."""
        return len(self._command_queue)

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def is_online(self) -> bool:
        """Return True when the device has sent a heartbeat recently."""
        if not self.last_seen:
            return False
        try:
            last = datetime.fromisoformat(self.last_seen)
            now = datetime.now(timezone.utc)
            # Make last timezone-aware if it isn't already (defensive).
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            return (now - last).total_seconds() < _STALE_THRESHOLD_SECONDS
        except (ValueError, TypeError):
            return False

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary dict."""
        return {
            "device_id": self.device_id,
            "hostname": self.hostname,
            "arch": self.arch,
            "board": self.board,
            "os_version": self.os_version,
            "hardware": self.hardware,
            "registered_at": self.registered_at,
            "last_seen": self.last_seen,
            "online": self.is_online(),
            "loaded_models": self.loaded_models,
            "service_health": self.service_health,
            "cpu_percent": self.cpu_percent,
            "memory_percent": self.memory_percent,
            "disk_percent": self.disk_percent,
            "pending_commands": self.pending_command_count(),
        }


class FleetRegistry:
    """Thread-safe central registry of managed devices.

    Usage::

        registry = get_registry()
        registry.register_device(device_id="abc", hostname="bmt-1", ...)
        registry.apply_heartbeat(heartbeat_obj)
        devices = registry.list_devices()
    """

    def __init__(self) -> None:
        self._devices: dict[str, DeviceRecord] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Device lifecycle
    # ------------------------------------------------------------------

    def register_device(
        self,
        device_id: str,
        hostname: str = "",
        arch: str = "",
        board: str = "",
        hardware: dict[str, Any] | None = None,
    ) -> DeviceRecord:
        """Register a new device, or refresh the record if it already exists.

        Returns the (possibly updated) :class:`DeviceRecord`.
        """
        with self._lock:
            if device_id in self._devices:
                rec = self._devices[device_id]
                # Refresh mutable fields without clearing the command queue.
                if hostname:
                    rec.hostname = hostname
                if arch:
                    rec.arch = arch
                if board:
                    rec.board = board
                if hardware:
                    rec.hardware.update(hardware)
                logger.info("Re-registered device %s (hostname=%s)", device_id, hostname)
            else:
                rec = DeviceRecord(
                    device_id=device_id,
                    hostname=hostname,
                    arch=arch,
                    board=board,
                    hardware=hardware,
                )
                self._devices[device_id] = rec
                logger.info(
                    "New device registered: %s (hostname=%s, arch=%s, board=%s)",
                    device_id,
                    hostname,
                    arch,
                    board,
                )
            return rec

    def remove_device(self, device_id: str) -> bool:
        """Remove a device from the registry.  Returns True if it existed."""
        with self._lock:
            if device_id in self._devices:
                del self._devices[device_id]
                logger.info("Removed device %s from fleet registry", device_id)
                return True
            return False

    # ------------------------------------------------------------------
    # Heartbeat processing
    # ------------------------------------------------------------------

    def apply_heartbeat(self, hb: DeviceHeartbeat) -> FleetCommand:
        """Record the heartbeat and return the next pending command (or no-op).

        Auto-registers the device on its first heartbeat so the agent doesn't
        need to call ``/register`` before it can send heartbeats.
        """
        with self._lock:
            if hb.device_id not in self._devices:
                logger.info("Auto-registering device %s (first heartbeat)", hb.device_id)
                self._devices[hb.device_id] = DeviceRecord(
                    device_id=hb.device_id,
                    hardware=hb.hardware,
                )
            rec = self._devices[hb.device_id]
            rec.apply_heartbeat(hb)
            return rec.dequeue_command()

    # ------------------------------------------------------------------
    # Command dispatch
    # ------------------------------------------------------------------

    def enqueue_command(self, device_id: str, cmd: FleetCommand) -> bool:
        """Queue *cmd* for delivery to *device_id*.

        Returns False if the device is not registered.
        """
        with self._lock:
            if device_id not in self._devices:
                return False
            self._devices[device_id].enqueue_command(cmd)
            return True

    def broadcast_command(self, cmd: FleetCommand) -> list[str]:
        """Queue *cmd* for every registered device.

        Returns the list of device IDs that received the command.
        """
        with self._lock:
            targets = list(self._devices.keys())
            for rec in self._devices.values():
                rec.enqueue_command(cmd)
        logger.info("Broadcast command %r to %d devices", cmd.action, len(targets))
        return targets

    def deploy_model(self, model: str, device_ids: list[str] | None = None) -> list[str]:
        """Queue a ``pull-model`` command on the specified devices (or all).

        Parameters
        ----------
        model:
            Ollama model name, e.g. ``qwen2.5-coder:7b``.
        device_ids:
            Target device IDs.  ``None`` means fleet-wide broadcast.

        Returns the list of device IDs targeted.
        """
        cmd = FleetCommand(action="pull-model", params={"model": model})
        with self._lock:
            targets = device_ids if device_ids is not None else list(self._devices.keys())
            reached: list[str] = []
            for dev_id in targets:
                if dev_id in self._devices:
                    self._devices[dev_id].enqueue_command(cmd)
                    reached.append(dev_id)
        logger.info("Queued model deploy %r on %d devices", model, len(reached))
        return reached

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_device(self, device_id: str) -> DeviceRecord | None:
        """Return the record for *device_id*, or None if not found."""
        with self._lock:
            return self._devices.get(device_id)

    def list_devices(self) -> list[dict[str, Any]]:
        """Return a list of all device summary dicts."""
        with self._lock:
            return [rec.to_dict() for rec in self._devices.values()]

    def device_count(self) -> int:
        """Return the total number of registered devices."""
        with self._lock:
            return len(self._devices)

    def online_count(self) -> int:
        """Return the number of devices that sent a heartbeat recently."""
        with self._lock:
            return sum(1 for rec in self._devices.values() if rec.is_online())

    def summary(self) -> dict[str, Any]:
        """Return an aggregated fleet summary for the dashboard."""
        with self._lock:
            total = len(self._devices)
            online = sum(1 for r in self._devices.values() if r.is_online())
            all_models: set[str] = set()
            for r in self._devices.values():
                all_models.update(r.loaded_models)
            return {
                "total_devices": total,
                "online_devices": online,
                "offline_devices": total - online,
                "unique_models": sorted(all_models),
            }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_registry: FleetRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> FleetRegistry:
    """Return the process-wide :class:`FleetRegistry` singleton."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = FleetRegistry()
    return _registry
