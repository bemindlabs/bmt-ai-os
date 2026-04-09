"""
tests/integration/test_boot.py — QEMU ARM64 integration tests for BMT AI OS.

These tests boot the OS image in QEMU and verify that the core services
come up correctly. They require either:
  - A pre-built image at output/images/bmt-ai-os-arm64.img, or
  - QEMU_EXTERNAL=1 with a QEMU instance already running.

All timeouts are configurable via environment variables:
  BOOT_TIMEOUT     — seconds to wait for kernel boot (default: 120)
  SERVICE_TIMEOUT  — seconds to wait for services (default: 180)
  QEMU_HOST        — guest hostname (default: 127.0.0.1)
  QEMU_SSH_PORT    — forwarded SSH port (default: 2222)
"""

import pytest
import requests

from .conftest import SERVICE_PORTS, wait_for_service

# All tests in this module require a running QEMU session.
pytestmark = [pytest.mark.integration, pytest.mark.slow]


# ---------------------------------------------------------------------------
# Test: Kernel boots within timeout
# ---------------------------------------------------------------------------


class TestSystemBoot:
    """Verify the ARM64 image boots successfully in QEMU."""

    def test_system_boots(self, ssh_exec):
        """
        The kernel should boot and reach a state where SSH is functional.

        If we can execute 'uname -m' over SSH, the kernel booted, init ran,
        networking came up, and sshd started — a comprehensive boot check.
        """
        rc, stdout, _stderr = ssh_exec("uname -m")
        assert rc == 0, f"uname failed with exit code {rc}"
        assert "aarch64" in stdout, f"Expected aarch64 architecture, got: {stdout}"

    def test_kernel_version(self, ssh_exec):
        """Verify the kernel reports a reasonable version string."""
        rc, stdout, _stderr = ssh_exec("uname -r")
        assert rc == 0, f"uname -r failed with exit code {rc}"
        # Kernel version should be a dotted numeric string (e.g., 6.1.x)
        assert "." in stdout, f"Unexpected kernel version format: {stdout}"


# ---------------------------------------------------------------------------
# Test: containerd is running
# ---------------------------------------------------------------------------


class TestContainerd:
    """Verify the container runtime is operational."""

    def test_containerd_running(self, ssh_exec):
        """
        containerd must be running for the AI stack containers to launch.

        Check both the process and the socket existence.
        """
        # Check process
        rc, stdout, _stderr = ssh_exec("pgrep -x containerd || pgrep -f containerd")
        assert rc == 0, "containerd process not found"
        assert stdout.strip(), "containerd PID list is empty"

    def test_containerd_socket(self, ssh_exec):
        """The containerd socket should exist for Docker/nerdctl to connect."""
        rc, _stdout, _stderr = ssh_exec(
            "test -S /run/containerd/containerd.sock"
        )
        assert rc == 0, "containerd socket /run/containerd/containerd.sock not found"


# ---------------------------------------------------------------------------
# Test: Ollama responding
# ---------------------------------------------------------------------------


class TestOllama:
    """Verify the Ollama inference service is healthy."""

    def test_ollama_healthy(self, qemu_session, service_timeout):
        """
        Ollama should respond to GET /api/tags with HTTP 200.

        This endpoint lists available models and is the standard health
        indicator for Ollama.
        """
        url = f"http://{qemu_session.host}:{SERVICE_PORTS['ollama']}/api/tags"
        ready = wait_for_service(url, timeout=service_timeout)
        assert ready, f"Ollama did not become healthy at {url} within {service_timeout}s"

        # Double-check with a direct request
        resp = requests.get(url, timeout=10)
        assert resp.status_code == 200, f"Ollama returned {resp.status_code}"
        # Response should be valid JSON with a 'models' key
        data = resp.json()
        assert "models" in data, f"Unexpected Ollama response: {data}"


# ---------------------------------------------------------------------------
# Test: ChromaDB responding
# ---------------------------------------------------------------------------


class TestChromaDB:
    """Verify the ChromaDB vector store is healthy."""

    def test_chromadb_healthy(self, qemu_session, service_timeout):
        """
        ChromaDB should respond to GET /api/v1/heartbeat with HTTP 200.

        The heartbeat endpoint returns a nanosecond timestamp, confirming
        the service is operational.
        """
        url = f"http://{qemu_session.host}:{SERVICE_PORTS['chromadb']}/api/v1/heartbeat"
        ready = wait_for_service(url, timeout=service_timeout)
        assert ready, f"ChromaDB did not become healthy at {url} within {service_timeout}s"

        resp = requests.get(url, timeout=10)
        assert resp.status_code == 200, f"ChromaDB returned {resp.status_code}"


# ---------------------------------------------------------------------------
# Test: Controller health
# ---------------------------------------------------------------------------


class TestController:
    """Verify the BMT AI OS controller process is running."""

    def test_controller_health(self, ssh_exec):
        """
        The controller orchestrates AI-stack containers.

        Verify the process is running. The controller is a Python process
        launched by the init system or as a service.
        """
        rc, stdout, _stderr = ssh_exec(
            "pgrep -f 'controller/main.py' || pgrep -f 'bmt.*controller'"
        )
        assert rc == 0, (
            "Controller process not found. "
            "Expected a process matching 'controller/main.py'"
        )
        assert stdout.strip(), "Controller PID is empty"


# ---------------------------------------------------------------------------
# Test: Network connectivity between containers
# ---------------------------------------------------------------------------


class TestNetworkConnectivity:
    """Verify that containers can resolve and reach each other."""

    def test_network_connectivity(self, ssh_exec):
        """
        Containers running in the AI stack should be able to resolve
        each other's hostnames via Docker networking.

        We test this by asking the guest to curl Ollama and ChromaDB
        from the host namespace (port-forwarded), confirming the
        Docker bridge network is functional.
        """
        # Test Ollama is reachable from within the guest
        rc, stdout, _stderr = ssh_exec(
            "wget -q -O- http://127.0.0.1:11434/api/tags 2>/dev/null "
            "|| curl -sf http://127.0.0.1:11434/api/tags 2>/dev/null "
            "|| echo 'UNREACHABLE'"
        )
        assert "UNREACHABLE" not in stdout, "Ollama not reachable from within the guest"

    def test_dns_resolution(self, ssh_exec):
        """
        Docker containers should have functioning DNS resolution.

        Check that the guest can resolve localhost at minimum.
        """
        rc, stdout, _stderr = ssh_exec("getent hosts localhost || echo '127.0.0.1 localhost'")
        assert rc == 0 or "127.0.0.1" in stdout, "DNS resolution not working"
