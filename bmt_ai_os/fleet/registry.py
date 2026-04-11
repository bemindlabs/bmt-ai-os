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


# ---------------------------------------------------------------------------
# In-memory device record
# ---------------------------------------------------------------------------


@dataclass
class DeviceRecord:
    """Full state of a registered device kept in the in-memory cache."""

    device_id: str
    hostname: str
    os_version: str
    arch: str
    board: str
    cpu_model: str
    cpu_cores: int
    memory_total_mb: int
    disk_total_gb: float
    registered_at: str
    last_seen: str
    last_heartbeat: dict[str, Any] = field(default_factory=dict)
    pending_commands: list[FleetCommand] = field(default_factory=list)

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
    # Public API
    # ------------------------------------------------------------------

    def register(self, info: dict[str, Any]) -> DeviceRecord:
        """Register or re-register a device.

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
                last_seen=now,
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
        action: str,
        params: dict[str, Any] | None = None,
        command_id: str | None = None,
    ) -> FleetCommand:
        """Add a command to the pending queue for *device_id*.

        Parameters
        ----------
        device_id:
            Target device identifier.
        action:
            One of ``update``, ``pull-model``, ``restart-service``.
        params:
            Action-specific parameters (optional).
        command_id:
            Explicit command ID.  Auto-generated UUID4 if omitted.

        Returns the created :class:`FleetCommand`.

        Raises
        ------
        KeyError
            If *device_id* is not registered.
        """
        with self._lock:
            if device_id not in self._devices:
                raise KeyError(f"Device not registered: {device_id!r}")

            cmd = FleetCommand(
                action=action,
                params=params or {},
                command_id=command_id or str(uuid.uuid4()),
                status="pending",
            )
            self._devices[device_id].pending_commands.append(cmd)
            self._insert_command_db(device_id, cmd)

        logger.info(
            "Fleet: enqueued command %r for device %s (command_id=%s)",
            action,
            device_id,
            cmd.command_id,
        )
        return cmd

    def remove(self, device_id: str) -> None:
        """Remove a registered device and its pending commands.

        Raises
        ------
        KeyError
            If *device_id* is not registered.
        """
        with self._lock:
            if device_id not in self._devices:
                raise KeyError(f"Device not registered: {device_id!r}")
            del self._devices[device_id]
            self._delete_device_db(device_id)

        logger.info("Fleet: removed device %s", device_id)

    def get_device(self, device_id: str) -> DeviceRecord | None:
        """Return the cached :class:`DeviceRecord` or ``None``."""
        with self._lock:
            return self._devices.get(device_id)

    def list_devices(self) -> list[DeviceRecord]:
        """Return all registered devices as a list."""
        with self._lock:
            return list(self._devices.values())

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
