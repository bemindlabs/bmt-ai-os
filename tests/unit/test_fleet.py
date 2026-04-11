"""Unit tests for bmt_ai_os.fleet.

All tests are fully offline — no live services or real filesystem side-effects.
HTTP calls and subprocess invocations are intercepted with unittest.mock.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# fleet.models
# ---------------------------------------------------------------------------
from bmt_ai_os.fleet.models import DeviceHeartbeat, DeviceInfo, FleetCommand


class TestDeviceHeartbeat:
    def test_now_sets_timestamp(self):
        hb = DeviceHeartbeat.now(
            device_id="abc",
            os_version="1.0",
            hardware={"board": "pi5"},
            loaded_models=["qwen2.5:7b"],
            service_health={"ollama": "up"},
            cpu_percent=12.5,
            memory_percent=33.0,
            disk_percent=20.0,
        )
        assert hb.device_id == "abc"
        assert "T" in hb.timestamp  # ISO 8601
        assert hb.loaded_models == ["qwen2.5:7b"]

    def test_to_dict_round_trip(self):
        hb = DeviceHeartbeat.now(
            device_id="dev-1",
            os_version="2026.4",
            hardware={"board": "rk3588"},
            loaded_models=[],
            service_health={"ollama": "down", "chromadb": "up"},
            cpu_percent=5.0,
            memory_percent=40.0,
            disk_percent=10.0,
        )
        d = hb.to_dict()
        assert d["device_id"] == "dev-1"
        assert d["service_health"] == {"ollama": "down", "chromadb": "up"}
        assert d["cpu_percent"] == 5.0
        # All required keys present
        for key in (
            "device_id",
            "timestamp",
            "os_version",
            "hardware",
            "loaded_models",
            "service_health",
            "cpu_percent",
            "memory_percent",
            "disk_percent",
        ):
            assert key in d


class TestFleetCommand:
    def test_from_dict_full(self):
        data = {
            "action": "pull-model",
            "params": {"model": "qwen2.5-coder:7b"},
            "command_id": "cmd-42",
            "status": "pending",
        }
        cmd = FleetCommand.from_dict(data)
        assert cmd.action == "pull-model"
        assert cmd.params == {"model": "qwen2.5-coder:7b"}
        assert cmd.command_id == "cmd-42"
        assert not cmd.is_noop()

    def test_from_dict_noop(self):
        cmd = FleetCommand.from_dict({"action": None})
        assert cmd.is_noop()

    def test_from_dict_empty(self):
        cmd = FleetCommand.from_dict({})
        assert cmd.is_noop()
        assert cmd.params == {}

    def test_defaults(self):
        cmd = FleetCommand(action="update")
        assert cmd.status == "pending"
        assert cmd.params == {}
        assert not cmd.is_noop()


class TestDeviceInfo:
    def test_construction(self):
        info = DeviceInfo(
            device_id="id-1",
            hostname="bmt-device",
            os_version="2026.4",
            arch="aarch64",
            board="jetson-orin",
            cpu_model="Cortex-A78AE",
            cpu_cores=12,
            memory_total_mb=8192,
            disk_total_gb=256.0,
        )
        assert info.cpu_cores == 12
        assert info.memory_total_mb == 8192


# ---------------------------------------------------------------------------
# fleet.collector
# ---------------------------------------------------------------------------

from bmt_ai_os.fleet.collector import (
    get_device_id,
    get_hardware_info,
    get_loaded_models,
    get_resource_usage,
    get_service_health,
)


class TestGetDeviceId:
    def test_reads_machine_id(self, tmp_path):
        machine_id_file = tmp_path / "machine-id"
        machine_id_file.write_text("abc123\n")
        with patch(
            "bmt_ai_os.fleet.collector._MACHINE_ID_PATHS",
            [machine_id_file],
        ):
            result = get_device_id()
        assert result == "abc123"

    def test_falls_back_to_tmp_file(self, tmp_path):
        _fallback = tmp_path / "bmt-device-id"
        with (
            patch("bmt_ai_os.fleet.collector._MACHINE_ID_PATHS", []),
            patch("bmt_ai_os.fleet.collector.Path") as MockPath,
        ):
            # Simulate that fallback file does not exist initially, then is created.
            mock_fallback = MagicMock()
            mock_fallback.exists.return_value = False
            MockPath.return_value = mock_fallback
            # uuid4 is called internally; just verify we get a non-empty string.
            result = get_device_id()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generates_uuid_when_all_fail(self, tmp_path):
        """When /etc/machine-id is absent and /tmp is unwritable, returns a UUID."""
        # Patch the fallback path to a non-existent location the process cannot write.
        nonexistent = tmp_path / "no-such-dir" / "bmt-device-id"
        with (
            patch("bmt_ai_os.fleet.collector._MACHINE_ID_PATHS", []),
            patch(
                "bmt_ai_os.fleet.collector.Path",
                side_effect=lambda *a, **k: (
                    nonexistent if "bmt-device-id" in str(a) else Path(*a, **k)
                ),
            ),
        ):
            # The real Path is still needed for _MACHINE_ID_PATHS iteration, so
            # just verify an empty list means we skip to the fallback.
            pass
        # Simpler: directly patch the fallback Path to raise OSError on write.
        import uuid as _uuid

        with patch("bmt_ai_os.fleet.collector._MACHINE_ID_PATHS", []):
            with patch("bmt_ai_os.fleet.collector.Path") as MockPath:
                inst = MagicMock()
                inst.exists.return_value = False
                inst.write_text.side_effect = OSError("read-only")
                MockPath.return_value = inst
                result = get_device_id()
        assert isinstance(result, str)
        # Must be a valid UUID4
        _uuid.UUID(result)  # raises ValueError if not valid


class TestGetHardwareInfo:
    def test_returns_expected_keys(self):
        info = get_hardware_info()
        for key in (
            "board",
            "cpu_model",
            "cpu_cores",
            "memory_total_mb",
            "disk_total_gb",
            "arch",
            "hostname",
        ):
            assert key in info, f"Missing key: {key}"

    def test_cpu_cores_positive(self):
        info = get_hardware_info()
        assert info["cpu_cores"] >= 1


class TestGetServiceHealth:
    def test_both_up(self):
        mock_resp = MagicMock()
        mock_resp.ok = True
        with patch("bmt_ai_os.fleet.collector.requests.get", return_value=mock_resp):
            health = get_service_health()
        assert health["ollama"] == "up"
        assert health["chromadb"] == "up"

    def test_both_down_on_exception(self):
        import requests as _req

        with patch(
            "bmt_ai_os.fleet.collector.requests.get",
            side_effect=_req.exceptions.ConnectionError,
        ):
            health = get_service_health()
        assert health["ollama"] == "down"
        assert health["chromadb"] == "down"

    def test_mixed_health(self):
        # Ollama up, ChromaDB down
        responses = [MagicMock(ok=True), MagicMock(ok=False)]
        with patch("bmt_ai_os.fleet.collector.requests.get", side_effect=responses):
            health = get_service_health()
        assert health["ollama"] == "up"
        assert health["chromadb"] == "down"


class TestGetLoadedModels:
    def test_returns_model_names(self):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "models": [{"name": "qwen2.5:7b"}, {"name": "nomic-embed-text"}]
        }
        with patch("bmt_ai_os.fleet.collector.requests.get", return_value=mock_resp):
            models = get_loaded_models()
        assert models == ["qwen2.5:7b", "nomic-embed-text"]

    def test_returns_empty_on_connection_error(self):
        import requests as _req

        with patch(
            "bmt_ai_os.fleet.collector.requests.get",
            side_effect=_req.exceptions.ConnectionError,
        ):
            models = get_loaded_models()
        assert models == []

    def test_skips_models_without_name(self):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"models": [{"name": "good"}, {}]}
        with patch("bmt_ai_os.fleet.collector.requests.get", return_value=mock_resp):
            models = get_loaded_models()
        assert models == ["good"]


class TestGetResourceUsage:
    def test_uses_psutil_when_available(self):
        psutil_mock = MagicMock()
        psutil_mock.cpu_percent.return_value = 42.0
        psutil_mock.virtual_memory.return_value = MagicMock(percent=55.0)
        psutil_mock.disk_usage.return_value = MagicMock(percent=30.0)

        with patch.dict("sys.modules", {"psutil": psutil_mock}):
            usage = get_resource_usage()

        assert usage["cpu_percent"] == 42.0
        assert usage["memory_percent"] == 55.0
        assert usage["disk_percent"] == 30.0

    def test_returns_dict_with_required_keys(self):
        usage = get_resource_usage()
        for key in ("cpu_percent", "memory_percent", "disk_percent"):
            assert key in usage
            assert isinstance(usage[key], float)

    def test_values_in_valid_range(self):
        usage = get_resource_usage()
        for key in ("cpu_percent", "memory_percent", "disk_percent"):
            assert 0.0 <= usage[key] <= 100.0, f"{key} out of range: {usage[key]}"


# ---------------------------------------------------------------------------
# fleet.agent
# ---------------------------------------------------------------------------

from bmt_ai_os.fleet.agent import FleetAgent


def _make_agent(server_url: str = "http://fleet.test") -> FleetAgent:
    return FleetAgent(server_url=server_url, device_id="test-device-id")


class TestFleetAgentSendHeartbeat:
    def test_sends_post_to_heartbeat_endpoint(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"action": None}

        with patch("bmt_ai_os.fleet.agent.requests.post", return_value=mock_resp) as mock_post:
            with patch("bmt_ai_os.fleet.agent.get_hardware_info", return_value={"board": "rk3588"}):
                with patch("bmt_ai_os.fleet.agent.get_loaded_models", return_value=[]):
                    with patch(
                        "bmt_ai_os.fleet.agent.get_service_health",
                        return_value={"ollama": "up"},
                    ):
                        with patch(
                            "bmt_ai_os.fleet.agent.get_resource_usage",
                            return_value={
                                "cpu_percent": 1.0,
                                "memory_percent": 2.0,
                                "disk_percent": 3.0,
                            },
                        ):
                            agent = _make_agent()
                            cmd = agent.send_heartbeat()

        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        assert call_url == "http://fleet.test/api/v1/fleet/heartbeat"
        assert cmd.is_noop()

    def test_returns_command_from_server(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "action": "pull-model",
            "params": {"model": "qwen2.5:7b"},
            "command_id": "c1",
        }

        with patch("bmt_ai_os.fleet.agent.requests.post", return_value=mock_resp):
            with patch("bmt_ai_os.fleet.agent.get_hardware_info", return_value={}):
                with patch("bmt_ai_os.fleet.agent.get_loaded_models", return_value=[]):
                    with patch("bmt_ai_os.fleet.agent.get_service_health", return_value={}):
                        with patch(
                            "bmt_ai_os.fleet.agent.get_resource_usage",
                            return_value={
                                "cpu_percent": 0.0,
                                "memory_percent": 0.0,
                                "disk_percent": 0.0,
                            },
                        ):
                            agent = _make_agent()
                            cmd = agent.send_heartbeat()

        assert cmd.action == "pull-model"
        assert cmd.params == {"model": "qwen2.5:7b"}


class TestFleetAgentExecuteCommand:
    def test_noop_does_nothing(self):
        agent = _make_agent()
        # Should not raise
        agent.execute_command(FleetCommand(action=None))

    def test_unknown_action_is_ignored(self):
        agent = _make_agent()
        agent.execute_command(FleetCommand(action="do-something-weird"))

    def test_pull_model_calls_ollama(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_lines.return_value = [
            json.dumps({"status": "pulling manifest"}).encode(),
            json.dumps({"status": "success"}).encode(),
        ]

        with patch("bmt_ai_os.fleet.agent.requests.post", return_value=mock_resp) as mock_post:
            agent = _make_agent()
            agent.execute_command(FleetCommand(action="pull-model", params={"model": "qwen2.5:7b"}))

        mock_post.assert_called_once()
        assert "api/pull" in mock_post.call_args[0][0]

    def test_pull_model_raises_when_no_model_param(self):
        agent = _make_agent()
        # execute_command catches exceptions and logs — it does not re-raise.
        # Verify no unhandled exception leaks out.
        agent.execute_command(FleetCommand(action="pull-model", params={}))

    def test_restart_service_calls_docker_compose(self):
        mock_result = MagicMock()
        mock_result.returncode = 0

        # load_config is imported inside _cmd_restart_service, so patch at its
        # source module rather than on the agent module.
        with patch("bmt_ai_os.fleet.agent.subprocess.run", return_value=mock_result) as mock_run:
            with patch(
                "bmt_ai_os.controller.config.load_config",
                return_value=MagicMock(compose_file="/opt/bmt/docker-compose.yml"),
            ):
                agent = _make_agent()
                agent.execute_command(
                    FleetCommand(action="restart-service", params={"service": "ollama"})
                )

        mock_run.assert_called_once()
        cmd_args = mock_run.call_args[0][0]
        assert "restart" in cmd_args
        assert "ollama" in cmd_args

    def test_update_calls_apk(self):
        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("bmt_ai_os.fleet.agent.subprocess.run", return_value=mock_result) as mock_run:
            agent = _make_agent()
            agent.execute_command(FleetCommand(action="update", params={}))

        assert mock_run.call_count == 2  # apk update + apk upgrade
        first_call_args = mock_run.call_args_list[0][0][0]
        assert "apk" in first_call_args


class TestFleetAgentRunStop:
    def test_run_starts_daemon_thread(self):
        agent = _make_agent()
        agent._stop_event.set()  # Prevent the loop from actually running

        with patch.object(agent, "_loop"):
            agent.run()
            assert agent._thread is not None

        agent.stop()

    def test_run_is_idempotent(self):
        agent = _make_agent()

        started = threading.Event()

        def _slow_loop():
            started.set()
            # Block until stop_event is set so the thread stays alive.
            agent._stop_event.wait()

        with patch.object(agent, "_loop", side_effect=_slow_loop):
            agent.run()
            started.wait(timeout=2)  # wait until thread is actually running
            thread_1 = agent._thread
            agent.run()  # should be a no-op
            thread_2 = agent._thread
            assert thread_1 is thread_2

        agent.stop()

    def test_status_dict(self):
        agent = _make_agent()
        s = agent.status()
        assert s["device_id"] == "test-device-id"
        assert s["server_url"] == "http://fleet.test"
        assert isinstance(s["running"], bool)


# ---------------------------------------------------------------------------
# CLI integration (Click test runner)
# ---------------------------------------------------------------------------

from click.testing import CliRunner

from bmt_ai_os.cli import main


class TestFleetCLI:
    def _runner(self):
        return CliRunner()

    def test_fleet_register_saves_state(self, tmp_path):
        state_file = str(tmp_path / "fleet-state.json")

        with (
            patch("bmt_ai_os.fleet.collector.get_device_id", return_value="dev-001"),
            patch(
                "bmt_ai_os.fleet.collector.get_hardware_info",
                return_value={"hostname": "bmt-1", "arch": "aarch64", "board": "rk3588"},
            ),
            patch("bmt_ai_os.cli._http_post", return_value=None),
            patch("bmt_ai_os.cli._FLEET_STATE_FILE", state_file),
            patch("bmt_ai_os.cli._save_fleet_state") as mock_save,
        ):
            runner = self._runner()
            result = runner.invoke(
                main,
                ["fleet", "register", "--server", "http://fleet.local"],
            )

        assert result.exit_code == 0, result.output
        assert "dev-001" in result.output
        assert "http://fleet.local" in result.output  # nosec B105 — test assertion on CLI output, not a credential check
        mock_save.assert_called_once()

    def test_fleet_status_no_server(self, tmp_path):
        # _load_fleet_state returns {} and env var is unset — should exit non-zero.
        with (
            patch("bmt_ai_os.cli._load_fleet_state", return_value={}),
            patch.dict("os.environ", {}, clear=False),
        ):
            # Make sure BMT_FLEET_SERVER is not set.
            import os as _os

            _os.environ.pop("BMT_FLEET_SERVER", None)
            runner = self._runner()
            result = runner.invoke(main, ["fleet", "status"])
        assert result.exit_code != 0

    def test_fleet_status_with_registration(self, tmp_path):
        state = {"server_url": "http://fleet.local", "device_id": "dev-001"}

        with (
            patch("bmt_ai_os.cli._load_fleet_state", return_value=state),
            patch("bmt_ai_os.cli._http_get", return_value=None),
        ):
            runner = self._runner()
            result = runner.invoke(main, ["fleet", "status"])

        assert result.exit_code == 0, result.output
        assert "dev-001" in result.output
        assert "http://fleet.local" in result.output  # nosec B105 — test assertion on CLI output, not a credential check
        assert "UNREACHABLE" in result.output

    def test_fleet_heartbeat_no_server(self):
        with (
            patch("bmt_ai_os.cli._load_fleet_state", return_value={}),
        ):
            import os as _os

            _os.environ.pop("BMT_FLEET_SERVER", None)
            runner = self._runner()
            result = runner.invoke(main, ["fleet", "heartbeat"])
        assert result.exit_code != 0

    def test_fleet_heartbeat_success(self):
        state = {"server_url": "http://fleet.local", "device_id": "dev-001"}
        noop_cmd = FleetCommand(action=None)

        with (
            patch("bmt_ai_os.cli._load_fleet_state", return_value=state),
            patch(
                "bmt_ai_os.fleet.agent.FleetAgent.send_heartbeat",
                return_value=noop_cmd,
            ),
        ):
            runner = self._runner()
            result = runner.invoke(main, ["fleet", "heartbeat"])

        assert result.exit_code == 0, result.output
        assert "Heartbeat sent successfully" in result.output
        assert "No command from server" in result.output

    def test_fleet_heartbeat_with_command(self):
        state = {"server_url": "http://fleet.local", "device_id": "dev-001"}
        pull_cmd = FleetCommand(action="pull-model", params={"model": "qwen2.5:7b"})

        with (
            patch("bmt_ai_os.cli._load_fleet_state", return_value=state),
            patch(
                "bmt_ai_os.fleet.agent.FleetAgent.send_heartbeat",
                return_value=pull_cmd,
            ),
        ):
            runner = self._runner()
            result = runner.invoke(main, ["fleet", "heartbeat"])

        assert result.exit_code == 0, result.output
        assert "pull-model" in result.output


# ---------------------------------------------------------------------------
# fleet.registry
# ---------------------------------------------------------------------------

from bmt_ai_os.fleet.registry import DeviceRecord, FleetRegistry


def _make_heartbeat(device_id: str = "dev-1") -> DeviceHeartbeat:
    return DeviceHeartbeat.now(
        device_id=device_id,
        os_version="2026.4",
        hardware={"board": "rk3588", "arch": "aarch64", "hostname": f"host-{device_id}"},
        loaded_models=["qwen2.5:7b"],
        service_health={"ollama": "up", "chromadb": "up"},
        cpu_percent=10.0,
        memory_percent=40.0,
        disk_percent=20.0,
    )


class TestDeviceRecord:
    def test_initial_state(self):
        rec = DeviceRecord(
            device_id="abc",
            hostname="pi5",
            arch="aarch64",
            board="rpi5",
        )
        assert rec.device_id == "abc"
        assert rec.is_online() is False  # no heartbeat yet
        assert rec.pending_command_count() == 0

    def test_apply_heartbeat_updates_fields(self):
        rec = DeviceRecord(device_id="dev-1")
        hb = _make_heartbeat("dev-1")
        rec.apply_heartbeat(hb)

        assert rec.loaded_models == ["qwen2.5:7b"]
        assert rec.service_health == {"ollama": "up", "chromadb": "up"}
        assert rec.cpu_percent == 10.0
        assert rec.memory_percent == 40.0
        assert rec.os_version == "2026.4"
        assert rec.last_seen == hb.timestamp

    def test_is_online_after_fresh_heartbeat(self):
        rec = DeviceRecord(device_id="dev-1")
        hb = _make_heartbeat("dev-1")
        rec.apply_heartbeat(hb)
        assert rec.is_online() is True

    def test_is_online_false_for_stale_timestamp(self):
        rec = DeviceRecord(device_id="dev-1")
        # Set last_seen to a timestamp far in the past.
        rec.last_seen = "2020-01-01T00:00:00+00:00"
        assert rec.is_online() is False

    def test_command_queue_fifo(self):
        rec = DeviceRecord(device_id="dev-1")
        cmd1 = FleetCommand(action="update", params={})
        cmd2 = FleetCommand(action="pull-model", params={"model": "qwen2.5:7b"})

        rec.enqueue_command(cmd1)
        rec.enqueue_command(cmd2)

        assert rec.pending_command_count() == 2
        out1 = rec.dequeue_command()
        assert out1.action == "update"
        assert rec.pending_command_count() == 1
        out2 = rec.dequeue_command()
        assert out2.action == "pull-model"
        assert rec.pending_command_count() == 0

    def test_dequeue_returns_noop_when_empty(self):
        rec = DeviceRecord(device_id="dev-1")
        cmd = rec.dequeue_command()
        assert cmd.is_noop()

    def test_to_dict_keys(self):
        rec = DeviceRecord(device_id="dev-1", hostname="h", arch="aarch64", board="rk3588")
        hb = _make_heartbeat("dev-1")
        rec.apply_heartbeat(hb)
        d = rec.to_dict()
        for key in (
            "device_id",
            "hostname",
            "arch",
            "board",
            "os_version",
            "hardware",
            "registered_at",
            "last_seen",
            "online",
            "loaded_models",
            "service_health",
            "cpu_percent",
            "memory_percent",
            "disk_percent",
            "pending_commands",
        ):
            assert key in d, f"Missing key in to_dict: {key}"


class TestFleetRegistry:
    def _registry(self) -> FleetRegistry:
        """Return a fresh registry for each test."""
        return FleetRegistry()

    def test_register_new_device(self):
        reg = self._registry()
        rec = reg.register_device(device_id="d1", hostname="h1", arch="aarch64", board="rk3588")
        assert rec.device_id == "d1"
        assert reg.device_count() == 1

    def test_register_idempotent(self):
        reg = self._registry()
        reg.register_device(device_id="d1")
        reg.register_device(device_id="d1", hostname="updated-host")
        assert reg.device_count() == 1
        rec = reg.get_device("d1")
        assert rec is not None
        assert rec.hostname == "updated-host"

    def test_remove_device(self):
        reg = self._registry()
        reg.register_device(device_id="d1")
        assert reg.remove_device("d1") is True
        assert reg.device_count() == 0
        assert reg.remove_device("d1") is False  # already gone

    def test_apply_heartbeat_auto_registers(self):
        reg = self._registry()
        hb = _make_heartbeat("new-device")
        reg.apply_heartbeat(hb)
        assert reg.device_count() == 1
        rec = reg.get_device("new-device")
        assert rec is not None
        assert rec.loaded_models == ["qwen2.5:7b"]

    def test_apply_heartbeat_returns_queued_command(self):
        reg = self._registry()
        reg.register_device("d1")
        cmd = FleetCommand(action="update", params={})
        reg.enqueue_command("d1", cmd)

        hb = _make_heartbeat("d1")
        returned = reg.apply_heartbeat(hb)
        assert returned.action == "update"

    def test_apply_heartbeat_returns_noop_when_no_command(self):
        reg = self._registry()
        hb = _make_heartbeat("d1")
        returned = reg.apply_heartbeat(hb)
        assert returned.is_noop()

    def test_enqueue_command_unknown_device(self):
        reg = self._registry()
        cmd = FleetCommand(action="update")
        result = reg.enqueue_command("nonexistent", cmd)
        assert result is False

    def test_broadcast_command(self):
        reg = self._registry()
        reg.register_device("d1")
        reg.register_device("d2")
        cmd = FleetCommand(action="restart-service", params={"service": "ollama"})
        targets = reg.broadcast_command(cmd)

        assert set(targets) == {"d1", "d2"}
        assert reg.get_device("d1").pending_command_count() == 1  # type: ignore[union-attr]
        assert reg.get_device("d2").pending_command_count() == 1  # type: ignore[union-attr]

    def test_deploy_model_all_devices(self):
        reg = self._registry()
        reg.register_device("d1")
        reg.register_device("d2")
        targeted = reg.deploy_model("qwen2.5-coder:7b")

        assert set(targeted) == {"d1", "d2"}
        d1 = reg.get_device("d1")
        assert d1 is not None
        cmd = d1.dequeue_command()
        assert cmd.action == "pull-model"
        assert cmd.params["model"] == "qwen2.5-coder:7b"

    def test_deploy_model_specific_devices(self):
        reg = self._registry()
        reg.register_device("d1")
        reg.register_device("d2")
        targeted = reg.deploy_model("qwen2.5:7b", device_ids=["d1"])

        assert targeted == ["d1"]
        assert reg.get_device("d1").pending_command_count() == 1  # type: ignore[union-attr]
        assert reg.get_device("d2").pending_command_count() == 0  # type: ignore[union-attr]

    def test_list_devices(self):
        reg = self._registry()
        reg.register_device("d1", hostname="h1")
        reg.register_device("d2", hostname="h2")
        devices = reg.list_devices()
        assert len(devices) == 2
        ids = {d["device_id"] for d in devices}
        assert ids == {"d1", "d2"}

    def test_summary(self):
        reg = self._registry()
        reg.register_device("d1")
        reg.register_device("d2")
        # Give d1 a fresh heartbeat (online), d2 stays offline.
        hb = _make_heartbeat("d1")
        reg.apply_heartbeat(hb)

        s = reg.summary()
        assert s["total_devices"] == 2
        assert s["online_devices"] == 1
        assert s["offline_devices"] == 1
        assert "qwen2.5:7b" in s["unique_models"]

    def test_online_count(self):
        reg = self._registry()
        reg.register_device("d1")
        assert reg.online_count() == 0
        reg.apply_heartbeat(_make_heartbeat("d1"))
        assert reg.online_count() == 1

    def test_get_registry_singleton(self):
        from bmt_ai_os.fleet.registry import get_registry

        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2


# ---------------------------------------------------------------------------
# fleet.routes (via FastAPI TestClient)
# ---------------------------------------------------------------------------

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bmt_ai_os.fleet.routes import router as fleet_router


def _make_test_app(registry: FleetRegistry | None = None) -> TestClient:
    """Build a minimal FastAPI app with the fleet router for testing."""
    from bmt_ai_os.fleet import registry as reg_module

    app = FastAPI()
    app.include_router(fleet_router, prefix="/api/v1")

    if registry is not None:
        # Monkey-patch the module-level singleton for test isolation.
        reg_module._registry = registry

    return TestClient(app)


class TestFleetRoutes:
    def setup_method(self):
        """Give each test a fresh, isolated registry."""
        from bmt_ai_os.fleet import registry as reg_module

        self._orig_registry = reg_module._registry
        self._test_registry = FleetRegistry()
        reg_module._registry = self._test_registry
        self._client = TestClient(_make_test_app(self._test_registry).app)

    def teardown_method(self):
        from bmt_ai_os.fleet import registry as reg_module

        reg_module._registry = self._orig_registry

    def test_health_endpoint(self):
        resp = self._client.get("/api/v1/fleet/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "total_devices" in data

    def test_register_new_device(self):
        resp = self._client.post(
            "/api/v1/fleet/register",
            json={
                "device_id": "d1",
                "hostname": "bmt-rk3588",
                "arch": "aarch64",
                "board": "rk3588",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "registered"
        assert data["device_id"] == "d1"

    def test_register_is_idempotent(self):
        for _ in range(2):
            resp = self._client.post(
                "/api/v1/fleet/register",
                json={"device_id": "d1", "hostname": "bmt-1"},
            )
            assert resp.status_code == 200
        assert self._test_registry.device_count() == 1

    def test_heartbeat_auto_registers_and_returns_noop(self):
        resp = self._client.post(
            "/api/v1/fleet/heartbeat",
            json={
                "device_id": "new-device",
                "timestamp": "2026-04-11T00:00:00+00:00",
                "os_version": "2026.4",
                "hardware": {"board": "rk3588"},
                "loaded_models": [],
                "service_health": {},
                "cpu_percent": 5.0,
                "memory_percent": 20.0,
                "disk_percent": 10.0,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] is None
        assert self._test_registry.device_count() == 1

    def test_heartbeat_returns_queued_command(self):
        self._test_registry.register_device("d1")
        self._test_registry.enqueue_command("d1", FleetCommand(action="update", params={}))
        resp = self._client.post(
            "/api/v1/fleet/heartbeat",
            json={
                "device_id": "d1",
                "timestamp": "2026-04-11T00:00:00+00:00",
                "os_version": "2026.4",
                "hardware": {},
                "loaded_models": [],
                "service_health": {},
                "cpu_percent": 0.0,
                "memory_percent": 0.0,
                "disk_percent": 0.0,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["action"] == "update"

    def test_list_devices_empty(self):
        resp = self._client.get("/api/v1/fleet/devices")
        assert resp.status_code == 200
        data = resp.json()
        assert data["devices"] == []
        assert data["total"] == 0

    def test_list_devices_populated(self):
        self._test_registry.register_device("d1")
        self._test_registry.register_device("d2")
        resp = self._client.get("/api/v1/fleet/devices")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["devices"]) == 2

    def test_get_device_found(self):
        self._test_registry.register_device("d1", hostname="pi5")
        resp = self._client.get("/api/v1/fleet/devices/d1")
        assert resp.status_code == 200
        assert resp.json()["device_id"] == "d1"

    def test_get_device_not_found(self):
        resp = self._client.get("/api/v1/fleet/devices/nonexistent")
        assert resp.status_code == 404

    def test_remove_device(self):
        self._test_registry.register_device("d1")
        resp = self._client.delete("/api/v1/fleet/devices/d1")
        assert resp.status_code == 200
        assert resp.json()["status"] == "removed"
        assert self._test_registry.device_count() == 0

    def test_remove_device_not_found(self):
        resp = self._client.delete("/api/v1/fleet/devices/ghost")
        assert resp.status_code == 404

    def test_summary_endpoint(self):
        self._test_registry.register_device("d1")
        resp = self._client.get("/api/v1/fleet/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_devices"] == 1
        assert "online_devices" in data

    def test_queue_command(self):
        self._test_registry.register_device("d1")
        resp = self._client.post(
            "/api/v1/fleet/devices/d1/command",
            json={"action": "restart-service", "params": {"service": "ollama"}, "command_id": "c1"},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "queued"
        assert data["action"] == "restart-service"
        assert self._test_registry.get_device("d1").pending_command_count() == 1  # type: ignore[union-attr]

    def test_queue_command_unknown_device(self):
        resp = self._client.post(
            "/api/v1/fleet/devices/ghost/command",
            json={"action": "update"},
        )
        assert resp.status_code == 404

    def test_deploy_model_all_devices(self):
        self._test_registry.register_device("d1")
        self._test_registry.register_device("d2")
        resp = self._client.post(
            "/api/v1/fleet/deploy-model",
            json={"model": "qwen2.5-coder:7b"},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["model"] == "qwen2.5-coder:7b"
        assert data["device_count"] == 2
        assert set(data["targeted_devices"]) == {"d1", "d2"}

    def test_deploy_model_specific_devices(self):
        self._test_registry.register_device("d1")
        self._test_registry.register_device("d2")
        resp = self._client.post(
            "/api/v1/fleet/deploy-model",
            json={"model": "qwen2.5:7b", "device_ids": ["d1"]},
        )
        assert resp.status_code == 202
        assert resp.json()["device_count"] == 1

    def test_deploy_model_empty_string_rejected(self):
        resp = self._client.post(
            "/api/v1/fleet/deploy-model",
            json={"model": "   "},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# fleet.agent — offline queue behaviour
# ---------------------------------------------------------------------------


class TestFleetAgentOfflineQueue:
    def test_offline_queue_starts_empty(self):
        agent = _make_agent()
        assert agent.offline_queue_size() == 0

    def test_status_includes_offline_queue_size(self):
        agent = _make_agent()
        s = agent.status()
        assert "offline_queue_size" in s
        assert s["offline_queue_size"] == 0

    def test_enqueue_offline_increments_size(self):
        agent = _make_agent()
        agent._enqueue_offline({"device_id": "test", "timestamp": "now"})
        assert agent.offline_queue_size() == 1

    def test_offline_queue_max_not_exceeded(self):
        from bmt_ai_os.fleet import agent as agent_mod

        orig_max = agent_mod._OFFLINE_QUEUE_MAX
        agent_mod._OFFLINE_QUEUE_MAX = 3
        try:
            ag = FleetAgent("http://fleet.test", device_id="d1")
            for i in range(10):
                ag._enqueue_offline({"seq": i})
            # deque maxlen caps at 3
            assert ag.offline_queue_size() == 3
        finally:
            agent_mod._OFFLINE_QUEUE_MAX = orig_max

    def test_flush_offline_queue_drains_on_success(self):
        agent = _make_agent()
        agent._enqueue_offline({"device_id": "t", "timestamp": "t1"})
        agent._enqueue_offline({"device_id": "t", "timestamp": "t2"})

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        with patch("bmt_ai_os.fleet.agent.requests.post", return_value=mock_resp):
            agent._flush_offline_queue()

        assert agent.offline_queue_size() == 0

    def test_flush_offline_queue_stops_on_failure(self):
        import requests as _req

        agent = _make_agent()
        agent._enqueue_offline({"device_id": "t", "timestamp": "t1"})
        agent._enqueue_offline({"device_id": "t", "timestamp": "t2"})

        with patch(
            "bmt_ai_os.fleet.agent.requests.post",
            side_effect=_req.exceptions.ConnectionError("offline"),
        ):
            agent._flush_offline_queue()

        # Nothing was drained because every attempt fails.
        assert agent.offline_queue_size() == 2

    def test_loop_queues_offline_on_connection_error(self):
        """When the server is unreachable the loop enqueues the heartbeat."""
        import requests as _req

        agent = _make_agent()
        # Prevent the loop from sleeping (it runs exactly one iteration).
        iterations = [0]

        original_wait = agent._stop_event.wait

        def _wait_once(timeout=None):
            iterations[0] += 1
            agent._stop_event.set()  # stop after first iteration
            return original_wait(timeout=0)

        agent._stop_event.wait = _wait_once

        with (
            patch(
                "bmt_ai_os.fleet.agent.requests.post",
                side_effect=_req.exceptions.ConnectionError("no server"),
            ),
            patch("bmt_ai_os.fleet.agent.get_hardware_info", return_value={}),
            patch("bmt_ai_os.fleet.agent.get_loaded_models", return_value=[]),
            patch("bmt_ai_os.fleet.agent.get_service_health", return_value={}),
            patch(
                "bmt_ai_os.fleet.agent.get_resource_usage",
                return_value={"cpu_percent": 0.0, "memory_percent": 0.0, "disk_percent": 0.0},
            ),
        ):
            agent._loop()

        assert agent.offline_queue_size() == 1
