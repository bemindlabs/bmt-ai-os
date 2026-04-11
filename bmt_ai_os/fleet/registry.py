"""Fleet registry with SQLite persistence for BMT AI OS.

Maintains an in-memory cache for hot-path reads (heartbeats) while persisting
all mutations (register, heartbeat, enqueue_command) to a SQLite database so
state survives controller restarts.

Configuration
-------------
``BMT_FLEET_DB``
    Path to the SQLite database file.
    Default: ``/var/lib/bmt/fleet.db``
    For dev/test a temp file is used when the default path is not writable.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generator

from .models import DeviceHeartbeat, FleetCommand

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = "/var/lib/bmt/fleet.db"
_ENV_DB_PATH = "BMT_FLEET_DB"

# How many seconds without a heartbeat before a device is considered offline
_ONLINE_THRESHOLD_SECONDS = 120


# ---------------------------------------------------------------------------
# In-memory device record
# ---------------------------------------------------------------------------


@dataclass
class DeviceRecord:
    """Full state of a registered device kept in the in-memory cache.

    All fields after *device_id* have defaults so the record can be created
    with minimal information (e.g. during auto-registration on first heartbeat).
    """

    device_id: str
    hostname: str = ""
    os_version: str = ""
    arch: str = ""
    board: str = ""
    cpu_model: str = ""
    cpu_cores: int = 0
    memory_total_mb: int = 0
    disk_total_gb: float = 0.0
    hardware: dict[str, Any] = field(default_factory=dict)
    registered_at: str = ""
    last_seen: str = ""
    loaded_models: list[str] = field(default_factory=list)
    service_health: dict[str, str] = field(default_factory=dict)
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    disk_percent: float = 0.0
    pending_commands: list[FleetCommand] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.registered_at:
            self.registered_at = datetime.now(timezone.utc).isoformat()
        if not self.last_seen:
            self.last_seen = ""

    # ------------------------------------------------------------------
    # Heartbeat application
    # ------------------------------------------------------------------

    def apply_heartbeat(self, hb: DeviceHeartbeat) -> None:
        """Update the record from a heartbeat."""
        self.last_seen = hb.timestamp
        self.os_version = hb.os_version
        self.hardware = hb.hardware
        self.loaded_models = hb.loaded_models
        self.service_health = hb.service_health
        self.cpu_percent = hb.cpu_percent
        self.memory_percent = hb.memory_percent
        self.disk_percent = hb.disk_percent

    # ------------------------------------------------------------------
    # Online status
    # ------------------------------------------------------------------

    def is_online(self) -> bool:
        """Return True if the device sent a heartbeat within the threshold."""
        if not self.last_seen:
            return False
        try:
            from datetime import timezone as _tz

            last = datetime.fromisoformat(self.last_seen)
            now = datetime.now(_tz.utc)
            if last.tzinfo is None:
                last = last.replace(tzinfo=_tz.utc)
            delta = (now - last).total_seconds()
            return delta < _ONLINE_THRESHOLD_SECONDS
        except (ValueError, TypeError):
            return False

    # ------------------------------------------------------------------
    # Command queue
    # ------------------------------------------------------------------

    def enqueue_command(self, cmd: FleetCommand) -> None:
        """Add a command to the pending queue."""
        self.pending_commands.append(cmd)

    def dequeue_command(self) -> FleetCommand:
        """Pop and return the next pending command, or a noop."""
        if self.pending_commands:
            return self.pending_commands.pop(0)
        return FleetCommand(action=None)

    def pending_command_count(self) -> int:
        """Return the number of pending commands."""
        return len(self.pending_commands)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

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
            "hardware": self.hardware,
            "registered_at": self.registered_at,
            "last_seen": self.last_seen,
            "online": self.is_online(),
            "loaded_models": self.loaded_models,
            "service_health": self.service_health,
            "cpu_percent": self.cpu_percent,
            "memory_percent": self.memory_percent,
            "disk_percent": self.disk_percent,
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
        env var, falling back to ``/var/lib/bmt/fleet.db``.  When the default
        path is not writable (e.g. during development) a temporary file is
        created automatically.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = self._resolve_db_path(db_path)
        self._lock = threading.Lock()
        self._devices: dict[str, DeviceRecord] = {}
        self._init_db()
        self._load_from_db()

    # ------------------------------------------------------------------
    # DB path resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_db_path(db_path: str | None) -> str:
        """Return a writable database path.

        Resolution order:
        1. Explicit *db_path* argument.
        2. ``BMT_FLEET_DB`` environment variable.
        3. Default ``/var/lib/bmt/fleet.db``.
        4. Fallback: a temp file when the default directory isn't writable.
        """
        if db_path:
            return db_path

        from_env = os.environ.get(_ENV_DB_PATH)
        if from_env:
            return from_env

        import pathlib

        target = pathlib.Path(_DEFAULT_DB_PATH)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            # Quick writability test
            test = target.parent / ".bmt-fleet-write-test"
            test.touch()
            test.unlink()
            return str(target)
        except OSError:
            # Default path not writable — use a temp file (dev/test mode)
            fd, tmp_path = tempfile.mkstemp(prefix="bmt-fleet-", suffix=".db")
            os.close(fd)
            logger.warning(
                "Fleet DB path %s is not writable; using temp file %s",
                _DEFAULT_DB_PATH,
                tmp_path,
            )
            return tmp_path

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
                    hardware         TEXT NOT NULL DEFAULT '{}',
                    registered_at    TEXT NOT NULL,
                    last_seen        TEXT NOT NULL DEFAULT '',
                    last_heartbeat   TEXT NOT NULL DEFAULT '{}',
                    loaded_models    TEXT NOT NULL DEFAULT '[]',
                    service_health   TEXT NOT NULL DEFAULT '{}',
                    cpu_percent      REAL NOT NULL DEFAULT 0.0,
                    memory_percent   REAL NOT NULL DEFAULT 0.0,
                    disk_percent     REAL NOT NULL DEFAULT 0.0
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
            # Migrate existing schema: add new columns if missing
            for col, col_def in [
                ("hardware", "TEXT NOT NULL DEFAULT '{}'"),
                ("last_heartbeat", "TEXT NOT NULL DEFAULT '{}'"),
                ("loaded_models", "TEXT NOT NULL DEFAULT '[]'"),
                ("service_health", "TEXT NOT NULL DEFAULT '{}'"),
                ("cpu_percent", "REAL NOT NULL DEFAULT 0.0"),
                ("memory_percent", "REAL NOT NULL DEFAULT 0.0"),
                ("disk_percent", "REAL NOT NULL DEFAULT 0.0"),
            ]:
                try:
                    con.execute(f"ALTER TABLE devices ADD COLUMN {col} {col_def}")
                except sqlite3.OperationalError:
                    pass  # column already exists

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
                hardware = json.loads(row["hardware"])
            except (json.JSONDecodeError, TypeError, IndexError):
                hardware = {}
            try:
                loaded_models = json.loads(row["loaded_models"])
            except (json.JSONDecodeError, TypeError, IndexError):
                loaded_models = []
            try:
                service_health = json.loads(row["service_health"])
            except (json.JSONDecodeError, TypeError, IndexError):
                service_health = {}

            # Gracefully handle old schema (no last_heartbeat column)
            keys = row.keys()
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
                hardware=hardware,
                registered_at=row["registered_at"],
                last_seen=row["last_seen"] if "last_seen" in keys else "",
                loaded_models=loaded_models,
                service_health=service_health,
                cpu_percent=float(row["cpu_percent"]) if "cpu_percent" in keys else 0.0,
                memory_percent=float(row["memory_percent"]) if "memory_percent" in keys else 0.0,
                disk_percent=float(row["disk_percent"]) if "disk_percent" in keys else 0.0,
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
        # Build a last_heartbeat dict from record fields (for backward compat with tests)
        last_heartbeat = {
            "device_id": record.device_id,
            "timestamp": record.last_seen,
            "os_version": record.os_version,
            "hardware": record.hardware,
            "loaded_models": record.loaded_models,
            "service_health": record.service_health,
            "cpu_percent": record.cpu_percent,
            "memory_percent": record.memory_percent,
            "disk_percent": record.disk_percent,
        }
        with self._conn() as con:
            con.execute(
                """
                INSERT INTO devices
                    (device_id, hostname, os_version, arch, board, cpu_model,
                     cpu_cores, memory_total_mb, disk_total_gb, hardware,
                     registered_at, last_seen, last_heartbeat,
                     loaded_models, service_health,
                     cpu_percent, memory_percent, disk_percent)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(device_id) DO UPDATE SET
                    hostname        = excluded.hostname,
                    os_version      = excluded.os_version,
                    arch            = excluded.arch,
                    board           = excluded.board,
                    cpu_model       = excluded.cpu_model,
                    cpu_cores       = excluded.cpu_cores,
                    memory_total_mb = excluded.memory_total_mb,
                    disk_total_gb   = excluded.disk_total_gb,
                    hardware        = excluded.hardware,
                    last_seen       = excluded.last_seen,
                    last_heartbeat  = excluded.last_heartbeat,
                    loaded_models   = excluded.loaded_models,
                    service_health  = excluded.service_health,
                    cpu_percent     = excluded.cpu_percent,
                    memory_percent  = excluded.memory_percent,
                    disk_percent    = excluded.disk_percent
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
                    json.dumps(record.hardware),
                    record.registered_at,
                    record.last_seen,
                    json.dumps(last_heartbeat),
                    json.dumps(record.loaded_models),
                    json.dumps(record.service_health),
                    record.cpu_percent,
                    record.memory_percent,
                    record.disk_percent,
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
    # Public API
    # ------------------------------------------------------------------

    def register(self, info: dict[str, Any]) -> DeviceRecord:
        """Register or re-register a device (dict-based API).

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

            hardware = info.get("hardware") or {}
            if not isinstance(hardware, dict):
                hardware = {}

            record = DeviceRecord(
                device_id=device_id,
                hostname=info.get("hostname", ""),
                os_version=info.get("os_version", ""),
                arch=info.get("arch", hardware.get("arch", "")),
                board=info.get("board", hardware.get("board", "")),
                cpu_model=info.get("cpu_model", ""),
                cpu_cores=int(info.get("cpu_cores", 0)),
                memory_total_mb=int(info.get("memory_total_mb", 0)),
                disk_total_gb=float(info.get("disk_total_gb", 0.0)),
                hardware=hardware,
                registered_at=registered_at,
                last_seen=existing.last_seen if existing else "",
                loaded_models=existing.loaded_models if existing else [],
                service_health=existing.service_health if existing else {},
                cpu_percent=existing.cpu_percent if existing else 0.0,
                memory_percent=existing.memory_percent if existing else 0.0,
                disk_percent=existing.disk_percent if existing else 0.0,
                pending_commands=existing.pending_commands if existing else [],
            )
            self._devices[device_id] = record
            self._upsert_device_db(record)

        logger.info("Fleet: registered device %s (%s)", device_id, record.hostname)
        return record

    def register_device(
        self,
        device_id: str,
        hostname: str = "",
        arch: str = "",
        board: str = "",
        hardware: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> DeviceRecord:
        """Register or re-register a device (keyword API).

        Convenience wrapper around :meth:`register` for the common case.
        """
        info: dict[str, Any] = {
            "device_id": device_id,
            "hostname": hostname,
            "arch": arch,
            "board": board,
        }
        if hardware:
            info["hardware"] = hardware
        info.update(kwargs)
        return self.register(info)

    def heartbeat(self, hb: DeviceHeartbeat) -> FleetCommand:
        """Record a heartbeat and return the next pending command (or noop).

        The first pending command is popped from the queue and returned.
        Its status is updated to ``'delivered'`` in SQLite.
        """
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
                    hardware=hb.hardware,
                    registered_at=datetime.now(timezone.utc).isoformat(),
                )

            record.apply_heartbeat(hb)
            self._devices[hb.device_id] = record
            self._upsert_device_db(record)

            # Pop next pending command
            if record.pending_commands:
                cmd = record.pending_commands.pop(0)
                self._mark_command_delivered_db(cmd.command_id)
            else:
                cmd = FleetCommand(action=None)

        return cmd

    def apply_heartbeat(self, hb: DeviceHeartbeat) -> FleetCommand:
        """Alias for :meth:`heartbeat` used by tests."""
        return self.heartbeat(hb)

    def enqueue_command(
        self,
        device_id: str,
        cmd_or_action: FleetCommand | str,
        params: dict[str, Any] | None = None,
        command_id: str | None = None,
    ) -> FleetCommand | bool:
        """Add a command to the pending queue for *device_id*.

        Accepts either a :class:`FleetCommand` object or an action string.

        Returns the created :class:`FleetCommand` when *cmd_or_action* is a
        string, or the passed :class:`FleetCommand` when it is already a
        command object.  Returns ``False`` when *device_id* is not registered.
        """
        _is_cmd_object = isinstance(cmd_or_action, FleetCommand)

        with self._lock:
            if device_id not in self._devices:
                # When called with a FleetCommand object return False (routes use this).
                # When called with an action string raise KeyError (old API used by legacy tests).
                if _is_cmd_object:
                    return False
                raise KeyError(f"Device not registered: {device_id!r}")

            if _is_cmd_object:
                cmd = cmd_or_action
                # Ensure the command has a command_id
                if not cmd.command_id:
                    cmd.command_id = str(uuid.uuid4())
            else:
                cmd = FleetCommand(
                    action=cmd_or_action,
                    params=params or {},
                    command_id=command_id or str(uuid.uuid4()),
                    status="pending",
                )

            self._devices[device_id].pending_commands.append(cmd)
            try:
                self._insert_command_db(device_id, cmd)
            except sqlite3.IntegrityError:
                # Duplicate command_id — ignore (idempotent)
                pass

        logger.info(
            "Fleet: enqueued command %r for device %s (command_id=%s)",
            cmd.action,
            device_id,
            cmd.command_id,
        )
        return cmd

    def broadcast_command(self, cmd: FleetCommand) -> list[str]:
        """Enqueue *cmd* on all registered devices.

        Returns the list of device IDs that received the command.
        """
        with self._lock:
            targets = list(self._devices.keys())

        targeted: list[str] = []
        for device_id in targets:
            # Create a fresh copy with a unique command_id for each device
            device_cmd = FleetCommand(
                action=cmd.action,
                params=cmd.params,
                command_id=str(uuid.uuid4()),
                status="pending",
            )
            result = self.enqueue_command(device_id, device_cmd)
            if result is not False:
                targeted.append(device_id)
        return targeted

    def deploy_model(self, model: str, device_ids: list[str] | None = None) -> list[str]:
        """Queue a ``pull-model`` command on one or all devices.

        Parameters
        ----------
        model:
            Ollama model name to pull (e.g. ``"qwen2.5-coder:7b"``).
        device_ids:
            Subset of device IDs to target.  ``None`` means all devices.

        Returns the list of targeted device IDs.
        """
        with self._lock:
            if device_ids is None:
                targets = list(self._devices.keys())
            else:
                targets = [d for d in device_ids if d in self._devices]

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

    def remove(self, device_id: str) -> None:
        """Remove a registered device and its pending commands.

        Raises KeyError if *device_id* is not registered.
        """
        with self._lock:
            if device_id not in self._devices:
                raise KeyError(f"Device not registered: {device_id!r}")
            del self._devices[device_id]
            self._delete_device_db(device_id)

        logger.info("Fleet: removed device %s", device_id)

    def remove_device(self, device_id: str) -> bool:
        """Remove a registered device.

        Returns True if the device existed, False otherwise.
        """
        try:
            self.remove(device_id)
            return True
        except KeyError:
            return False

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

    def online_count(self) -> int:
        """Return the number of online devices."""
        with self._lock:
            return sum(1 for r in self._devices.values() if r.is_online())

    def summary(self) -> dict[str, Any]:
        """Return aggregated fleet-wide metrics."""
        with self._lock:
            devices = list(self._devices.values())

        total = len(devices)
        online = sum(1 for d in devices if d.is_online())
        all_models: set[str] = set()
        for d in devices:
            all_models.update(d.loaded_models)

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
    """Return the process-level :class:`FleetRegistry` singleton."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = FleetRegistry()
    return _registry
