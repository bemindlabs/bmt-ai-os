"""
tests/integration/conftest.py — Shared fixtures for QEMU-based integration tests.

Provides session-scoped fixtures to:
  - Launch and manage a QEMU ARM64 virtual machine
  - Establish SSH connections to the QEMU guest
  - Poll HTTP endpoints until services are ready

All timeouts are configurable via environment variables or pytest CLI options
(see tests/conftest.py for the option definitions).
"""

import logging
import os
import signal
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator, Optional

import paramiko
import pytest
import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
QEMU_BOOT_SCRIPT = PROJECT_ROOT / "scripts" / "ci-qemu-boot.sh"
DEFAULT_IMAGE = PROJECT_ROOT / "output" / "images" / "bmt_ai_os-arm64.img"

# ---------------------------------------------------------------------------
# Port map — forwarded from QEMU guest to localhost
# ---------------------------------------------------------------------------

SERVICE_PORTS = {
    "ssh": 2222,
    "ollama": 11434,
    "chromadb": 8000,
    "dashboard": 9090,
    "openai_proxy": 8080,
    "jupyter": 8888,
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class QEMUSession:
    """Tracks a running QEMU process and its connection parameters."""

    process: Optional[subprocess.Popen] = None
    host: str = "127.0.0.1"
    ssh_port: int = 2222
    pid: int = 0
    serial_log: str = ""
    ports: dict = field(default_factory=lambda: dict(SERVICE_PORTS))


# ---------------------------------------------------------------------------
# Helper: wait for a TCP port to accept connections
# ---------------------------------------------------------------------------


def wait_for_port(
    host: str,
    port: int,
    timeout: int = 60,
    interval: float = 2.0,
) -> bool:
    """
    Poll a TCP port until it accepts connections or timeout expires.

    Returns True if the port became reachable, False on timeout.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=3):
                return True
        except OSError:
            time.sleep(interval)
    return False


# ---------------------------------------------------------------------------
# Helper: wait for an HTTP endpoint to return a successful status
# ---------------------------------------------------------------------------


def wait_for_service(
    url: str,
    timeout: int = 120,
    interval: float = 3.0,
    expected_status: int = 200,
) -> bool:
    """
    Poll an HTTP endpoint until it returns the expected status code.

    Returns True if the service responded in time, False on timeout.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code == expected_status:
                return True
        except requests.ConnectionError:
            pass
        except requests.Timeout:
            pass
        time.sleep(interval)
    return False


# ---------------------------------------------------------------------------
# Fixtures: configurable parameters (env-var backed, graceful defaults)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def qemu_host() -> str:
    """
    Hostname / IP where the QEMU guest is reachable.

    Override with the QEMU_HOST environment variable (default: 127.0.0.1).
    """
    return os.environ.get("QEMU_HOST", "127.0.0.1")


@pytest.fixture(scope="session")
def ssh_port() -> int:
    """
    Host-side TCP port forwarded to the QEMU guest SSH daemon.

    Override with the QEMU_SSH_PORT environment variable (default: 2222).
    """
    raw = os.environ.get("QEMU_SSH_PORT", "2222")
    try:
        return int(raw)
    except ValueError:
        pytest.skip(f"QEMU_SSH_PORT={raw!r} is not a valid integer")


@pytest.fixture(scope="session")
def boot_timeout() -> int:
    """
    Seconds to wait for the QEMU guest to become reachable via SSH.

    Override with the BOOT_TIMEOUT environment variable (default: 120).
    """
    raw = os.environ.get("BOOT_TIMEOUT", "120")
    try:
        return int(raw)
    except ValueError:
        pytest.skip(f"BOOT_TIMEOUT={raw!r} is not a valid integer")


@pytest.fixture(scope="session")
def service_timeout() -> int:
    """
    Seconds to wait for individual services (Ollama, ChromaDB, etc.) to
    respond after the guest has booted.

    Override with the SERVICE_TIMEOUT environment variable (default: 180).
    """
    raw = os.environ.get("SERVICE_TIMEOUT", "180")
    try:
        return int(raw)
    except ValueError:
        pytest.skip(f"SERVICE_TIMEOUT={raw!r} is not a valid integer")


# ---------------------------------------------------------------------------
# Fixture: QEMU session (session-scoped — one VM per test run)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def qemu_session(
    qemu_host: str,
    ssh_port: int,
    boot_timeout: int,
) -> Generator[QEMUSession, None, None]:
    """
    Start a QEMU ARM64 VM for integration testing.

    If the environment variable QEMU_EXTERNAL=1 is set, the fixture assumes
    a QEMU instance is already running externally (e.g., started by the CI
    script) and skips launching its own. This is useful in CI where the boot
    script runs as a separate step.

    The fixture waits for the SSH port to become reachable before yielding,
    ensuring the guest has booted far enough to accept connections.
    """
    session = QEMUSession(host=qemu_host, ssh_port=ssh_port)

    # ------------------------------------------------------------------
    # External QEMU mode: skip launch, just wait for SSH
    # ------------------------------------------------------------------
    if os.environ.get("QEMU_EXTERNAL", "0") == "1":
        logger.info("QEMU_EXTERNAL=1 — assuming QEMU is already running")
        if not wait_for_port(session.host, session.ssh_port, timeout=boot_timeout):
            pytest.fail(
                f"External QEMU not reachable on {session.host}:{session.ssh_port} "
                f"within {boot_timeout}s"
            )
        yield session
        return

    # ------------------------------------------------------------------
    # Managed QEMU mode: launch via ci-qemu-boot.sh
    # ------------------------------------------------------------------
    image_path = os.environ.get("QEMU_IMAGE", str(DEFAULT_IMAGE))
    if not Path(image_path).is_file():
        pytest.skip(f"QEMU image not found at {image_path} — skipping integration tests")

    if not QEMU_BOOT_SCRIPT.is_file():
        pytest.skip(f"Boot script not found at {QEMU_BOOT_SCRIPT}")

    serial_log = f"/tmp/bmt-qemu-integration-{os.getpid()}.log"
    session.serial_log = serial_log

    logger.info("Starting QEMU via %s (image: %s)", QEMU_BOOT_SCRIPT, image_path)

    proc = subprocess.Popen(
        [
            str(QEMU_BOOT_SCRIPT),
            "--image",
            image_path,
            "--timeout",
            str(boot_timeout),
            "--serial-log",
            serial_log,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,  # Create new process group for clean teardown
    )
    session.process = proc
    session.pid = proc.pid

    # Wait for SSH port to indicate guest has booted
    logger.info("Waiting up to %ds for SSH on %s:%d", boot_timeout, session.host, session.ssh_port)
    if not wait_for_port(session.host, session.ssh_port, timeout=boot_timeout):
        # Capture whatever output QEMU produced for debugging
        stdout, _ = proc.communicate(timeout=5)
        output_snippet = stdout.decode(errors="replace")[-2000:] if stdout else "(no output)"
        pytest.fail(
            f"QEMU guest SSH not reachable within {boot_timeout}s.\n"
            f"QEMU output (last 2000 chars):\n{output_snippet}"
        )

    logger.info("QEMU guest is up (PID %d)", session.pid)
    yield session

    # ------------------------------------------------------------------
    # Teardown: terminate QEMU process group
    # ------------------------------------------------------------------
    logger.info("Tearing down QEMU (PID %d)", session.pid)
    if proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=10)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.wait(timeout=5)

    # Clean up serial log
    if os.path.isfile(serial_log):
        os.unlink(serial_log)


# ---------------------------------------------------------------------------
# Fixture: SSH connection to the QEMU guest
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def ssh_connection(qemu_session: QEMUSession) -> Generator[paramiko.SSHClient, None, None]:
    """
    Establish an SSH connection to the QEMU guest.

    Uses root with no password by default (standard for Buildroot images).
    Override credentials via QEMU_SSH_USER and QEMU_SSH_PASSWORD env vars.
    """
    ssh_user = os.environ.get("QEMU_SSH_USER", "root")
    ssh_password = os.environ.get("QEMU_SSH_PASSWORD", "")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    max_retries = 5
    for attempt in range(1, max_retries + 1):
        try:
            connect_kwargs = {
                "hostname": qemu_session.host,
                "port": qemu_session.ssh_port,
                "username": ssh_user,
                "timeout": 10,
                "allow_agent": False,
                "look_for_keys": False,
            }
            if ssh_password:
                connect_kwargs["password"] = ssh_password
            else:
                # Buildroot root with empty password
                connect_kwargs["password"] = ""

            client.connect(**connect_kwargs)
            logger.info(
                "SSH connected to %s:%d (attempt %d)",
                qemu_session.host,
                qemu_session.ssh_port,
                attempt,
            )
            break
        except (paramiko.ssh_exception.SSHException, OSError) as exc:
            if attempt == max_retries:
                pytest.fail(f"SSH connection failed after {max_retries} attempts: {exc}")
            time.sleep(3)

    yield client
    client.close()


# ---------------------------------------------------------------------------
# Helper fixture: run a command over SSH and return (exit_code, stdout, stderr)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def ssh_exec(ssh_connection: paramiko.SSHClient):
    """
    Return a callable that executes a command on the QEMU guest via SSH.

    Usage in tests:
        def test_something(ssh_exec):
            rc, stdout, stderr = ssh_exec("uname -m")
            assert rc == 0
            assert "aarch64" in stdout
    """

    def _exec(command: str, timeout: int = 30) -> tuple[int, str, str]:
        stdin, stdout, stderr = ssh_connection.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        return (
            exit_code,
            stdout.read().decode(errors="replace").strip(),
            stderr.read().decode(errors="replace").strip(),
        )

    return _exec
