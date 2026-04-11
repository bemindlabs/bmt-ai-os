"""Unit tests for bmt_ai_os.controller.health.

Covers:
- CircuitBreaker state transitions (CLOSED -> OPEN -> HALF_OPEN -> CLOSED)
- HealthChecker.check_service success and failure paths
- HealthChecker.check_all, needs_restart, reset_failures, get_history
- get_circuit_state helper
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from bmt_ai_os.controller.config import ControllerConfig, ServiceDef
from bmt_ai_os.controller.health import (
    CircuitBreaker,
    CircuitState,
    HealthChecker,
    HealthResult,
    HealthStatus,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def service() -> ServiceDef:
    return ServiceDef(
        name="ollama",
        container_name="bmt-ollama",
        health_url="http://localhost:11434/api/tags",
        port=11434,
    )


@pytest.fixture()
def config(service: ServiceDef) -> ControllerConfig:
    cfg = ControllerConfig()
    cfg.services = [service]
    cfg.health_timeout = 2
    cfg.circuit_breaker_threshold = 3
    cfg.circuit_breaker_reset = 60
    cfg.max_restarts = 3
    cfg.health_history_size = 5
    return cfg


@pytest.fixture()
def checker(config: ControllerConfig) -> HealthChecker:
    return HealthChecker(config)


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    def test_initial_state_is_closed(self):
        cb = CircuitBreaker(threshold=3, reset_timeout=60)
        assert cb.state == CircuitState.CLOSED

    def test_allow_restart_when_closed(self):
        cb = CircuitBreaker(threshold=3, reset_timeout=60)
        assert cb.allow_restart() is True

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker(threshold=3, reset_timeout=60)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_does_not_open_below_threshold(self):
        cb = CircuitBreaker(threshold=3, reset_timeout=60)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_open_blocks_restarts(self):
        cb = CircuitBreaker(threshold=1, reset_timeout=9999)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_restart() is False

    def test_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker(threshold=1, reset_timeout=0)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        # With reset_timeout=0 it transitions immediately
        assert cb.allow_restart() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_allows_restart(self):
        cb = CircuitBreaker(threshold=1, reset_timeout=0)
        cb.record_failure()
        cb.allow_restart()  # triggers OPEN -> HALF_OPEN
        assert cb.allow_restart() is True

    def test_success_resets_to_closed(self):
        cb = CircuitBreaker(threshold=3, reset_timeout=60)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_failure_count_increments(self):
        cb = CircuitBreaker(threshold=10, reset_timeout=60)
        cb.record_failure()
        cb.record_failure()
        assert cb.failure_count == 2


# ---------------------------------------------------------------------------
# HealthChecker.check_service
# ---------------------------------------------------------------------------


class TestCheckService:
    def test_healthy_when_http_200(self, checker: HealthChecker, service: ServiceDef) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("requests.get", return_value=mock_resp):
            result = checker.check_service(service)
        assert result.status == HealthStatus.HEALTHY
        assert result.service == "ollama"
        assert result.response_time_ms >= 0
        assert result.error == ""

    def test_unhealthy_when_http_500(self, checker: HealthChecker, service: ServiceDef) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch("requests.get", return_value=mock_resp):
            result = checker.check_service(service)
        assert result.status == HealthStatus.UNHEALTHY
        assert "500" in result.error

    def test_unhealthy_on_connection_error(
        self, checker: HealthChecker, service: ServiceDef
    ) -> None:
        with patch("requests.get", side_effect=requests.ConnectionError("refused")):
            result = checker.check_service(service)
        assert result.status == HealthStatus.UNHEALTHY
        assert "refused" in result.error

    def test_unhealthy_on_timeout(self, checker: HealthChecker, service: ServiceDef) -> None:
        with patch("requests.get", side_effect=requests.Timeout("timed out")):
            result = checker.check_service(service)
        assert result.status == HealthStatus.UNHEALTHY

    def test_result_added_to_history(self, checker: HealthChecker, service: ServiceDef) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("requests.get", return_value=mock_resp):
            checker.check_service(service)
        history = checker.get_history("ollama")
        assert len(history) == 1
        assert history[0].status == HealthStatus.HEALTHY

    def test_circuit_breaker_triggered_on_repeated_failures(
        self, checker: HealthChecker, service: ServiceDef
    ) -> None:
        with patch("requests.get", side_effect=requests.ConnectionError("refused")):
            for _ in range(checker.config.circuit_breaker_threshold):
                checker.check_service(service)
        state = checker.get_circuit_state("ollama")
        assert state == CircuitState.OPEN

    def test_success_resets_circuit_breaker(
        self, checker: HealthChecker, service: ServiceDef
    ) -> None:
        # Trip breaker
        with patch("requests.get", side_effect=requests.ConnectionError("refused")):
            for _ in range(checker.config.circuit_breaker_threshold):
                checker.check_service(service)
        # Recover
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # Force circuit back to closed by patching the breaker's state
        checker._circuit_breakers["ollama"].state = CircuitState.HALF_OPEN
        checker._circuit_breakers["ollama"].failure_count = 0
        with patch("requests.get", return_value=mock_resp):
            checker.check_service(service)
        assert checker.get_circuit_state("ollama") == CircuitState.CLOSED


# ---------------------------------------------------------------------------
# HealthChecker.check_all
# ---------------------------------------------------------------------------


class TestCheckAll:
    def test_check_all_returns_result_per_service(self) -> None:
        svc1 = ServiceDef("s1", "c1", "http://s1/health", 8001)
        svc2 = ServiceDef("s2", "c2", "http://s2/health", 8002)
        cfg = ControllerConfig()
        cfg.services = [svc1, svc2]
        checker = HealthChecker(cfg)

        mock_ok = MagicMock()
        mock_ok.status_code = 200
        with patch("requests.get", return_value=mock_ok):
            results = checker.check_all()
        assert len(results) == 2
        assert {r.service for r in results} == {"s1", "s2"}


# ---------------------------------------------------------------------------
# needs_restart / reset_failures
# ---------------------------------------------------------------------------


class TestNeedsRestart:
    def test_no_restart_below_threshold(self, checker: HealthChecker, service: ServiceDef) -> None:
        # 0 failures — should not need restart
        assert checker.needs_restart("ollama") is False

    def test_needs_restart_after_max_failures(
        self, checker: HealthChecker, service: ServiceDef
    ) -> None:
        checker._consecutive_failures["ollama"] = checker.config.max_restarts
        assert checker.needs_restart("ollama") is True

    def test_no_restart_when_circuit_open(
        self, checker: HealthChecker, service: ServiceDef
    ) -> None:
        checker._consecutive_failures["ollama"] = checker.config.max_restarts
        checker._circuit_breakers["ollama"].state = CircuitState.OPEN
        checker._circuit_breakers["ollama"].last_failure_time = time.time()
        assert checker.needs_restart("ollama") is False

    def test_reset_failures_clears_counter(self, checker: HealthChecker) -> None:
        checker._consecutive_failures["ollama"] = 5
        checker.reset_failures("ollama")
        assert checker._consecutive_failures["ollama"] == 0

    def test_needs_restart_unknown_service_false(self, checker: HealthChecker) -> None:
        assert checker.needs_restart("nonexistent") is False


# ---------------------------------------------------------------------------
# get_history / get_circuit_state
# ---------------------------------------------------------------------------


class TestGetHistoryAndState:
    def test_history_empty_initially(self, checker: HealthChecker) -> None:
        assert checker.get_history("ollama") == []

    def test_history_unknown_service_empty(self, checker: HealthChecker) -> None:
        assert checker.get_history("unknown") == []

    def test_circuit_state_default_closed(self, checker: HealthChecker) -> None:
        assert checker.get_circuit_state("ollama") == CircuitState.CLOSED

    def test_circuit_state_unknown_service_closed(self, checker: HealthChecker) -> None:
        assert checker.get_circuit_state("ghost") == CircuitState.CLOSED

    def test_history_capped_at_maxlen(self, checker: HealthChecker, service: ServiceDef) -> None:
        mock_ok = MagicMock()
        mock_ok.status_code = 200
        with patch("requests.get", return_value=mock_ok):
            # history_size is 5
            for _ in range(8):
                checker.check_service(service)
        assert len(checker.get_history("ollama")) == 5


# ---------------------------------------------------------------------------
# HealthResult dataclass
# ---------------------------------------------------------------------------


class TestHealthResult:
    def test_fields(self):
        r = HealthResult(service="svc", status=HealthStatus.HEALTHY, response_time_ms=12.5)
        assert r.service == "svc"
        assert r.status == HealthStatus.HEALTHY
        assert r.response_time_ms == 12.5
        assert r.error == ""

    def test_timestamp_auto_set(self):
        r = HealthResult(service="svc", status=HealthStatus.UNKNOWN)
        assert r.timestamp > 0
