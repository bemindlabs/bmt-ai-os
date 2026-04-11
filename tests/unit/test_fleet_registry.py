"""Unit tests for bmt_ai_os.fleet.registry (SQLite persistence)."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from bmt_ai_os.fleet.models import DeviceHeartbeat
from bmt_ai_os.fleet.registry import DeviceRecord, FleetRegistry


def _make_registry(tmp_path: Path) -> FleetRegistry:
    """Return a fresh FleetRegistry backed by a temp SQLite file."""
    return FleetRegistry(db_path=str(tmp_path / "fleet.db"))


def _make_device_info(**overrides) -> dict:
    defaults = {
        "device_id": "dev-001",
        "hostname": "bmt-host",
        "os_version": "2026.4.11",
        "arch": "aarch64",
        "board": "rk3588",
        "cpu_model": "Cortex-A55",
        "cpu_cores": 8,
        "memory_total_mb": 8192,
        "disk_total_gb": 256.0,
    }
    defaults.update(overrides)
    return defaults


def _make_heartbeat(device_id: str = "dev-001") -> DeviceHeartbeat:
    return DeviceHeartbeat.now(
        device_id=device_id,
        os_version="2026.4.11",
        hardware={"board": "rk3588"},
        loaded_models=["qwen2.5:7b"],
        service_health={"ollama": "up"},
        cpu_percent=10.0,
        memory_percent=40.0,
        disk_percent=20.0,
    )


# ---------------------------------------------------------------------------
# Table creation
# ---------------------------------------------------------------------------


class TestDatabaseInit:
    def test_creates_devices_table(self, tmp_path):
        _make_registry(tmp_path)
        con = sqlite3.connect(str(tmp_path / "fleet.db"))
        tables = {
            row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        con.close()
        assert "devices" in tables

    def test_creates_pending_commands_table(self, tmp_path):
        _make_registry(tmp_path)
        con = sqlite3.connect(str(tmp_path / "fleet.db"))
        tables = {
            row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        con.close()
        assert "pending_commands" in tables


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------


class TestRegister:
    def test_register_returns_device_record(self, tmp_path):
        reg = _make_registry(tmp_path)
        record = reg.register(_make_device_info())
        assert isinstance(record, DeviceRecord)
        assert record.device_id == "dev-001"
        assert record.hostname == "bmt-host"

    def test_register_persists_to_db(self, tmp_path):
        reg = _make_registry(tmp_path)
        reg.register(_make_device_info())
        # Re-open DB and verify row exists
        con = sqlite3.connect(str(tmp_path / "fleet.db"))
        row = con.execute("SELECT device_id FROM devices WHERE device_id = 'dev-001'").fetchone()
        con.close()
        assert row is not None

    def test_register_increments_device_count(self, tmp_path):
        reg = _make_registry(tmp_path)
        reg.register(_make_device_info(device_id="d1"))
        reg.register(_make_device_info(device_id="d2"))
        assert reg.device_count() == 2

    def test_reregister_preserves_registered_at(self, tmp_path):
        reg = _make_registry(tmp_path)
        r1 = reg.register(_make_device_info())
        r2 = reg.register(_make_device_info(hostname="new-host"))
        assert r1.registered_at == r2.registered_at

    def test_reregister_updates_hostname(self, tmp_path):
        reg = _make_registry(tmp_path)
        reg.register(_make_device_info(hostname="old-host"))
        r2 = reg.register(_make_device_info(hostname="new-host"))
        assert r2.hostname == "new-host"


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------


class TestHeartbeat:
    def test_heartbeat_returns_noop_when_no_commands(self, tmp_path):
        reg = _make_registry(tmp_path)
        reg.register(_make_device_info())
        cmd = reg.heartbeat(_make_heartbeat())
        assert cmd.is_noop()

    def test_heartbeat_updates_last_seen(self, tmp_path):
        reg = _make_registry(tmp_path)
        reg.register(_make_device_info())
        hb = _make_heartbeat()
        reg.heartbeat(hb)
        record = reg.get_device("dev-001")
        assert record is not None
        assert record.last_seen != ""

    def test_heartbeat_auto_registers_unknown_device(self, tmp_path):
        reg = _make_registry(tmp_path)
        hb = _make_heartbeat("unknown-dev")
        reg.heartbeat(hb)
        assert reg.get_device("unknown-dev") is not None

    def test_heartbeat_persists_to_db(self, tmp_path):
        reg = _make_registry(tmp_path)
        reg.register(_make_device_info())
        reg.heartbeat(_make_heartbeat())
        con = sqlite3.connect(str(tmp_path / "fleet.db"))
        row = con.execute("SELECT last_seen FROM devices WHERE device_id = 'dev-001'").fetchone()
        con.close()
        assert row is not None
        assert row[0] != ""


# ---------------------------------------------------------------------------
# Enqueue command
# ---------------------------------------------------------------------------


class TestEnqueueCommand:
    def test_enqueue_returns_fleet_command(self, tmp_path):
        reg = _make_registry(tmp_path)
        reg.register(_make_device_info())
        cmd = reg.enqueue_command("dev-001", "pull-model", {"model": "qwen2.5:7b"})
        assert cmd.action == "pull-model"
        assert cmd.params == {"model": "qwen2.5:7b"}
        assert cmd.command_id != ""

    def test_enqueue_raises_for_unknown_device(self, tmp_path):
        reg = _make_registry(tmp_path)
        with pytest.raises(KeyError, match="not registered"):
            reg.enqueue_command("ghost-device", "update")

    def test_heartbeat_pops_queued_command(self, tmp_path):
        reg = _make_registry(tmp_path)
        reg.register(_make_device_info())
        reg.enqueue_command("dev-001", "update")
        cmd = reg.heartbeat(_make_heartbeat())
        assert cmd.action == "update"
        # Second heartbeat should be noop
        cmd2 = reg.heartbeat(_make_heartbeat())
        assert cmd2.is_noop()

    def test_enqueue_persists_to_db(self, tmp_path):
        reg = _make_registry(tmp_path)
        reg.register(_make_device_info())
        reg.enqueue_command("dev-001", "restart-service", {"service": "ollama"})
        con = sqlite3.connect(str(tmp_path / "fleet.db"))
        row = con.execute(
            "SELECT action FROM pending_commands WHERE device_id = 'dev-001'"
        ).fetchone()
        con.close()
        assert row is not None
        assert row[0] == "restart-service"

    def test_delivered_command_marked_in_db(self, tmp_path):
        reg = _make_registry(tmp_path)
        reg.register(_make_device_info())
        reg.enqueue_command("dev-001", "update")
        reg.heartbeat(_make_heartbeat())  # pops the command
        con = sqlite3.connect(str(tmp_path / "fleet.db"))
        row = con.execute(
            "SELECT status FROM pending_commands WHERE device_id = 'dev-001'"
        ).fetchone()
        con.close()
        assert row is not None
        # row is a plain tuple with one element (the status column)
        assert row[0] == "delivered"


# ---------------------------------------------------------------------------
# Remove
# ---------------------------------------------------------------------------


class TestRemove:
    def test_remove_deletes_device(self, tmp_path):
        reg = _make_registry(tmp_path)
        reg.register(_make_device_info())
        reg.remove("dev-001")
        assert reg.get_device("dev-001") is None

    def test_remove_deletes_from_db(self, tmp_path):
        reg = _make_registry(tmp_path)
        reg.register(_make_device_info())
        reg.remove("dev-001")
        con = sqlite3.connect(str(tmp_path / "fleet.db"))
        row = con.execute("SELECT device_id FROM devices WHERE device_id = 'dev-001'").fetchone()
        con.close()
        assert row is None

    def test_remove_raises_for_unknown_device(self, tmp_path):
        reg = _make_registry(tmp_path)
        with pytest.raises(KeyError):
            reg.remove("nonexistent")


# ---------------------------------------------------------------------------
# Persistence across restarts
# ---------------------------------------------------------------------------


class TestPersistenceAcrossRestarts:
    def test_devices_survive_restart(self, tmp_path):
        db_path = str(tmp_path / "fleet.db")
        reg1 = FleetRegistry(db_path=db_path)
        reg1.register(_make_device_info(device_id="d1", hostname="host1"))
        reg1.register(_make_device_info(device_id="d2", hostname="host2"))

        # Simulate restart with a fresh registry instance
        reg2 = FleetRegistry(db_path=db_path)
        assert reg2.device_count() == 2
        assert reg2.get_device("d1").hostname == "host1"
        assert reg2.get_device("d2").hostname == "host2"

    def test_pending_commands_survive_restart(self, tmp_path):
        db_path = str(tmp_path / "fleet.db")
        reg1 = FleetRegistry(db_path=db_path)
        reg1.register(_make_device_info())
        reg1.enqueue_command("dev-001", "pull-model", {"model": "qwen2.5:7b"})

        reg2 = FleetRegistry(db_path=db_path)
        cmd = reg2.heartbeat(_make_heartbeat())
        assert cmd.action == "pull-model"


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_registers(self, tmp_path):
        reg = _make_registry(tmp_path)
        errors = []

        def _register(i: int):
            try:
                reg.register(_make_device_info(device_id=f"dev-{i}"))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_register, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert reg.device_count() == 20


# ---------------------------------------------------------------------------
# DB path resolution
# ---------------------------------------------------------------------------


class TestDbPathResolution:
    def test_env_var_takes_precedence(self, tmp_path):
        db_path = str(tmp_path / "custom.db")
        with patch.dict("os.environ", {"BMT_FLEET_DB": db_path}):
            reg = FleetRegistry()
        assert reg._db_path == db_path

    def test_explicit_arg_takes_precedence_over_env(self, tmp_path):
        db_path = str(tmp_path / "explicit.db")
        env_path = str(tmp_path / "env.db")
        with patch.dict("os.environ", {"BMT_FLEET_DB": env_path}):
            reg = FleetRegistry(db_path=db_path)
        assert reg._db_path == db_path

    def test_fallback_to_temp_file_when_not_writable(self, tmp_path):
        import os as _os

        # When default path is not writable, should fall back to a temp file
        with patch("bmt_ai_os.fleet.registry._DEFAULT_DB_PATH", "/nonexistent/path/fleet.db"):
            with patch.dict("os.environ", {}, clear=False):
                _os.environ.pop("BMT_FLEET_DB", None)
                reg = FleetRegistry()
        # Should have created a temp file
        assert reg._db_path != "/nonexistent/path/fleet.db"
        assert _os.path.exists(reg._db_path)
