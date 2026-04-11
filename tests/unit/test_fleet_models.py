"""Unit tests for bmt_ai_os.fleet.models.

Covers DeviceInfo, DeviceHeartbeat, and FleetCommand fully.
"""

from __future__ import annotations

from bmt_ai_os.fleet.models import DeviceHeartbeat, DeviceInfo, FleetCommand

# ---------------------------------------------------------------------------
# DeviceInfo
# ---------------------------------------------------------------------------


class TestDeviceInfo:
    def test_creation(self):
        info = DeviceInfo(
            device_id="dev-abc",
            hostname="bmt-device",
            os_version="2026.4.10",
            arch="aarch64",
            board="rk3588",
            cpu_model="Cortex-A76",
            cpu_cores=8,
            memory_total_mb=8192,
            disk_total_gb=64.0,
        )
        assert info.device_id == "dev-abc"
        assert info.hostname == "bmt-device"
        assert info.arch == "aarch64"
        assert info.cpu_cores == 8
        assert info.memory_total_mb == 8192
        assert info.disk_total_gb == 64.0

    def test_board_field(self):
        info = DeviceInfo(
            device_id="x",
            hostname="h",
            os_version="1.0",
            arch="arm64",
            board="pi5",
            cpu_model="BCM2712",
            cpu_cores=4,
            memory_total_mb=4096,
            disk_total_gb=32.0,
        )
        assert info.board == "pi5"

    def test_os_version(self):
        info = DeviceInfo(
            device_id="x",
            hostname="h",
            os_version="2026.5.0",
            arch="aarch64",
            board="jetson",
            cpu_model="Orin",
            cpu_cores=12,
            memory_total_mb=16384,
            disk_total_gb=256.0,
        )
        assert info.os_version == "2026.5.0"


# ---------------------------------------------------------------------------
# DeviceHeartbeat
# ---------------------------------------------------------------------------


class TestDeviceHeartbeat:
    def test_now_creates_iso_timestamp(self):
        hb = DeviceHeartbeat.now(
            device_id="dev-1",
            os_version="2026.4.10",
            hardware={"board": "rk3588"},
            loaded_models=["qwen2.5:7b"],
            service_health={"ollama": "up"},
            cpu_percent=10.0,
            memory_percent=25.0,
            disk_percent=15.0,
        )
        # ISO 8601 format includes a "T" separator and timezone info
        assert "T" in hb.timestamp
        assert "Z" in hb.timestamp or "+" in hb.timestamp

    def test_now_sets_device_id(self):
        hb = DeviceHeartbeat.now(
            device_id="my-device",
            os_version="1.0",
            hardware={},
            loaded_models=[],
            service_health={},
            cpu_percent=0,
            memory_percent=0,
            disk_percent=0,
        )
        assert hb.device_id == "my-device"

    def test_to_dict_all_keys_present(self):
        hb = DeviceHeartbeat.now(
            device_id="d",
            os_version="v1",
            hardware={"cpu": "arm"},
            loaded_models=["model-a"],
            service_health={"ollama": "up", "chromadb": "down"},
            cpu_percent=50.0,
            memory_percent=70.0,
            disk_percent=30.0,
        )
        d = hb.to_dict()
        expected_keys = {
            "device_id",
            "timestamp",
            "os_version",
            "hardware",
            "loaded_models",
            "service_health",
            "cpu_percent",
            "memory_percent",
            "disk_percent",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_values_correct(self):
        hb = DeviceHeartbeat.now(
            device_id="test-id",
            os_version="2026.4",
            hardware={"board": "pi5", "arch": "aarch64"},
            loaded_models=["qwen2.5:7b", "llama3:8b"],
            service_health={"ollama": "up", "chromadb": "up"},
            cpu_percent=22.5,
            memory_percent=48.3,
            disk_percent=12.0,
        )
        d = hb.to_dict()
        assert d["device_id"] == "test-id"
        assert d["os_version"] == "2026.4"
        assert d["hardware"]["board"] == "pi5"
        assert len(d["loaded_models"]) == 2
        assert d["cpu_percent"] == 22.5
        assert d["memory_percent"] == 48.3
        assert d["disk_percent"] == 12.0

    def test_to_dict_empty_loaded_models(self):
        hb = DeviceHeartbeat.now(
            device_id="d",
            os_version="v1",
            hardware={},
            loaded_models=[],
            service_health={},
            cpu_percent=0,
            memory_percent=0,
            disk_percent=0,
        )
        assert hb.to_dict()["loaded_models"] == []

    def test_hardware_dict_preserved(self):
        hw = {"board": "orin", "cpu_cores": 12, "memory_total_mb": 16384}
        hb = DeviceHeartbeat.now(
            device_id="d",
            os_version="v1",
            hardware=hw,
            loaded_models=[],
            service_health={},
            cpu_percent=0,
            memory_percent=0,
            disk_percent=0,
        )
        assert hb.to_dict()["hardware"] == hw


# ---------------------------------------------------------------------------
# FleetCommand
# ---------------------------------------------------------------------------


class TestFleetCommand:
    def test_from_dict_null_action(self):
        cmd = FleetCommand.from_dict({"action": None})
        assert cmd.action is None
        assert cmd.is_noop() is True

    def test_from_dict_with_action(self):
        cmd = FleetCommand.from_dict({"action": "pull-model", "params": {"model": "qwen2.5:7b"}})
        assert cmd.action == "pull-model"
        assert cmd.params["model"] == "qwen2.5:7b"
        assert cmd.is_noop() is False

    def test_from_dict_empty_dict(self):
        cmd = FleetCommand.from_dict({})
        assert cmd.action is None
        assert cmd.is_noop() is True

    def test_from_dict_missing_params_defaults_to_empty(self):
        cmd = FleetCommand.from_dict({"action": "update"})
        assert cmd.params == {}

    def test_from_dict_command_id(self):
        cmd = FleetCommand.from_dict({"action": "update", "command_id": "cmd-123"})
        assert cmd.command_id == "cmd-123"

    def test_from_dict_status(self):
        cmd = FleetCommand.from_dict({"action": "update", "status": "in-progress"})
        assert cmd.status == "in-progress"

    def test_from_dict_default_status_pending(self):
        cmd = FleetCommand.from_dict({"action": "restart-service"})
        assert cmd.status == "pending"

    def test_update_action(self):
        cmd = FleetCommand.from_dict({"action": "update", "params": {"version": "2026.5.0"}})
        assert cmd.action == "update"
        assert cmd.params["version"] == "2026.5.0"

    def test_restart_service_action(self):
        cmd = FleetCommand.from_dict(
            {"action": "restart-service", "params": {"service": "chromadb"}}
        )
        assert cmd.action == "restart-service"
        assert cmd.params["service"] == "chromadb"

    def test_pull_model_action(self):
        cmd = FleetCommand.from_dict(
            {"action": "pull-model", "params": {"model": "qwen2.5-coder:7b"}}
        )
        assert cmd.action == "pull-model"
        assert not cmd.is_noop()

    def test_is_noop_false_for_all_valid_actions(self):
        for action in ["update", "pull-model", "restart-service"]:
            cmd = FleetCommand(action=action)
            assert cmd.is_noop() is False

    def test_direct_construction(self):
        cmd = FleetCommand(action="pull-model", params={"model": "llama3:8b"}, command_id="xyz")
        assert cmd.action == "pull-model"
        assert cmd.command_id == "xyz"

    def test_null_params_defaults_to_empty(self):
        cmd = FleetCommand.from_dict({"action": "update", "params": None})
        assert cmd.params == {}
