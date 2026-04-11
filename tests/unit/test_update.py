"""Unit tests for the OS update orchestration layer.

All tests are offline — no network calls, no block devices, no Docker.
External calls are injected via the orchestrator's injection points.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bmt_ai_os.ota.engine import UpdateInfo
from bmt_ai_os.ota.state import OTAState, StateManager
from bmt_ai_os.update.orchestrator import (
    StageResult,
    UpdateOrchestrator,
    UpdateResult,
    _read_current_version,
    run_full_update,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_sm(tmp_path: Path, slot: str = "a") -> StateManager:
    sm = StateManager(path=tmp_path / "ota-state.json")
    sm.save(OTAState(current_slot=slot, standby_slot="b" if slot == "a" else "a"))
    return sm


def _mock_check_update(info: UpdateInfo | None):
    """Return a callable that mimics check_update."""
    return lambda server_url, current_version=None: info


def _mock_download_ok(url, dest, sha256, **kw) -> bool:
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    Path(dest).write_bytes(b"fake image data")
    return True


def _mock_download_fail(url, dest, sha256, **kw) -> bool:
    return False


def _mock_apply_ok(image_path, target_slot, dry_run=None, state_manager=None) -> bool:
    if state_manager:
        state_manager.switch_slots()
    return True


def _mock_apply_fail(image_path, target_slot, dry_run=None, state_manager=None) -> bool:
    return False


def _mock_subprocess_ok(*args, **kwargs):
    return MagicMock(returncode=0, stderr=b"")


def _mock_subprocess_fail(*args, **kwargs):
    return MagicMock(returncode=1, stderr=b"docker: error")


def _mock_subprocess_not_found(*args, **kwargs):
    raise FileNotFoundError("docker not found")


def _mock_subprocess_timeout(*args, **kwargs):
    raise subprocess.TimeoutExpired(cmd=args[0], timeout=1800)


# ---------------------------------------------------------------------------
# StageResult / UpdateResult
# ---------------------------------------------------------------------------


class TestUpdateResult:
    def test_success_when_all_stages_pass(self):
        r = UpdateResult()
        r.add(StageResult(name="s1", success=True))
        r.add(StageResult(name="s2", success=True))
        assert r.success is True

    def test_failure_when_any_stage_fails(self):
        r = UpdateResult()
        r.add(StageResult(name="s1", success=True))
        r.add(StageResult(name="s2", success=False))
        assert r.success is False

    def test_skipped_stages_do_not_affect_success(self):
        r = UpdateResult()
        r.add(StageResult(name="s1", success=True))
        r.add(StageResult(name="s2", success=False, skipped=True))
        assert r.success is True

    def test_all_skipped_is_success(self):
        r = UpdateResult()
        r.add(StageResult(name="s1", success=False, skipped=True))
        assert r.success is True

    def test_new_version_defaults_to_none(self):
        assert UpdateResult().new_version is None


# ---------------------------------------------------------------------------
# Data stages
# ---------------------------------------------------------------------------


class TestDataStages:
    def test_data_check_passes_when_data_dir_is_absent(self, tmp_path, monkeypatch):
        """On a fresh device /data sub-paths may not exist yet — that's OK."""
        monkeypatch.chdir(tmp_path)
        sm = _make_sm(tmp_path)
        orc = UpdateOrchestrator(
            state_manager=sm,
            _check_fn=_mock_check_update(None),
        )
        stage = orc._stage_data_check()
        assert stage.success is True

    def test_data_check_fails_when_preserved_path_is_a_file(self, tmp_path, monkeypatch):
        """If a preserved path exists as a *file* rather than a dir, flag it."""
        from bmt_ai_os.update import orchestrator as mod

        fake_data = tmp_path / "data"
        fake_data.mkdir()
        # Create one of the preserved sub-paths as a regular file.
        bad = fake_data / "bmt_ai_os" / "db"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("oops")  # file, not a directory

        monkeypatch.setattr(mod, "_DATA_MOUNT", fake_data)
        monkeypatch.setattr(mod, "_PRESERVED_PATHS", ["bmt_ai_os/db"])

        sm = _make_sm(tmp_path)
        orc = UpdateOrchestrator(state_manager=sm, _check_fn=_mock_check_update(None))
        stage = orc._stage_data_check()
        assert stage.success is False
        assert "non-directory" in stage.message

    def test_data_verify_passes_when_data_exists(self, tmp_path, monkeypatch):
        from bmt_ai_os.update import orchestrator as mod

        fake_data = tmp_path / "data"
        fake_data.mkdir()
        monkeypatch.setattr(mod, "_DATA_MOUNT", fake_data)

        sm = _make_sm(tmp_path)
        orc = UpdateOrchestrator(state_manager=sm, _check_fn=_mock_check_update(None))
        stage = orc._stage_data_verify()
        assert stage.success is True

    def test_data_verify_fails_when_data_missing(self, tmp_path, monkeypatch):
        from bmt_ai_os.update import orchestrator as mod

        monkeypatch.setattr(mod, "_DATA_MOUNT", tmp_path / "nonexistent")

        sm = _make_sm(tmp_path)
        orc = UpdateOrchestrator(state_manager=sm, _check_fn=_mock_check_update(None))
        stage = orc._stage_data_verify()
        assert stage.success is False
        assert "not accessible" in stage.message


# ---------------------------------------------------------------------------
# OS update stage
# ---------------------------------------------------------------------------


class TestOsUpdateStage:
    def test_skips_when_already_up_to_date(self, tmp_path):
        sm = _make_sm(tmp_path)
        orc = UpdateOrchestrator(
            state_manager=sm,
            _check_fn=_mock_check_update(None),
        )
        stage = orc._stage_os_update()
        assert stage.skipped is True
        assert stage.success is True

    def test_returns_success_when_download_and_apply_succeed(self, tmp_path):
        info = UpdateInfo(
            version="2026.5.1",
            url="https://example.com/bmt.img",
            sha256="a" * 64,
        )
        sm = _make_sm(tmp_path)
        orc = UpdateOrchestrator(
            state_manager=sm,
            _check_fn=_mock_check_update(info),
            _download_fn=_mock_download_ok,
            _apply_fn=_mock_apply_ok,
        )
        stage = orc._stage_os_update()
        assert stage.success is True
        assert stage.skipped is False
        assert "2026.5.1" in stage.message

    def test_records_new_version_on_success(self, tmp_path):
        info = UpdateInfo(
            version="2026.5.1",
            url="https://example.com/bmt.img",
            sha256="a" * 64,
        )
        sm = _make_sm(tmp_path)
        orc = UpdateOrchestrator(
            state_manager=sm,
            _check_fn=_mock_check_update(info),
            _download_fn=_mock_download_ok,
            _apply_fn=_mock_apply_ok,
        )
        orc._stage_os_update()
        assert orc._last_update_info_version == "2026.5.1"

    def test_fails_when_download_fails(self, tmp_path):
        info = UpdateInfo(
            version="2026.5.1",
            url="https://example.com/bmt.img",
            sha256="a" * 64,
        )
        sm = _make_sm(tmp_path)
        orc = UpdateOrchestrator(
            state_manager=sm,
            _check_fn=_mock_check_update(info),
            _download_fn=_mock_download_fail,
            _apply_fn=_mock_apply_ok,
        )
        stage = orc._stage_os_update()
        assert stage.success is False
        assert "download" in stage.message

    def test_fails_when_apply_fails(self, tmp_path):
        info = UpdateInfo(
            version="2026.5.1",
            url="https://example.com/bmt.img",
            sha256="a" * 64,
        )
        sm = _make_sm(tmp_path)
        orc = UpdateOrchestrator(
            state_manager=sm,
            _check_fn=_mock_check_update(info),
            _download_fn=_mock_download_ok,
            _apply_fn=_mock_apply_fail,
        )
        stage = orc._stage_os_update()
        assert stage.success is False
        assert "slot" in stage.message

    def test_writes_to_standby_slot(self, tmp_path):
        """Verify the orchestrator always targets the *inactive* slot."""
        info = UpdateInfo(
            version="2026.5.1",
            url="https://example.com/bmt.img",
            sha256="a" * 64,
        )
        applied_slots: list[str] = []

        def _record_apply(image_path, target_slot, dry_run=None, state_manager=None):
            applied_slots.append(target_slot)
            return True

        # Current slot is "a" → should write to "b".
        sm = _make_sm(tmp_path, slot="a")
        orc = UpdateOrchestrator(
            state_manager=sm,
            _check_fn=_mock_check_update(info),
            _download_fn=_mock_download_ok,
            _apply_fn=_record_apply,
        )
        orc._stage_os_update()
        assert applied_slots == ["b"]

    def test_writes_to_slot_a_when_current_is_b(self, tmp_path):
        info = UpdateInfo(
            version="2026.5.1",
            url="https://example.com/bmt.img",
            sha256="a" * 64,
        )
        applied_slots: list[str] = []

        def _record_apply(image_path, target_slot, dry_run=None, state_manager=None):
            applied_slots.append(target_slot)
            return True

        sm = _make_sm(tmp_path, slot="b")
        orc = UpdateOrchestrator(
            state_manager=sm,
            _check_fn=_mock_check_update(info),
            _download_fn=_mock_download_ok,
            _apply_fn=_record_apply,
        )
        with patch("subprocess.run", side_effect=FileNotFoundError):
            orc._stage_os_update()
        assert applied_slots == ["a"]


# ---------------------------------------------------------------------------
# Container stage
# ---------------------------------------------------------------------------


class TestContainerStage:
    def test_success_when_compose_pull_exits_zero(self, tmp_path):
        compose = tmp_path / "docker-compose.yml"
        compose.write_text("version: '3'")

        sm = _make_sm(tmp_path)
        orc = UpdateOrchestrator(
            state_manager=sm,
            compose_file=str(compose),
            _check_fn=_mock_check_update(None),
            _subprocess_run=_mock_subprocess_ok,
        )
        stage = orc._stage_containers()
        assert stage.success is True
        assert stage.skipped is False

    def test_skips_when_compose_file_not_found(self, tmp_path):
        sm = _make_sm(tmp_path)
        orc = UpdateOrchestrator(
            state_manager=sm,
            compose_file=str(tmp_path / "nonexistent-compose.yml"),
            _check_fn=_mock_check_update(None),
            _subprocess_run=_mock_subprocess_ok,
        )
        stage = orc._stage_containers()
        assert stage.skipped is True
        assert stage.success is True

    def test_skips_when_docker_not_on_path(self, tmp_path):
        compose = tmp_path / "docker-compose.yml"
        compose.write_text("version: '3'")

        sm = _make_sm(tmp_path)
        orc = UpdateOrchestrator(
            state_manager=sm,
            compose_file=str(compose),
            _check_fn=_mock_check_update(None),
            _subprocess_run=_mock_subprocess_not_found,
        )
        stage = orc._stage_containers()
        assert stage.skipped is True
        assert stage.success is True
        assert "docker not found" in stage.message

    def test_fails_when_compose_pull_exits_nonzero(self, tmp_path):
        compose = tmp_path / "docker-compose.yml"
        compose.write_text("version: '3'")

        sm = _make_sm(tmp_path)
        orc = UpdateOrchestrator(
            state_manager=sm,
            compose_file=str(compose),
            _check_fn=_mock_check_update(None),
            _subprocess_run=_mock_subprocess_fail,
        )
        stage = orc._stage_containers()
        assert stage.success is False
        assert "exited 1" in stage.message

    def test_fails_when_compose_pull_times_out(self, tmp_path):
        compose = tmp_path / "docker-compose.yml"
        compose.write_text("version: '3'")

        sm = _make_sm(tmp_path)
        orc = UpdateOrchestrator(
            state_manager=sm,
            compose_file=str(compose),
            _check_fn=_mock_check_update(None),
            _subprocess_run=_mock_subprocess_timeout,
        )
        stage = orc._stage_containers()
        assert stage.success is False
        assert "timed out" in stage.message

    def test_pull_command_includes_compose_file(self, tmp_path):
        """Verify the exact docker compose invocation contains the right file."""
        compose = tmp_path / "docker-compose.yml"
        compose.write_text("version: '3'")
        captured_cmds: list[list[str]] = []

        def _capture(cmd, **kwargs):
            captured_cmds.append(list(cmd))
            return MagicMock(returncode=0, stderr=b"")

        sm = _make_sm(tmp_path)
        orc = UpdateOrchestrator(
            state_manager=sm,
            compose_file=str(compose),
            _check_fn=_mock_check_update(None),
            _subprocess_run=_capture,
        )
        orc._stage_containers()
        assert len(captured_cmds) == 1
        cmd = captured_cmds[0]
        assert "docker" in cmd
        assert "compose" in cmd
        assert str(compose) in cmd
        assert "pull" in cmd


# ---------------------------------------------------------------------------
# Full orchestration (run())
# ---------------------------------------------------------------------------


class TestUpdateOrchestratorRun:
    def test_full_run_up_to_date_is_success(self, tmp_path, monkeypatch):
        from bmt_ai_os.update import orchestrator as mod

        monkeypatch.setattr(mod, "_DATA_MOUNT", tmp_path / "data")
        (tmp_path / "data").mkdir()

        compose = tmp_path / "docker-compose.yml"
        compose.write_text("version: '3'")

        sm = _make_sm(tmp_path)
        orc = UpdateOrchestrator(
            state_manager=sm,
            compose_file=str(compose),
            _check_fn=_mock_check_update(None),
            _subprocess_run=_mock_subprocess_ok,
        )
        result = orc.run()
        assert result.success is True
        assert result.new_version is None

    def test_full_run_with_update_returns_new_version(self, tmp_path, monkeypatch):
        from bmt_ai_os.update import orchestrator as mod

        monkeypatch.setattr(mod, "_DATA_MOUNT", tmp_path / "data")
        (tmp_path / "data").mkdir()

        compose = tmp_path / "docker-compose.yml"
        compose.write_text("version: '3'")

        info = UpdateInfo(
            version="2026.5.1",
            url="https://example.com/bmt.img",
            sha256="a" * 64,
        )
        sm = _make_sm(tmp_path)
        orc = UpdateOrchestrator(
            state_manager=sm,
            compose_file=str(compose),
            _check_fn=_mock_check_update(info),
            _download_fn=_mock_download_ok,
            _apply_fn=_mock_apply_ok,
            _subprocess_run=_mock_subprocess_ok,
        )
        result = orc.run()
        assert result.success is True
        assert result.new_version == "2026.5.1"

    def test_full_run_stage_names(self, tmp_path, monkeypatch):
        from bmt_ai_os.update import orchestrator as mod

        monkeypatch.setattr(mod, "_DATA_MOUNT", tmp_path / "data")
        (tmp_path / "data").mkdir()

        sm = _make_sm(tmp_path)
        orc = UpdateOrchestrator(
            state_manager=sm,
            _check_fn=_mock_check_update(None),
            _subprocess_run=_mock_subprocess_ok,
        )
        result = orc.run()
        names = [s.name for s in result.stages]
        assert "data_check" in names
        assert "os_update" in names
        assert "containers" in names
        assert "data_verify" in names

    def test_container_failure_does_not_block_os_success(self, tmp_path, monkeypatch):
        """A docker pull failure is recorded but the overall result can still
        report the OS update as successful via new_version."""
        from bmt_ai_os.update import orchestrator as mod

        monkeypatch.setattr(mod, "_DATA_MOUNT", tmp_path / "data")
        (tmp_path / "data").mkdir()

        compose = tmp_path / "docker-compose.yml"
        compose.write_text("version: '3'")

        info = UpdateInfo(
            version="2026.5.1",
            url="https://example.com/bmt.img",
            sha256="a" * 64,
        )
        sm = _make_sm(tmp_path)
        orc = UpdateOrchestrator(
            state_manager=sm,
            compose_file=str(compose),
            _check_fn=_mock_check_update(info),
            _download_fn=_mock_download_ok,
            _apply_fn=_mock_apply_ok,
            _subprocess_run=_mock_subprocess_fail,
        )
        result = orc.run()
        # OS update succeeded.
        os_stage = next(s for s in result.stages if s.name == "os_update")
        assert os_stage.success is True
        assert result.new_version == "2026.5.1"
        # Container stage failed.
        ct_stage = next(s for s in result.stages if s.name == "containers")
        assert ct_stage.success is False
        # Overall result is False because containers failed.
        assert result.success is False

    def test_os_update_failure_records_no_new_version(self, tmp_path, monkeypatch):
        from bmt_ai_os.update import orchestrator as mod

        monkeypatch.setattr(mod, "_DATA_MOUNT", tmp_path / "data")
        (tmp_path / "data").mkdir()

        info = UpdateInfo(
            version="2026.5.1",
            url="https://example.com/bmt.img",
            sha256="a" * 64,
        )
        sm = _make_sm(tmp_path)
        orc = UpdateOrchestrator(
            state_manager=sm,
            _check_fn=_mock_check_update(info),
            _download_fn=_mock_download_fail,
            _apply_fn=_mock_apply_ok,
            _subprocess_run=_mock_subprocess_ok,
        )
        result = orc.run()
        assert result.new_version is None
        assert result.success is False

    def test_check_method_delegates_to_check_fn(self, tmp_path):
        info = UpdateInfo(
            version="2026.5.1",
            url="https://example.com/bmt.img",
            sha256="a" * 64,
        )
        sm = _make_sm(tmp_path)
        orc = UpdateOrchestrator(
            state_manager=sm,
            _check_fn=_mock_check_update(info),
        )
        returned = orc.check()
        assert returned is info

    def test_confirm_delegates_to_confirm_boot(self, tmp_path):
        sm = _make_sm(tmp_path)
        sm.increment_bootcount()

        orc = UpdateOrchestrator(state_manager=sm, _check_fn=_mock_check_update(None))
        with patch("subprocess.run", return_value=MagicMock(returncode=0)):
            orc.confirm()

        state = sm.load()
        assert state.confirmed is True
        assert state.bootcount == 0


# ---------------------------------------------------------------------------
# run_full_update convenience wrapper
# ---------------------------------------------------------------------------


class TestRunFullUpdate:
    def test_returns_update_result(self, tmp_path, monkeypatch):
        from bmt_ai_os.update import orchestrator as mod

        monkeypatch.setattr(mod, "_DATA_MOUNT", tmp_path / "data")
        (tmp_path / "data").mkdir()

        sm = _make_sm(tmp_path)
        result = run_full_update(
            server_url="https://example.com/latest.json",
            state_manager=sm,
            _check_fn=_mock_check_update(None),
            _subprocess_run=_mock_subprocess_ok,
        )
        assert isinstance(result, UpdateResult)
        assert result.success is True

    def test_dry_run_flag_is_forwarded(self, tmp_path, monkeypatch):
        from bmt_ai_os.update import orchestrator as mod

        monkeypatch.setattr(mod, "_DATA_MOUNT", tmp_path / "data")
        (tmp_path / "data").mkdir()

        info = UpdateInfo(
            version="2026.5.1",
            url="https://example.com/bmt.img",
            sha256="a" * 64,
        )
        dry_run_flags: list[bool] = []

        def _record_apply(image_path, target_slot, dry_run=None, state_manager=None):
            dry_run_flags.append(bool(dry_run))
            return True

        sm = _make_sm(tmp_path)
        run_full_update(
            state_manager=sm,
            dry_run=True,
            _check_fn=_mock_check_update(info),
            _download_fn=_mock_download_ok,
            _apply_fn=_record_apply,
            _subprocess_run=_mock_subprocess_ok,
        )
        assert dry_run_flags == [True]


# ---------------------------------------------------------------------------
# _read_current_version helper
# ---------------------------------------------------------------------------


class TestReadCurrentVersion:
    def test_reads_from_env(self, monkeypatch):
        monkeypatch.setenv("BMT_OS_VERSION", "2026.9.1")
        assert _read_current_version() == "2026.9.1"

    def test_reads_from_release_file(self, tmp_path, monkeypatch):
        release_file = tmp_path / "bmt-release"
        release_file.write_text("2026.8.1\n")
        monkeypatch.delenv("BMT_OS_VERSION", raising=False)

        original_is_file = Path.is_file
        original_read_text = Path.read_text

        def _is_file(self):
            if str(self) == "/etc/bmt-release":
                return True
            return original_is_file(self)

        def _read_text(self, *args, **kwargs):
            if str(self) == "/etc/bmt-release":
                return release_file.read_text()
            return original_read_text(self, *args, **kwargs)

        with patch.object(Path, "is_file", _is_file), patch.object(Path, "read_text", _read_text):
            ver = _read_current_version()
        assert ver == "2026.8.1"

    def test_falls_back_to_cli_version(self, monkeypatch):
        monkeypatch.delenv("BMT_OS_VERSION", raising=False)
        # Patch out the release file check.
        with patch("pathlib.Path.is_file", return_value=False):
            ver = _read_current_version()
        # Should equal the CLI __version__ constant.
        from bmt_ai_os.cli import __version__

        assert ver == __version__

    def test_env_takes_priority_over_release_file(self, monkeypatch):
        monkeypatch.setenv("BMT_OS_VERSION", "2099.1.1")
        ver = _read_current_version()
        assert ver == "2099.1.1"


# ---------------------------------------------------------------------------
# CLI integration (click CliRunner)
# ---------------------------------------------------------------------------


class TestCLIUpdateRun:
    @pytest.fixture()
    def runner(self):
        from click.testing import CliRunner

        return CliRunner()

    def test_run_no_update_available(self, runner, tmp_path, monkeypatch):
        """When no update is available the command exits 0 and says up-to-date."""
        from bmt_ai_os.update import orchestrator as mod

        monkeypatch.setattr(mod, "_DATA_MOUNT", tmp_path / "data")
        (tmp_path / "data").mkdir()

        state_file = str(tmp_path / "state.json")

        with (
            patch("bmt_ai_os.update.orchestrator.check_update", return_value=None),
            patch("subprocess.run", side_effect=FileNotFoundError),
        ):
            from bmt_ai_os.cli import main

            result = runner.invoke(
                main,
                [
                    "update",
                    "run",
                    "--server",
                    "https://example.com/latest.json",
                    "--state-file",
                    state_file,
                    "--dry-run",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "up to date" in result.output.lower()

    def test_run_exits_1_on_failure(self, runner, tmp_path, monkeypatch):
        """When the OS update stage fails the command exits 1."""
        from bmt_ai_os.update import orchestrator as mod

        monkeypatch.setattr(mod, "_DATA_MOUNT", tmp_path / "data")
        (tmp_path / "data").mkdir()

        state_file = str(tmp_path / "state.json")

        info = UpdateInfo(
            version="2026.5.1",
            url="https://example.com/bmt.img",
            sha256="a" * 64,
        )

        with (
            patch("bmt_ai_os.update.orchestrator.check_update", return_value=info),
            patch("bmt_ai_os.update.orchestrator.download_image", return_value=False),
        ):
            from bmt_ai_os.cli import main

            result = runner.invoke(
                main,
                [
                    "update",
                    "run",
                    "--server",
                    "https://example.com/latest.json",
                    "--state-file",
                    state_file,
                    "--dry-run",
                ],
            )

        assert result.exit_code == 1

    def test_run_shows_stage_results(self, runner, tmp_path, monkeypatch):
        """Output includes labelled stage lines."""
        from bmt_ai_os.update import orchestrator as mod

        monkeypatch.setattr(mod, "_DATA_MOUNT", tmp_path / "data")
        (tmp_path / "data").mkdir()

        state_file = str(tmp_path / "state.json")

        with (
            patch("bmt_ai_os.update.orchestrator.check_update", return_value=None),
            patch("subprocess.run", side_effect=FileNotFoundError),
        ):
            from bmt_ai_os.cli import main

            result = runner.invoke(
                main,
                [
                    "update",
                    "run",
                    "--state-file",
                    state_file,
                    "--dry-run",
                ],
            )

        assert "data_check" in result.output
        assert "os_update" in result.output

    def test_skip_containers_flag(self, runner, tmp_path, monkeypatch):
        """--skip-containers makes the container stage always skip."""
        from bmt_ai_os.update import orchestrator as mod

        monkeypatch.setattr(mod, "_DATA_MOUNT", tmp_path / "data")
        (tmp_path / "data").mkdir()

        state_file = str(tmp_path / "state.json")

        called_docker: list[bool] = []

        def _spy_subprocess(cmd, **kwargs):
            called_docker.append(True)
            return MagicMock(returncode=0, stderr=b"")

        with patch("bmt_ai_os.update.orchestrator.check_update", return_value=None):
            from bmt_ai_os.cli import main

            result = runner.invoke(
                main,
                [
                    "update",
                    "run",
                    "--state-file",
                    state_file,
                    "--dry-run",
                    "--skip-containers",
                ],
            )

        assert result.exit_code == 0
        # Docker should not have been called.
        assert not called_docker
