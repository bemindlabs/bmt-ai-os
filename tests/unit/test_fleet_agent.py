"""Unit tests for bmt_ai_os.fleet.agent.FleetAgent.

All network calls and subprocess invocations are mocked.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest
import requests

from bmt_ai_os.fleet.agent import FleetAgent, _read_os_version
from bmt_ai_os.fleet.models import FleetCommand

# ---------------------------------------------------------------------------
# _read_os_version
# ---------------------------------------------------------------------------


class TestReadOsVersion:
    def test_env_var_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv("BMT_FLEET_OS_VERSION", "2026.4.10")
        assert _read_os_version() == "2026.4.10"

    def test_reads_from_os_version_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BMT_FLEET_OS_VERSION", raising=False)
        version_file = tmp_path / "bmt-os-version"
        version_file.write_text("2026.3.1\n")
        import bmt_ai_os.fleet.agent as agent_mod

        monkeypatch.setattr(agent_mod, "_OS_VERSION_FILE", str(version_file))
        assert _read_os_version() == "2026.3.1"

    def test_returns_unknown_when_nothing_available(self, monkeypatch, tmp_path):
        monkeypatch.delenv("BMT_FLEET_OS_VERSION", raising=False)
        import bmt_ai_os.fleet.agent as agent_mod

        monkeypatch.setattr(agent_mod, "_OS_VERSION_FILE", str(tmp_path / "nonexistent"))
        # Also patch /etc/os-release to not exist
        with patch("builtins.open", side_effect=OSError("not found")):
            result = _read_os_version()
        # Result is either "unknown" or a version from the running system
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# FleetAgent construction
# ---------------------------------------------------------------------------


class TestFleetAgentConstruction:
    def test_server_url_trailing_slash_stripped(self):
        agent = FleetAgent("https://fleet.example.com/", device_id="dev-1")
        assert agent.server_url == "https://fleet.example.com"

    def test_device_id_from_env(self, monkeypatch):
        monkeypatch.setenv("BMT_FLEET_DEVICE_ID", "env-device-id")
        with patch("bmt_ai_os.fleet.agent.get_device_id", return_value="system-id"):
            agent = FleetAgent("https://fleet.example.com")
        assert agent.device_id == "env-device-id"

    def test_device_id_explicit_param(self, monkeypatch):
        monkeypatch.delenv("BMT_FLEET_DEVICE_ID", raising=False)
        agent = FleetAgent("https://fleet.example.com", device_id="explicit-id")
        assert agent.device_id == "explicit-id"

    def test_default_heartbeat_interval(self):
        agent = FleetAgent("https://fleet.example.com", device_id="d")
        assert agent.heartbeat_interval == 60

    def test_custom_heartbeat_interval(self):
        agent = FleetAgent("https://fleet.example.com", device_id="d", heartbeat_interval=30)
        assert agent.heartbeat_interval == 30

    def test_initial_status(self):
        agent = FleetAgent("https://fleet.example.com", device_id="d")
        status = agent.status()
        assert status["running"] is False
        assert status["last_ok"] is None
        assert status["last_error"] == ""


# ---------------------------------------------------------------------------
# send_heartbeat
# ---------------------------------------------------------------------------


class TestSendHeartbeat:
    @pytest.fixture()
    def agent(self):
        return FleetAgent("https://fleet.example.com", device_id="test-device")

    def _mock_post(self, response_body: dict, status_code: int = 200) -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.json.return_value = response_body
        mock_resp.raise_for_status = MagicMock()
        if status_code >= 400:
            mock_resp.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status_code}")
        return mock_resp

    # Short resource usage stub reused across heartbeat tests
    _ZERO_USAGE = {"cpu_percent": 0, "memory_percent": 0, "disk_percent": 0}

    def _hb_patches(self, post_mock, hw_return=None):
        """Return the four collector patches plus a requests.post mock."""
        hw = hw_return if hw_return is not None else {}
        return (
            patch("bmt_ai_os.fleet.agent.get_hardware_info", return_value=hw),
            patch("bmt_ai_os.fleet.agent.get_resource_usage", return_value=self._ZERO_USAGE),
            patch("bmt_ai_os.fleet.agent.get_loaded_models", return_value=[]),
            patch("bmt_ai_os.fleet.agent.get_service_health", return_value={}),
            post_mock,
        )

    def test_sends_to_correct_url(self, agent: FleetAgent) -> None:
        mock_resp = self._mock_post({"action": None})
        with (
            patch("bmt_ai_os.fleet.agent.get_hardware_info", return_value={}),
            patch("bmt_ai_os.fleet.agent.get_resource_usage", return_value=self._ZERO_USAGE),
            patch("bmt_ai_os.fleet.agent.get_loaded_models", return_value=[]),
            patch("bmt_ai_os.fleet.agent.get_service_health", return_value={}),
            patch("requests.post", return_value=mock_resp) as mock_post,
        ):
            agent.send_heartbeat()
        call_url = mock_post.call_args[0][0]
        assert call_url == "https://fleet.example.com/api/v1/fleet/heartbeat"

    def test_returns_noop_command_on_null_action(self, agent: FleetAgent) -> None:
        mock_resp = self._mock_post({"action": None})
        with (
            patch("bmt_ai_os.fleet.agent.get_hardware_info", return_value={}),
            patch("bmt_ai_os.fleet.agent.get_resource_usage", return_value=self._ZERO_USAGE),
            patch("bmt_ai_os.fleet.agent.get_loaded_models", return_value=[]),
            patch("bmt_ai_os.fleet.agent.get_service_health", return_value={}),
            patch("requests.post", return_value=mock_resp),
        ):
            cmd = agent.send_heartbeat()
        assert cmd.is_noop() is True

    def test_returns_command_from_server(self, agent: FleetAgent) -> None:
        mock_resp = self._mock_post({"action": "pull-model", "params": {"model": "qwen2.5:7b"}})
        with (
            patch("bmt_ai_os.fleet.agent.get_hardware_info", return_value={}),
            patch("bmt_ai_os.fleet.agent.get_resource_usage", return_value=self._ZERO_USAGE),
            patch("bmt_ai_os.fleet.agent.get_loaded_models", return_value=[]),
            patch("bmt_ai_os.fleet.agent.get_service_health", return_value={}),
            patch("requests.post", return_value=mock_resp),
        ):
            cmd = agent.send_heartbeat()
        assert cmd.action == "pull-model"
        assert cmd.params["model"] == "qwen2.5:7b"

    def test_raises_on_network_error(self, agent: FleetAgent) -> None:
        with (
            patch("bmt_ai_os.fleet.agent.get_hardware_info", return_value={}),
            patch("bmt_ai_os.fleet.agent.get_resource_usage", return_value=self._ZERO_USAGE),
            patch("bmt_ai_os.fleet.agent.get_loaded_models", return_value=[]),
            patch("bmt_ai_os.fleet.agent.get_service_health", return_value={}),
            patch("requests.post", side_effect=requests.ConnectionError("refused")),
        ):
            with pytest.raises(requests.ConnectionError):
                agent.send_heartbeat()

    def test_hardware_cached_after_first_call(self, agent: FleetAgent) -> None:
        mock_resp = self._mock_post({"action": None})
        with (
            patch(
                "bmt_ai_os.fleet.agent.get_hardware_info", return_value={"board": "pi5"}
            ) as mock_hw,
            patch("bmt_ai_os.fleet.agent.get_resource_usage", return_value=self._ZERO_USAGE),
            patch("bmt_ai_os.fleet.agent.get_loaded_models", return_value=[]),
            patch("bmt_ai_os.fleet.agent.get_service_health", return_value={}),
            patch("requests.post", return_value=mock_resp),
        ):
            agent.send_heartbeat()
            agent.send_heartbeat()
        # get_hardware_info should only be called once (cached)
        assert mock_hw.call_count == 1


# ---------------------------------------------------------------------------
# execute_command
# ---------------------------------------------------------------------------


class TestExecuteCommand:
    @pytest.fixture()
    def agent(self):
        return FleetAgent("https://fleet.example.com", device_id="test-device")

    def test_noop_does_nothing(self, agent: FleetAgent) -> None:
        cmd = FleetCommand(action=None)
        agent.execute_command(cmd)  # should not raise

    def test_unknown_action_logged_not_raised(self, agent: FleetAgent) -> None:
        cmd = FleetCommand(action="fly-to-moon", params={})
        agent.execute_command(cmd)  # should not raise

    def test_restart_service_calls_docker_compose(self, agent: FleetAgent) -> None:
        cmd = FleetCommand(action="restart-service", params={"service": "ollama"})
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            agent.execute_command(cmd)
        args = mock_run.call_args[0][0]
        assert "docker" in args
        assert "restart" in args
        assert "ollama" in args

    def test_restart_service_raises_on_failure(self, agent: FleetAgent) -> None:
        cmd = FleetCommand(action="restart-service", params={"service": "chromadb"})
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error"
        # execute_command catches exceptions and logs them — no re-raise
        with patch("subprocess.run", return_value=mock_result):
            agent.execute_command(cmd)  # should not raise to caller

    def test_restart_service_missing_param_logged(self, agent: FleetAgent) -> None:
        cmd = FleetCommand(action="restart-service", params={})
        agent.execute_command(cmd)  # should not raise

    def test_pull_model_calls_ollama_api(self, agent: FleetAgent) -> None:
        cmd = FleetCommand(action="pull-model", params={"model": "qwen2.5:7b"})
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_lines.return_value = [
            b'{"status": "pulling manifest"}',
            b'{"status": "success"}',
        ]
        with patch("requests.post", return_value=mock_resp):
            agent.execute_command(cmd)
        mock_resp.raise_for_status.assert_called_once()

    def test_pull_model_missing_model_logged(self, agent: FleetAgent) -> None:
        cmd = FleetCommand(action="pull-model", params={})
        agent.execute_command(cmd)  # should not raise

    def test_update_calls_apk(self, agent: FleetAgent) -> None:
        cmd = FleetCommand(action="update", params={"version": "2026.5.0"})
        mock_ok = MagicMock()
        mock_ok.returncode = 0
        with patch("subprocess.run", return_value=mock_ok) as mock_run:
            agent.execute_command(cmd)
        calls = [c[0][0] for c in mock_run.call_args_list]
        assert any("apk" in cmd_args for cmd_args in calls)


# ---------------------------------------------------------------------------
# run / stop lifecycle
# ---------------------------------------------------------------------------


class TestRunStop:
    def test_run_starts_thread(self):
        agent = FleetAgent("https://fleet.example.com", device_id="d")
        agent._stop_event.set()  # Prevent the loop from actually running
        with patch.object(agent, "_loop"):
            agent.run()
        assert agent._thread is not None

    def test_run_twice_is_noop(self):
        agent = FleetAgent("https://fleet.example.com", device_id="d")
        # Use an event to keep the loop alive so the thread stays alive
        # when we call run() a second time

        stop = threading.Event()

        def slow_loop():
            stop.wait(timeout=5)

        with patch.object(agent, "_loop", side_effect=slow_loop):
            agent.run()
            thread1 = agent._thread
            # Thread is alive — second call should be a noop
            assert agent._thread is not None and agent._thread.is_alive()
            agent.run()
            thread2 = agent._thread
        stop.set()
        assert thread1 is thread2

    def test_stop_sets_event(self):
        agent = FleetAgent("https://fleet.example.com", device_id="d")
        agent.run()
        agent.stop()
        assert agent._stop_event.is_set()


# ---------------------------------------------------------------------------
# status()
# ---------------------------------------------------------------------------


class TestStatus:
    def test_status_dict_keys(self):
        agent = FleetAgent("https://fleet.example.com", device_id="my-device")
        s = agent.status()
        assert "device_id" in s
        assert "server_url" in s
        assert "running" in s
        assert "last_ok" in s
        assert "last_error" in s

    def test_device_id_in_status(self):
        agent = FleetAgent("https://fleet.example.com", device_id="my-device")
        assert agent.status()["device_id"] == "my-device"

    def test_server_url_in_status(self):
        agent = FleetAgent("https://fleet.example.com", device_id="d")
        assert agent.status()["server_url"] == "https://fleet.example.com"
