"""
BMT AI OS — Network integration tests (BMTOS-20).

These tests verify service discovery, container DNS resolution, host-port
access, network isolation, and resilience across container restarts.

Requirements:
    - Docker daemon running
    - docker-compose available
    - AI stack containers (bmt-ollama, bmt-chromadb) running on bmt-ai-net

Run:
    python -m pytest tests/integration/test_networking.py -v
"""

import json
import subprocess
import time

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
NETWORK_NAME = "bmt-ai-net"
SUBNET = "172.20.0.0/16"

SERVICES = {
    "ollama": {"container": "bmt-ollama", "port": 11434},
    "chromadb": {"container": "bmt-chromadb", "port": 8000},
}

COMPOSE_FILE = "bmt-ai-os/ai-stack/docker-compose.yml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a docker CLI command and return the result."""
    return subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        check=check,
        timeout=30,
    )


def network_exists(name: str = NETWORK_NAME) -> bool:
    result = docker("network", "inspect", name, check=False)
    return result.returncode == 0


def container_running(name: str) -> bool:
    result = docker(
        "inspect", "--format", "{{.State.Running}}", name, check=False
    )
    return result.stdout.strip() == "true"


def exec_in_container(container: str, cmd: list[str]) -> subprocess.CompletedProcess:
    """Execute a command inside a running container."""
    return docker("exec", container, *cmd, check=False)


def wait_for_container(container: str, timeout: int = 30) -> None:
    """Wait until a container is running and healthy."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if container_running(container):
            return
        time.sleep(1)
    pytest.skip(f"Container {container} not running (timeout={timeout}s)")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module", autouse=True)
def require_docker():
    """Skip the entire module if Docker is not available."""
    result = subprocess.run(
        ["docker", "info"], capture_output=True, text=True, timeout=10
    )
    if result.returncode != 0:
        pytest.skip("Docker daemon is not available")


@pytest.fixture(scope="module")
def require_network(require_docker):
    """Ensure the bmt-ai-net network exists."""
    if not network_exists():
        pytest.skip(f"Network '{NETWORK_NAME}' does not exist")


@pytest.fixture(scope="module")
def require_services(require_network):
    """Ensure at least the core services are running."""
    for svc in SERVICES.values():
        if not container_running(svc["container"]):
            pytest.skip(
                f"Container {svc['container']} is not running — "
                "start the AI stack first"
            )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestContainerDNSResolution:
    """Containers must resolve each other by service name."""

    @pytest.mark.parametrize("target", list(SERVICES.keys()))
    def test_container_dns_resolution(self, require_services, target):
        """Each service name must resolve from within another container."""
        svc = SERVICES[target]
        # Pick a *different* container to resolve from
        probe = next(
            s["container"]
            for name, s in SERVICES.items()
            if name != target
        )

        result = exec_in_container(
            probe,
            ["sh", "-c", f"getent hosts {target} 2>/dev/null || nslookup {target} 2>/dev/null"],
        )
        assert result.returncode == 0, (
            f"DNS resolution of '{target}' failed inside {probe}: "
            f"{result.stderr}"
        )


class TestHostPortAccess:
    """Host must reach services via localhost ports."""

    @pytest.mark.parametrize(
        "port",
        [svc["port"] for svc in SERVICES.values()],
        ids=[f"localhost:{svc['port']}" for svc in SERVICES.values()],
    )
    def test_host_port_access(self, require_services, port):
        """localhost:<port> must be reachable from the host."""
        result = subprocess.run(
            ["curl", "-sf", "--connect-timeout", "3", f"http://localhost:{port}/"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # A non-zero exit code means the port is not reachable.
        # We accept any HTTP response (even 4xx) — the point is connectivity.
        # curl returns 0 for HTTP 2xx/3xx; for others we also check nc.
        if result.returncode != 0:
            nc_result = subprocess.run(
                ["nc", "-z", "-w", "3", "localhost", str(port)],
                capture_output=True,
                timeout=10,
            )
            assert nc_result.returncode == 0, (
                f"Port {port} not reachable on localhost"
            )


class TestNetworkIsolation:
    """AI stack must be on an isolated bridge network."""

    def test_network_isolation(self, require_network):
        """bmt-ai-net must be a bridge network with the expected subnet."""
        result = docker("network", "inspect", NETWORK_NAME)
        info = json.loads(result.stdout)
        assert len(info) == 1

        net = info[0]
        assert net["Driver"] == "bridge"
        assert any(
            cfg["Subnet"] == SUBNET for cfg in net["IPAM"]["Config"]
        ), f"Expected subnet {SUBNET} not found in network config"

    def test_containers_on_correct_network(self, require_services):
        """All AI-stack containers must be attached to bmt-ai-net."""
        result = docker("network", "inspect", NETWORK_NAME)
        info = json.loads(result.stdout)
        connected = {
            c["Name"] for c in info[0].get("Containers", {}).values()
        }
        for svc in SERVICES.values():
            assert svc["container"] in connected, (
                f"{svc['container']} not connected to {NETWORK_NAME}"
            )


class TestNetworkSurvivesRestart:
    """DNS and connectivity must survive container restarts."""

    def test_network_survives_restart(self, require_services):
        """Restart a container and verify DNS + port still work."""
        target_name = "ollama"
        target = SERVICES[target_name]
        container = target["container"]

        # Restart the container
        docker("restart", container)
        wait_for_container(container, timeout=60)

        # Small grace period for DNS propagation
        time.sleep(2)

        # DNS resolution must still work
        probe = next(
            s["container"]
            for name, s in SERVICES.items()
            if name != target_name
        )
        result = exec_in_container(
            probe,
            ["sh", "-c", f"getent hosts {target_name} 2>/dev/null || nslookup {target_name} 2>/dev/null"],
        )
        assert result.returncode == 0, (
            f"DNS resolution of '{target_name}' failed after restart"
        )

        # Host port must still be reachable
        deadline = time.time() + 15
        reachable = False
        while time.time() < deadline:
            nc = subprocess.run(
                ["nc", "-z", "-w", "2", "localhost", str(target["port"])],
                capture_output=True,
                timeout=10,
            )
            if nc.returncode == 0:
                reachable = True
                break
            time.sleep(1)
        assert reachable, (
            f"Port {target['port']} not reachable after restarting {container}"
        )


class TestExternalDNS:
    """Containers must be able to resolve external domain names."""

    @pytest.mark.parametrize("container", [s["container"] for s in SERVICES.values()])
    def test_external_dns(self, require_services, container):
        """Containers should resolve public hostnames via Docker DNS."""
        result = exec_in_container(
            container,
            ["sh", "-c", "getent hosts cloudflare.com 2>/dev/null || nslookup cloudflare.com 2>/dev/null"],
        )
        assert result.returncode == 0, (
            f"External DNS resolution failed inside {container}: "
            f"{result.stderr}"
        )
