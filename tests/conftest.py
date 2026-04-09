"""
tests/conftest.py — Root pytest configuration for BMT AI OS.

Provides shared settings, markers, and CLI options used across all test suites
(smoke tests, integration tests, and future unit tests).
"""

import os

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register custom CLI options for the test suite."""
    parser.addoption(
        "--qemu-host",
        default=os.environ.get("QEMU_HOST", "127.0.0.1"),
        help="Hostname or IP of the QEMU guest (default: 127.0.0.1)",
    )
    parser.addoption(
        "--ssh-port",
        default=int(os.environ.get("QEMU_SSH_PORT", "2222")),
        type=int,
        help="SSH port forwarded from QEMU guest (default: 2222)",
    )
    parser.addoption(
        "--boot-timeout",
        default=int(os.environ.get("BOOT_TIMEOUT", "120")),
        type=int,
        help="Seconds to wait for QEMU guest to boot (default: 120)",
    )
    parser.addoption(
        "--service-timeout",
        default=int(os.environ.get("SERVICE_TIMEOUT", "180")),
        type=int,
        help="Seconds to wait for services to become healthy (default: 180)",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers to avoid warnings."""
    config.addinivalue_line("markers", "integration: integration tests requiring QEMU")
    config.addinivalue_line("markers", "smoke: lightweight smoke tests (no QEMU)")
    config.addinivalue_line("markers", "slow: tests that take a long time to run")


@pytest.fixture(scope="session")
def qemu_host(request: pytest.FixtureRequest) -> str:
    """Return the QEMU guest hostname/IP."""
    return request.config.getoption("--qemu-host")


@pytest.fixture(scope="session")
def ssh_port(request: pytest.FixtureRequest) -> int:
    """Return the SSH port for the QEMU guest."""
    return request.config.getoption("--ssh-port")


@pytest.fixture(scope="session")
def boot_timeout(request: pytest.FixtureRequest) -> int:
    """Return the boot timeout in seconds."""
    return request.config.getoption("--boot-timeout")


@pytest.fixture(scope="session")
def service_timeout(request: pytest.FixtureRequest) -> int:
    """Return the service readiness timeout in seconds."""
    return request.config.getoption("--service-timeout")
