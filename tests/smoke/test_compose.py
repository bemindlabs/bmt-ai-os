"""
tests/smoke/test_compose.py — Lightweight smoke tests for Docker Compose config.

These tests validate the AI stack's docker-compose.yml without requiring
QEMU, Docker daemon, or any running services. They parse the YAML directly
and verify structural correctness.

Run with:
    pytest tests/smoke/ -v
"""

import subprocess
from pathlib import Path

import pytest
import yaml

# All tests in this module are smoke tests — fast, no infrastructure needed.
pytestmark = pytest.mark.smoke

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = PROJECT_ROOT / "bmt_ai_os" / "ai-stack" / "docker-compose.yml"

# Services that MUST be present in the AI stack
REQUIRED_SERVICES = {"ollama", "chromadb"}

# Ports that each required service must expose
EXPECTED_PORTS = {
    "ollama": 11434,
    "chromadb": 8000,
}


# ---------------------------------------------------------------------------
# Fixture: parsed compose config
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def compose_config() -> dict:
    """Load and return the parsed docker-compose.yml."""
    assert COMPOSE_FILE.is_file(), f"Compose file not found: {COMPOSE_FILE}"
    with open(COMPOSE_FILE) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Test: Compose file validates with docker compose
# ---------------------------------------------------------------------------


class TestComposeValidation:
    """Validate the Docker Compose configuration file."""

    def test_compose_config_valid(self):
        """
        'docker compose config' should succeed without errors.

        This catches syntax errors, invalid service definitions, and
        unsupported Compose features. Skipped if docker is not installed
        (e.g., in minimal CI environments without Docker).
        """
        result = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "config", "--quiet"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 127:
            pytest.skip("docker CLI not available")
        assert result.returncode == 0, f"docker compose config failed:\n{result.stderr}"

    def test_compose_yaml_parseable(self, compose_config):
        """The compose file should parse as valid YAML with a services key."""
        assert "services" in compose_config, "Missing top-level 'services' key"
        assert isinstance(compose_config["services"], dict), "services should be a dict"


# ---------------------------------------------------------------------------
# Test: Required services are defined
# ---------------------------------------------------------------------------


class TestServiceDefinitions:
    """Verify that all required AI stack services are declared."""

    def test_compose_services_defined(self, compose_config):
        """
        Both Ollama and ChromaDB must be defined as services.

        These are the two core AI stack components required for inference
        and vector search respectively.
        """
        services = set(compose_config["services"].keys())
        missing = REQUIRED_SERVICES - services
        assert not missing, f"Missing required services: {missing}"

    @pytest.mark.parametrize("service_name", sorted(REQUIRED_SERVICES))
    def test_service_has_image(self, compose_config, service_name):
        """Each required service must specify a container image."""
        service = compose_config["services"][service_name]
        assert "image" in service, f"Service '{service_name}' has no image defined"
        assert service["image"], f"Service '{service_name}' has empty image"

    @pytest.mark.parametrize(
        "service_name,expected_port",
        sorted(EXPECTED_PORTS.items()),
    )
    def test_service_port_exposed(self, compose_config, service_name, expected_port):
        """Each service must expose its expected port."""
        service = compose_config["services"][service_name]
        ports = service.get("ports", [])
        # Ports can be strings like "11434:11434" or ints
        port_strings = [str(p) for p in ports]
        found = any(str(expected_port) in ps for ps in port_strings)
        assert found, (
            f"Service '{service_name}' does not expose port {expected_port}. Ports found: {ports}"
        )


# ---------------------------------------------------------------------------
# Test: Healthchecks are defined
# ---------------------------------------------------------------------------


class TestHealthchecks:
    """Verify that services have healthcheck configurations."""

    @pytest.mark.parametrize("service_name", sorted(REQUIRED_SERVICES))
    def test_healthchecks_defined(self, compose_config, service_name):
        """
        Each core service should have a healthcheck so Docker can
        report readiness and the controller can monitor health.
        """
        service = compose_config["services"][service_name]
        assert "healthcheck" in service, (
            f"Service '{service_name}' is missing a healthcheck definition"
        )
        hc = service["healthcheck"]
        assert "test" in hc, f"Service '{service_name}' healthcheck has no test command"

    @pytest.mark.parametrize("service_name", sorted(REQUIRED_SERVICES))
    def test_healthcheck_has_interval(self, compose_config, service_name):
        """Healthchecks should define a check interval."""
        hc = compose_config["services"][service_name].get("healthcheck", {})
        assert "interval" in hc, f"Service '{service_name}' healthcheck missing 'interval'"


# ---------------------------------------------------------------------------
# Test: Volumes are declared
# ---------------------------------------------------------------------------


class TestVolumes:
    """Verify that persistent volumes are declared for stateful services."""

    def test_volumes_defined(self, compose_config):
        """
        The compose file should declare top-level volumes for persistent
        data (model weights, vector indices, etc.).
        """
        assert "volumes" in compose_config, "No top-level 'volumes' key found"
        volumes = compose_config["volumes"]
        assert len(volumes) > 0, "No volumes declared"

    def test_ollama_has_volume(self, compose_config):
        """Ollama should mount a volume for model storage."""
        service = compose_config["services"].get("ollama", {})
        volumes = service.get("volumes", [])
        assert len(volumes) > 0, "Ollama has no volumes — model data will be lost"

    def test_chromadb_has_volume(self, compose_config):
        """ChromaDB should mount a volume for vector index persistence."""
        service = compose_config["services"].get("chromadb", {})
        volumes = service.get("volumes", [])
        assert len(volumes) > 0, "ChromaDB has no volumes — index data will be lost"


# ---------------------------------------------------------------------------
# Test: Restart policy
# ---------------------------------------------------------------------------


class TestRestartPolicy:
    """Verify services have appropriate restart policies."""

    @pytest.mark.parametrize("service_name", sorted(REQUIRED_SERVICES))
    def test_restart_policy(self, compose_config, service_name):
        """
        Core services should have a restart policy so they recover
        from crashes without manual intervention.
        """
        service = compose_config["services"][service_name]
        restart = service.get("restart", "no")
        valid_policies = {"always", "unless-stopped", "on-failure"}
        assert restart in valid_policies, (
            f"Service '{service_name}' has restart='{restart}', expected one of {valid_policies}"
        )
