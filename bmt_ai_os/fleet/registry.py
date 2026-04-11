"""Fleet registry with SQLite persistence for BMT AI OS.

Maintains an in-memory cache for hot-path reads (heartbeats) while persisting
all mutations (register, heartbeat, enqueue_command) to a SQLite database so
state survives controller restarts.

Configuration
-------------
``BMT_FLEET_DB``
    Path to the SQLite database file.
    Default: ``/tmp/bmt-fleet.db``
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generator

from .models import DeviceHeartbeat, FleetCommand

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = "/tmp/bmt-fleet.db"
_ENV_DB_PATH = "BMT_FLEET_DB"

# Devices are considered online if their last heartbeat was within this window.
_ONLINE_THRESHOLD_SECONDS = 120


# ---------------------------------------------------------------------------
# In-memory device record
# ---------------------------------------------------------------------------


@dataclass
class DeviceRecord:
    """Full state of a registered device kept in the in-memory cache."""

    device_id: str
    hostname: str = ""
    os_version: str = ""
    arch: str = ""
    board: str = ""
    cpu_model: str = ""
    cpu_cores: int = 0
    memory_total_mb: int = 0
    disk_total_gb: float = 0.0
    registered_at: str = ""
    last_seen: str = ""
    last_heartbeat: dict[str, Any] = field(default_factory=dict)
    pending_commands: list[FleetCommand] = field(default_factory=list)
    # Extended fields populated by heartbeats
    hardware: dict[str, Any] = field(default_factory=dict)
    loaded_models: list[str] = field(default_factory=list)
    service_health: dict[str, str] = field(default_factory=dict)
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    disk_percent: float = 0.0

    def __post_init__(self) -> None:
        if not self.registered_at:
            self.registered_at = datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # Heartbeat helpers
    # ------------------------------------------------------------------

    def apply_heartbeat(self, hb: DeviceHeartbeat) -> None:
        """Update device state from a heartbeat snapshot."""
        self.last_seen = hb.timestamp
        self.os_version = hb.os_version
        self.hardware = hb.hardware
        self.loaded_models = hb.loaded_models
        self.service_health = hb.service_health
        self.cpu_percent = hb.cpu_percent
        self.memory_percent = hb.memory_percent
        self.disk_percent = hb.disk_percent
        self.last_heartbeat = hb.to_dict()

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    def is_online(self) -> bool:
        """Return True when the last heartbeat was recent enough."""
        if not self.last_seen:
            return False
        try:
            ts = datetime.fromisoformat(self.last_seen)
            now = datetime.now(timezone.utc)
            # Make ts timezone-aware if it isn't already
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            delta = (now - ts).total_seconds()
            return delta <= _ONLINE_THRESHOLD_SECONDS
        except (ValueError, TypeError):
            return False

    # ------------------------------------------------------------------
    # Command queue helpers
    # ------------------------------------------------------------------

    def pending_command_count(self) -> int:
        """Return the number of pending commands in the queue."""
        return len(self.pending_commands)

    def enqueue_command(self, cmd: FleetCommand) -> None:
        """Append a command to this device's pending queue."""
        self.pending_commands.append(cmd)

    def dequeue_command(self) -> FleetCommand:
        """Pop and return the next pending command, or a noop."""
        if self.pending_commands:
            return self.pending_commands.pop(0)
        return FleetCommand(action=None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "hostname": self.hostname,
            "os_version": self.os_version,
            "arch": self.arch,
            "board": self.board,
            "cpu_model": self.cpu_model,
            "cpu_cores": self.cpu_cores,
            "memory_total_mb": self.memory_total_mb,
            "disk_total_gb": self.disk_total_gb,
            "registered_at": self.registered_at,
            "last_seen": self.last_seen,
            "last_heartbeat": self.last_heartbeat,
            "hardware": self.hardware,
            "loaded_models": self.loaded_models,
            "service_health": self.service_health,
            "cpu_percent": self.cpu_percent,
            "memory_percent": self.memory_percent,
            "disk_percent": self.disk_percent,
            "online": self.is_online(),
            "pending_commands": [
                {
                    "action": c.action,
                    "params": c.params,
                    "command_id": c.command_id,
                    "status": c.status,
                }
                for c in self.pending_commands
            ],
        }


# ---------------------------------------------------------------------------
# FleetRegistry
# ---------------------------------------------------------------------------


class FleetRegistry:
    """Thread-safe fleet registry with SQLite persistence.

    All writes go to SQLite immediately.  Reads use the in-memory cache so
    heartbeat processing is fast even under high device counts.

    Parameters
    ----------
    db_path:
        Path to the SQLite file.  Defaults to the value of ``BMT_FLEET_DB``
        env var, falling back to ``/tmp/bmt-fleet.db``.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.environ.get(_ENV_DB_PATH, _DEFAULT_DB_PATH)
        self._lock = threading.Lock()
        self._devices: dict[str, DeviceRecord] = {}
        self._init_db()
        self._load_from_db()

    # ------------------------------------------------------------------
    # SQLite helpers
    # ------------------------------------------------------------------

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        con = sqlite3.connect(self._db_path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def _init_db(self) -> None:
        """Create tables if they do not yet exist."""
        with self._conn() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    device_id        TEXT PRIMARY KEY,
                    hostname         TEXT NOT NULL DEFAULT '',
                    os_version       TEXT NOT NULL DEFAULT '',
                    arch             TEXT NOT NULL DEFAULT '',
                    board            TEXT NOT NULL DEFAULT '',
                    cpu_model        TEXT NOT NULL DEFAULT '',
                    cpu_cores        INTEGER NOT NULL DEFAULT 0,
                    memory_total_mb  INTEGER NOT NULL DEFAULT 0,
                    disk_total_gb    REAL    NOT NULL DEFAULT 0.0,
                    registered_at    TEXT NOT NULL,
                    last_seen        TEXT NOT NULL,
                    last_heartbeat   TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_commands (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id   TEXT    NOT NULL,
                    command_id  TEXT    NOT NULL UNIQUE,
                    action      TEXT    NOT NULL,
                    params      TEXT    NOT NULL DEFAULT '{}',
                    status      TEXT    NOT NULL DEFAULT 'pending',
                    created_at  TEXT    NOT NULL,
                    FOREIGN KEY (device_id) REFERENCES devices(device_id)
                )
                """
            )

    # ------------------------------------------------------------------
    # Load from DB into cache on startup
    # ------------------------------------------------------------------

    def _load_from_db(self) -> None:
        """Populate the in-memory cache from SQLite.  Called once at init."""
        with self._conn() as con:
            device_rows = con.execute("SELECT * FROM devices").fetchall()
            cmd_rows = con.execute(
                "SELECT * FROM pending_commands WHERE status = 'pending' ORDER BY id"
            ).fetchall()

        # Index pending commands by device_id
        cmds_by_device: dict[str, list[FleetCommand]] = {}
        for row in cmd_rows:
            device_id = row["device_id"]
            cmds_by_device.setdefault(device_id, []).append(
                FleetCommand(
                    action=row["action"],
                    params=json.loads(row["params"]),
                    command_id=row["command_id"],
                    status=row["status"],
                )
            )

        for row in device_rows:
            try:
                last_heartbeat = json.loads(row["last_heartbeat"])
            except (json.JSONDecodeError, TypeError):
                last_heartbeat = {}

            record = DeviceRecord(
                device_id=row["device_id"],
                hostname=row["hostname"],
                os_version=row["os_version"],
                arch=row["arch"],
                board=row["board"],
                cpu_model=row["cpu_model"],
                cpu_cores=row["cpu_cores"],
                memory_total_mb=row["memory_total_mb"],
                disk_total_gb=row["disk_total_gb"],
                registered_at=row["registered_at"],
                last_seen=row["last_seen"],
                last_heartbeat=last_heartbeat,
                pending_commands=cmds_by_device.get(row["device_id"], []),
            )
            self._devices[record.device_id] = record

        logger.info(
            "Fleet registry loaded %d device(s) from %s",
            len(self._devices),
            self._db_path,
        )

    # ------------------------------------------------------------------
    # DB write helpers (called while holding self._lock)
    # ------------------------------------------------------------------

    def _upsert_device_db(self, record: DeviceRecord) -> None:
        with self._conn() as con:
            con.execute(
                """
                INSERT INTO devices
                    (device_id, hostname, os_version, arch, board, cpu_model,
                     cpu_cores, memory_total_mb, disk_total_gb, registered_at,
                     last_seen, last_heartbeat)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(device_id) DO UPDATE SET
                    hostname        = excluded.hostname,
                    os_version      = excluded.os_version,
                    arch            = excluded.arch,
                    board           = excluded.board,
                    cpu_model       = excluded.cpu_model,
                    cpu_cores       = excluded.cpu_cores,
                    memory_total_mb = excluded.memory_total_mb,
                    disk_total_gb   = excluded.disk_total_gb,
                    last_seen       = excluded.last_seen,
                    last_heartbeat  = excluded.last_heartbeat
                """,
                (
                    record.device_id,
                    record.hostname,
                    record.os_version,
                    record.arch,
                    record.board,
                    record.cpu_model,
                    record.cpu_cores,
                    record.memory_total_mb,
                    record.disk_total_gb,
                    record.registered_at,
                    record.last_seen,
                    json.dumps(record.last_heartbeat),
                ),
            )

    def _insert_command_db(self, device_id: str, cmd: FleetCommand) -> None:
        with self._conn() as con:
            con.execute(
                """
                INSERT INTO pending_commands
                    (device_id, command_id, action, params, status, created_at)
                VALUES (?,?,?,?,?,?)
                """,
                (
                    device_id,
                    cmd.command_id,
                    cmd.action or "",
                    json.dumps(cmd.params),
                    cmd.status,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def _mark_command_delivered_db(self, command_id: str) -> None:
        with self._conn() as con:
            con.execute(
                "UPDATE pending_commands SET status = 'delivered' WHERE command_id = ?",
                (command_id,),
            )

    def _delete_device_db(self, device_id: str) -> None:
        with self._conn() as con:
            con.execute("DELETE FROM pending_commands WHERE device_id = ?", (device_id,))
            con.execute("DELETE FROM devices WHERE device_id = ?", (device_id,))

    # ------------------------------------------------------------------
    # Public API — SQLite-backed (primary interface)
    # ------------------------------------------------------------------

    def register(self, info: dict[str, Any]) -> DeviceRecord:
        """Register or re-register a device (dict-based interface).

        Parameters
        ----------
        info:
            Dict with at minimum ``device_id``.  All other fields default to
            empty strings / zero if missing.

        Returns the resulting :class:`DeviceRecord`.
        """
        device_id = info["device_id"]
        now = datetime.now(timezone.utc).isoformat()

        with self._lock:
            existing = self._devices.get(device_id)
            registered_at = existing.registered_at if existing else now
            # Preserve last_seen from an existing record so online-status is
            # not reset by a re-registration.  New devices start with an empty
            # last_seen so they are considered offline until the first heartbeat.
            last_seen = existing.last_seen if existing else ""

            record = DeviceRecord(
                device_id=device_id,
                hostname=info.get("hostname", ""),
                os_version=info.get("os_version", ""),
                arch=info.get("arch", ""),
                board=info.get("board", ""),
                cpu_model=info.get("cpu_model", ""),
                cpu_cores=int(info.get("cpu_cores", 0)),
                memory_total_mb=int(info.get("memory_total_mb", 0)),
                disk_total_gb=float(info.get("disk_total_gb", 0.0)),
                registered_at=registered_at,
                last_seen=last_seen,
                last_heartbeat=existing.last_heartbeat if existing else {},
                pending_commands=existing.pending_commands if existing else [],
            )
            self._devices[device_id] = record
            self._upsert_device_db(record)

        logger.info("Fleet: registered device %s (%s)", device_id, record.hostname)
        return record

    def heartbeat(self, hb: DeviceHeartbeat) -> FleetCommand:
        """Record a heartbeat and return the next pending command (or noop).

        The first pending command is popped from the queue and returned.
        Its status is updated to ``'delivered'`` in SQLite.
        """
        now = datetime.now(timezone.utc).isoformat()

        with self._lock:
            record = self._devices.get(hb.device_id)
            if record is None:
                # Auto-register on first heartbeat with minimal info
                record = DeviceRecord(
                    device_id=hb.device_id,
                    hostname="",
                    os_version=hb.os_version,
                    arch="",
                    board="",
                    cpu_model="",
                    cpu_cores=0,
                    memory_total_mb=0,
                    disk_total_gb=0.0,
                    registered_at=now,
                    last_seen=now,
                    last_heartbeat={},
                    pending_commands=[],
                )

            record.last_seen = now
            record.os_version = hb.os_version
            record.last_heartbeat = hb.to_dict()
            # Also update extended fields
            record.hardware = hb.hardware
            record.loaded_models = hb.loaded_models
            record.service_health = hb.service_health
            record.cpu_percent = hb.cpu_percent
            record.memory_percent = hb.memory_percent
            record.disk_percent = hb.disk_percent
            self._devices[hb.device_id] = record
            self._upsert_device_db(record)

            # Pop next pending command
            if record.pending_commands:
                cmd = record.pending_commands.pop(0)
                self._mark_command_delivered_db(cmd.command_id)
            else:
                cmd = FleetCommand(action=None)

        return cmd

    def enqueue_command(
        self,
        device_id: str,
        action_or_cmd: str | FleetCommand,
        params: dict[str, Any] | None = None,
        command_id: str | None = None,
    ) -> FleetCommand | bool:
        """Add a command to the pending queue for *device_id*.

        Accepts two calling conventions:
        1. New API: ``enqueue_command(device_id, action_str, params, command_id)``
           Returns the created :class:`FleetCommand` or raises :exc:`KeyError`
           if the device is not registered.
        2. Legacy API: ``enqueue_command(device_id, cmd_object)``
           Returns ``True`` if enqueued, ``False`` if device not found.
        """
        # Detect legacy (FleetCommand object) vs new (str action) calling convention
        legacy_mode = isinstance(action_or_cmd, FleetCommand)

        if legacy_mode:
            cmd_obj: FleetCommand = action_or_cmd  # type: ignore[assignment]
            # Ensure command_id is set
            if not cmd_obj.command_id:
                cmd_obj = FleetCommand(
                    action=cmd_obj.action,
                    params=cmd_obj.params,
                    command_id=str(uuid.uuid4()),
                    status=cmd_obj.status,
                )
        else:
            action_str: str = action_or_cmd  # type: ignore[assignment]
            cmd_obj = FleetCommand(
                action=action_str,
                params=params or {},
                command_id=command_id or str(uuid.uuid4()),
                status="pending",
            )

        with self._lock:
            if device_id not in self._devices:
                if legacy_mode:
                    return False
                raise KeyError(f"Device not registered: {device_id!r}")

            self._devices[device_id].pending_commands.append(cmd_obj)
            self._insert_command_db(device_id, cmd_obj)

        logger.info(
            "Fleet: enqueued command %r for device %s (command_id=%s)",
            cmd_obj.action,
            device_id,
            cmd_obj.command_id,
        )

        if legacy_mode:
            return True
        return cmd_obj

    # ------------------------------------------------------------------
    # Public API — legacy / routes interface
    # ------------------------------------------------------------------

    def register_device(
        self,
        device_id: str,
        hostname: str = "",
        arch: str = "",
        board: str = "",
        hardware: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> DeviceRecord:
        """Register or re-register a device (keyword-argument interface).

        Wraps :meth:`register` for compatibility with routes and legacy tests.
        """
        info: dict[str, Any] = {
            "device_id": device_id,
            "hostname": hostname,
            "arch": arch,
            "board": board,
        }
        if hardware:
            info.update(hardware)
        info.update(kwargs)
        return self.register(info)

    def apply_heartbeat(self, hb: DeviceHeartbeat) -> FleetCommand:
        """Apply a heartbeat and return next pending command (legacy alias).

        Identical to :meth:`heartbeat` but uses :meth:`DeviceRecord.apply_heartbeat`
        on the cached record so that the extended fields (loaded_models, etc.)
        are properly updated.
        """
        return self.heartbeat(hb)

    def remove_device(self, device_id: str) -> bool:
        """Remove a device from the registry.

        Returns ``True`` if the device existed and was removed, ``False`` otherwise.
        """
        with self._lock:
            if device_id not in self._devices:
                return False
            del self._devices[device_id]
            self._delete_device_db(device_id)
        logger.info("Fleet: removed device %s", device_id)
        return True

    def broadcast_command(self, cmd: FleetCommand) -> list[str]:
        """Enqueue *cmd* on every registered device.

        Returns the list of device IDs that received the command.
        """
        with self._lock:
            device_ids = list(self._devices.keys())

        targeted: list[str] = []
        for device_id in device_ids:
            # Create a fresh copy so each device gets a unique command_id
            new_cmd = FleetCommand(
                action=cmd.action,
                params=dict(cmd.params),
                command_id=str(uuid.uuid4()),
                status="pending",
            )
            result = self.enqueue_command(device_id, new_cmd)
            if result is not False:
                targeted.append(device_id)
        return targeted

    def deploy_model(
        self,
        model: str,
        device_ids: list[str] | None = None,
    ) -> list[str]:
        """Queue a ``pull-model`` command on one or all devices.

        Parameters
        ----------
        model:
            Model tag to pull (e.g. ``"qwen2.5-coder:7b"``).
        device_ids:
            Specific device IDs to target.  Broadcasts to all if ``None``.

        Returns the list of device IDs targeted.
        """
        with self._lock:
            all_ids = list(self._devices.keys())

        targets = device_ids if device_ids is not None else all_ids
        targeted: list[str] = []
        for device_id in targets:
            cmd = FleetCommand(
                action="pull-model",
                params={"model": model},
                command_id=str(uuid.uuid4()),
                status="pending",
            )
            result = self.enqueue_command(device_id, cmd)
            if result is not False:
                targeted.append(device_id)
        return targeted

    def online_count(self) -> int:
        """Return the number of devices currently considered online."""
        with self._lock:
            return sum(1 for r in self._devices.values() if r.is_online())

    def summary(self) -> dict[str, Any]:
        """Return aggregated fleet-wide metrics."""
        with self._lock:
            records = list(self._devices.values())

        total = len(records)
        online = sum(1 for r in records if r.is_online())
        unique_models: set[str] = set()
        for r in records:
            unique_models.update(r.loaded_models)

        return {
            "total_devices": total,
            "online_devices": online,
            "offline_devices": total - online,
            "unique_models": sorted(unique_models),
        }

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    def get_device(self, device_id: str) -> DeviceRecord | None:
        """Return the cached :class:`DeviceRecord` or ``None``."""
        with self._lock:
            return self._devices.get(device_id)

    def list_devices(self) -> list[dict[str, Any]]:
        """Return all registered devices as a list of dicts."""
        with self._lock:
            return [r.to_dict() for r in self._devices.values()]

    def device_count(self) -> int:
        """Return the number of registered devices."""
        with self._lock:
            return len(self._devices)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_registry: FleetRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> FleetRegistry:
    """Return the process-level :class:`FleetRegistry` singleton."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = FleetRegistry()
    return _registry
