"""Data models for BMT AI OS fleet management.

All models are plain dataclasses — no external dependencies beyond stdlib.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class DeviceInfo:
    """Static information about the device, collected once at startup."""

    device_id: str
    hostname: str
    os_version: str
    arch: str
    board: str
    cpu_model: str
    cpu_cores: int
    memory_total_mb: int
    disk_total_gb: float


@dataclass
class DeviceHeartbeat:
    """Periodic status snapshot sent from agent to fleet server."""

    device_id: str
    timestamp: str
    os_version: str
    hardware: dict[str, Any]
    loaded_models: list[str]
    service_health: dict[str, str]
    cpu_percent: float
    memory_percent: float
    disk_percent: float

    @classmethod
    def now(
        cls,
        device_id: str,
        os_version: str,
        hardware: dict[str, Any],
        loaded_models: list[str],
        service_health: dict[str, str],
        cpu_percent: float,
        memory_percent: float,
        disk_percent: float,
    ) -> "DeviceHeartbeat":
        """Construct a heartbeat with the current UTC timestamp."""
        return cls(
            device_id=device_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            os_version=os_version,
            hardware=hardware,
            loaded_models=loaded_models,
            service_health=service_health,
            cpu_percent=cpu_percent,
            memory_percent=memory_percent,
            disk_percent=disk_percent,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict suitable for JSON POST."""
        return {
            "device_id": self.device_id,
            "timestamp": self.timestamp,
            "os_version": self.os_version,
            "hardware": self.hardware,
            "loaded_models": self.loaded_models,
            "service_health": self.service_health,
            "cpu_percent": self.cpu_percent,
            "memory_percent": self.memory_percent,
            "disk_percent": self.disk_percent,
        }


@dataclass
class FleetCommand:
    """A command dispatched by the fleet server to a device agent.

    The server responds to a heartbeat POST with zero or one command.
    Absent a command the server returns ``{"action": null}``.

    Supported actions
    -----------------
    ``update``
        Trigger a system/package update.  ``params`` may carry
        ``{"version": "2026.5.0"}`` or be empty.

    ``pull-model``
        Pull an Ollama model.  ``params`` must contain
        ``{"model": "<name>"}`` e.g. ``{"model": "qwen2.5-coder:7b"}``.

    ``restart-service``
        Restart a named AI-stack service.  ``params`` must contain
        ``{"service": "<name>"}`` e.g. ``{"service": "ollama"}``.
    """

    action: str | None
    params: dict[str, Any] = field(default_factory=dict)
    command_id: str = ""
    status: str = "pending"

    VALID_ACTIONS: tuple[str, ...] = field(
        default=("update", "pull-model", "restart-service"), init=False, repr=False, compare=False
    )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FleetCommand":
        """Parse a command dict as returned by the fleet server."""
        return cls(
            action=data.get("action"),
            params=data.get("params") or {},
            command_id=data.get("command_id", ""),
            status=data.get("status", "pending"),
        )

    def is_noop(self) -> bool:
        """Return True when the server sent no actionable command."""
        return self.action is None
