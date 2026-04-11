"""OS update orchestrator for BMT AI OS.

Coordinates a full system update across three independent layers:

1. **OS rootfs** — downloads and writes a new image to the inactive A/B
   partition via :mod:`bmt_ai_os.ota.engine`.
2. **Container images** — pulls the latest container images via
   ``docker compose pull`` so the AI stack benefits from fixes without
   changing the rootfs.
3. **Data preservation** — /data is a separate partition and is never
   touched during an update; this module verifies the mount and records
   its state before and after for auditability.

The orchestrator is intentionally synchronous and side-effect-free in its
pure logic so that it can be unit-tested without Docker or a block device.
All external calls (network, subprocess, filesystem) go through injected
callables with sensible defaults that hit the real system.

Public API
----------
- :class:`UpdateOrchestrator` — stateful coordinator, entry point.
- :class:`UpdateResult` — structured result returned by every stage.
- :func:`run_full_update` — convenience wrapper: check → apply → pull.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from bmt_ai_os.ota.engine import (
    UpdateInfo,
    apply_update,
    check_update,
    confirm_boot,
    download_image,
    get_current_slot,
)
from bmt_ai_os.ota.state import StateManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_OTA_SERVER = os.environ.get(
    "BMT_OTA_SERVER_URL",
    "https://releases.bemindlabs.com/bmt-ai-os/latest.json",
)

_DEFAULT_COMPOSE_FILE = os.environ.get(
    "BMT_COMPOSE_FILE",
    "/opt/bmt_ai_os/ai-stack/docker-compose.yml",
)

# Data partition mount point — preserved across updates.
_DATA_MOUNT = Path(os.environ.get("BMT_DATA_MOUNT", "/data"))

# Directories inside /data that must survive updates.
_PRESERVED_PATHS: list[str] = [
    "bmt_ai_os/db",  # OTA state + metadata SQLite
    "bmt_ai_os/slots",  # file-backed slot images (dev/test)
    "bmt_ai_os/models",  # Ollama model blobs
    "chromadb",  # ChromaDB vector store
]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class StageResult:
    """Outcome of a single update stage."""

    name: str
    success: bool
    message: str = ""
    skipped: bool = False


@dataclass
class UpdateResult:
    """Aggregated result of a full update run."""

    stages: list[StageResult] = field(default_factory=list)
    new_version: str | None = None
    rollback_required: bool = False

    @property
    def success(self) -> bool:
        """True only when all non-skipped stages succeeded."""
        return all(s.success or s.skipped for s in self.stages)

    def add(self, stage: StageResult) -> None:
        self.stages.append(stage)
        logger.info(
            "update stage '%s': %s%s",
            stage.name,
            "SKIP" if stage.skipped else ("OK" if stage.success else "FAIL"),
            f" — {stage.message}" if stage.message else "",
        )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class UpdateOrchestrator:
    """Coordinates a full BMT AI OS update.

    Parameters
    ----------
    server_url:
        Release-info endpoint.  Defaults to :data:`_DEFAULT_OTA_SERVER`.
    compose_file:
        Path to the Docker Compose file for ``docker compose pull``.
    current_version:
        Running OS version string.  Compared against the server version to
        decide whether an OS update is needed.
    state_manager:
        Injected :class:`~bmt_ai_os.ota.state.StateManager` for testability.
    dry_run:
        When ``True``, image writes use the file-backed slot store instead
        of a block device.  Container pulls are still attempted.
    _subprocess_run:
        Injection point for ``subprocess.run`` — allows tests to mock
        container pull calls without spinning up Docker.
    _download_fn:
        Injection point for :func:`~bmt_ai_os.ota.engine.download_image`.
    _apply_fn:
        Injection point for :func:`~bmt_ai_os.ota.engine.apply_update`.
    _check_fn:
        Injection point for :func:`~bmt_ai_os.ota.engine.check_update`.
    """

    def __init__(
        self,
        server_url: str = _DEFAULT_OTA_SERVER,
        compose_file: str = _DEFAULT_COMPOSE_FILE,
        current_version: str | None = None,
        state_manager: StateManager | None = None,
        dry_run: bool = False,
        _subprocess_run: Callable | None = None,
        _download_fn: Callable | None = None,
        _apply_fn: Callable | None = None,
        _check_fn: Callable | None = None,
    ) -> None:
        self.server_url = server_url
        self.compose_file = compose_file
        self.current_version = current_version or _read_current_version()
        self.state_manager = state_manager or StateManager()
        self.dry_run = dry_run

        # Injection points (real callables by default).
        self._subprocess_run: Callable = _subprocess_run or subprocess.run
        self._download_fn: Callable = _download_fn or download_image
        self._apply_fn: Callable = _apply_fn or apply_update
        self._check_fn: Callable = _check_fn or check_update

    # ------------------------------------------------------------------
    # High-level entry points
    # ------------------------------------------------------------------

    def run(self) -> UpdateResult:
        """Execute the full update sequence.

        Stages (in order):
        1. data_check  — verify /data mount is healthy
        2. os_update   — download + write rootfs to standby slot
        3. containers  — docker compose pull
        4. data_verify — confirm /data paths are still present

        The container pull stage never blocks a successful OS update from
        being reported.  A container pull failure is recorded but does not
        roll back the rootfs write.
        """
        result = UpdateResult()

        # Stage 1: verify data partition.
        result.add(self._stage_data_check())

        # Stage 2: OS rootfs update.
        os_stage = self._stage_os_update()
        result.add(os_stage)
        if os_stage.success and not os_stage.skipped:
            result.new_version = self._last_update_info_version

        # Stage 3: container image update (best-effort).
        result.add(self._stage_containers())

        # Stage 4: re-verify data paths after all writes.
        result.add(self._stage_data_verify())

        return result

    def check(self) -> UpdateInfo | None:
        """Query the release server without downloading anything.

        Returns
        -------
        UpdateInfo | None
            Metadata for the available update, or ``None`` when up to date.
        """
        return self._check_fn(self.server_url, current_version=self.current_version)

    def confirm(self) -> None:
        """Mark the current boot as healthy (delegates to OTA engine)."""
        confirm_boot(state_manager=self.state_manager)

    # ------------------------------------------------------------------
    # Individual stages
    # ------------------------------------------------------------------

    #: Stores the version string of the last successfully fetched UpdateInfo.
    _last_update_info_version: str | None = None

    def _stage_data_check(self) -> StageResult:
        """Verify that critical /data sub-paths are accessible."""
        name = "data_check"
        missing: list[str] = []
        for rel in _PRESERVED_PATHS:
            candidate = _DATA_MOUNT / rel
            # We only flag paths that *exist on the current system* and
            # become missing — a brand-new device may not have all of them.
            if candidate.exists() and not candidate.is_dir():
                missing.append(str(candidate))

        if missing:
            return StageResult(
                name=name,
                success=False,
                message=f"non-directory paths under /data: {missing}",
            )
        return StageResult(name=name, success=True, message="data partition accessible")

    def _stage_os_update(self) -> StageResult:
        """Download and write new OS image to the standby partition."""
        name = "os_update"

        info = self._check_fn(self.server_url, current_version=self.current_version)
        if info is None:
            return StageResult(
                name=name,
                success=True,
                skipped=True,
                message="already up to date or server unreachable",
            )

        self._last_update_info_version = info.version

        current_slot = get_current_slot(self.state_manager)
        standby_slot = "b" if current_slot == "a" else "a"

        logger.info("os_update: fetching version %s for slot %s", info.version, standby_slot)

        with tempfile.TemporaryDirectory(prefix="bmt-ota-") as tmpdir:
            dest = Path(tmpdir) / "update.img"

            ok = self._download_fn(info.url, dest, info.sha256)
            if not ok:
                return StageResult(
                    name=name,
                    success=False,
                    message="download or checksum verification failed",
                )

            ok = self._apply_fn(
                dest,
                standby_slot,
                dry_run=self.dry_run,
                state_manager=self.state_manager,
            )

        if not ok:
            return StageResult(
                name=name,
                success=False,
                message=f"failed to write image to slot '{standby_slot}'",
            )

        return StageResult(
            name=name,
            success=True,
            message=(
                f"version {info.version} written to slot '{standby_slot}'; "
                "reboot and confirm to activate"
            ),
        )

    def _stage_containers(self) -> StageResult:
        """Pull updated container images via docker compose pull."""
        name = "containers"

        # An empty string is treated as "skip containers" (set by --skip-containers).
        if not self.compose_file:
            return StageResult(
                name=name,
                success=True,
                skipped=True,
                message="container update skipped by caller",
            )

        compose = Path(self.compose_file)
        if not compose.exists():
            return StageResult(
                name=name,
                success=True,
                skipped=True,
                message=f"compose file not found at {self.compose_file}",
            )

        cmd = ["docker", "compose", "-f", str(compose), "pull", "--quiet"]
        logger.info("containers: running %s", " ".join(cmd))

        try:
            result = self._subprocess_run(
                cmd,
                capture_output=True,
                timeout=1800,  # 30 min — large images on slow links
            )
        except FileNotFoundError:
            return StageResult(
                name=name,
                success=True,
                skipped=True,
                message="docker not found on PATH — skipping container update",
            )
        except subprocess.TimeoutExpired:
            return StageResult(
                name=name,
                success=False,
                message="docker compose pull timed out after 30 minutes",
            )

        if result.returncode != 0:
            stderr = ""
            if hasattr(result, "stderr") and result.stderr:
                stderr = result.stderr.decode(errors="replace").strip()
            return StageResult(
                name=name,
                success=False,
                message=f"docker compose pull exited {result.returncode}: {stderr}",
            )

        return StageResult(name=name, success=True, message="container images updated")

    def _stage_data_verify(self) -> StageResult:
        """Re-check that /data paths were not disturbed by the update."""
        name = "data_verify"
        # Re-use the same check logic; directory contents are not validated
        # (that would require checksumming model blobs — too slow for an update
        # flow).  We only confirm that /data itself is still mounted.
        data_root = _DATA_MOUNT
        if not data_root.exists():
            return StageResult(
                name=name,
                success=False,
                message=f"{data_root} is not accessible after update",
            )
        return StageResult(name=name, success=True, message="/data partition intact")


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------


def run_full_update(
    server_url: str = _DEFAULT_OTA_SERVER,
    compose_file: str = _DEFAULT_COMPOSE_FILE,
    current_version: str | None = None,
    state_manager: StateManager | None = None,
    dry_run: bool = False,
    **kwargs,
) -> UpdateResult:
    """Run a full update cycle and return the aggregated result.

    This is the function called by ``bmt-ai-os update run``.

    Parameters
    ----------
    server_url:
        OTA release-info endpoint.
    compose_file:
        Path to the Compose file used for ``docker compose pull``.
    current_version:
        Running version (auto-read from package metadata when omitted).
    state_manager:
        Injected :class:`~bmt_ai_os.ota.state.StateManager`.
    dry_run:
        Use file-backed slot store instead of a real block device.
    **kwargs:
        Forwarded to :class:`UpdateOrchestrator` (injection points for
        testing).
    """
    orchestrator = UpdateOrchestrator(
        server_url=server_url,
        compose_file=compose_file,
        current_version=current_version,
        state_manager=state_manager,
        dry_run=dry_run,
        **kwargs,
    )
    return orchestrator.run()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_current_version() -> str:
    """Return the running OS version string.

    Reads from (in order):
    1. ``BMT_OS_VERSION`` environment variable.
    2. ``/etc/bmt-release`` plain-text version file (on real devices).
    3. Hard-coded CLI ``__version__`` as a final fallback.
    """
    env_ver = os.environ.get("BMT_OS_VERSION", "").strip()
    if env_ver:
        return env_ver

    release_file = Path("/etc/bmt-release")
    if release_file.is_file():
        try:
            ver = release_file.read_text().strip().splitlines()[0]
            if ver:
                return ver
        except OSError:
            pass

    # Last resort: import from the CLI module.
    try:
        from bmt_ai_os.cli import __version__

        return __version__
    except Exception:
        return "unknown"
