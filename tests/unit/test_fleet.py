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
        fallback = tmp_path / "bmt-device-id"
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
        with patch("bmt_ai_os.fleet.collector.requests.get", return_value=mock_resp) as mock_get:
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
        assert "http://fleet.local" in result.output
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
        assert "http://fleet.local" in result.output
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
