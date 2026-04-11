"""Unit tests for bmt_ai_os.controller.health."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests

from bmt_ai_os.controller.config import ControllerConfig, ServiceDef
from bmt_ai_os.controller.health import (
    CircuitBreaker,
    CircuitState,
    HealthChecker,
    HealthStatus,
)


def _make_config(**overrides) -> ControllerConfig:
    defaults = dict(
        circuit_breaker_threshold=3,
        circuit_breaker_reset=300,
        max_restarts=3,
        health_timeout=5,
        health_history_size=10,
    )
    defaults.update(overrides)
    return ControllerConfig(**defaults)


def _make_service(name="ollama", port=11434) -> ServiceDef:
    return ServiceDef(
        name=name,
        container_name=f"bmt-{name}",
        health_url=f"http://localhost:{port}/health",
        port=port,
    )


class TestCircuitBreaker:
    def test_initial_state_is_closed(self):
        cb = CircuitBreaker(threshold=3, reset_timeout=60)
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker(threshold=3, reset_timeout=60)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_stays_closed_below_threshold(self):
        cb = CircuitBreaker(threshold=3, reset_timeout=60)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_record_success_resets_to_closed(self):
        cb = CircuitBreaker(threshold=3, reset_timeout=60)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_allows_restart_when_closed(self):
        cb = CircuitBreaker(threshold=3, reset_timeout=60)
        assert cb.allow_restart() is True

    def test_blocks_restart_when_open(self):
        cb = CircuitBreaker(threshold=2, reset_timeout=3600)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_restart() is False

    def test_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker(threshold=2, reset_timeout=0)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        # With reset_timeout=0, elapsed >= 0 is always true
        result = cb.allow_restart()
        assert result is True
        assert cb.state == CircuitState.HALF_OPEN


class TestHealthChecker:
    def _make_checker(self, services=None, **cfg_overrides) -> HealthChecker:
        cfg = _make_config(**cfg_overrides)
        if services is not None:
            cfg.services = services
        return HealthChecker(cfg)

    def test_initialises_per_service_state(self):
        svc = _make_service("ollama")
        checker = self._make_checker(services=[svc])
        assert "ollama" in checker._history
        assert "ollama" in checker._circuit_breakers
        assert checker._consecutive_failures["ollama"] == 0

    def test_check_service_healthy(self):
        svc = _make_service()
        checker = self._make_checker(services=[svc])
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("bmt_ai_os.controller.health.requests.get", return_value=mock_resp):
            result = checker.check_service(svc)
        assert result.status == HealthStatus.HEALTHY
        assert result.response_time_ms >= 0
        assert checker._consecutive_failures[svc.name] == 0

    def test_check_service_unhealthy_non_200(self):
        svc = _make_service()
        checker = self._make_checker(services=[svc])
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        with patch("bmt_ai_os.controller.health.requests.get", return_value=mock_resp):
            result = checker.check_service(svc)
        assert result.status == HealthStatus.UNHEALTHY
        assert "503" in result.error
        assert checker._consecutive_failures[svc.name] == 1

    def test_check_service_unhealthy_on_connection_error(self):
        svc = _make_service()
        checker = self._make_checker(services=[svc])
        with patch(
            "bmt_ai_os.controller.health.requests.get",
            side_effect=requests.ConnectionError("refused"),
        ):
            result = checker.check_service(svc)
        assert result.status == HealthStatus.UNHEALTHY
        assert checker._consecutive_failures[svc.name] == 1

    def test_check_all_returns_one_result_per_service(self):
        svcs = [_make_service("ollama", 11434), _make_service("chromadb", 8000)]
        checker = self._make_checker(services=svcs)
        mock_resp = MagicMock(status_code=200)
        with patch("bmt_ai_os.controller.health.requests.get", return_value=mock_resp):
            results = checker.check_all()
        assert len(results) == 2
        names = {r.service for r in results}
        assert names == {"ollama", "chromadb"}

    def test_needs_restart_below_threshold(self):
        svc = _make_service()
        checker = self._make_checker(services=[svc], max_restarts=3)
        checker._consecutive_failures[svc.name] = 2
        assert checker.needs_restart(svc.name) is False

    def test_needs_restart_at_threshold(self):
        svc = _make_service()
        checker = self._make_checker(services=[svc], max_restarts=3)
        checker._consecutive_failures[svc.name] = 3
        assert checker.needs_restart(svc.name) is True

    def test_needs_restart_blocked_by_open_circuit(self):
        svc = _make_service()
        checker = self._make_checker(
            services=[svc], max_restarts=1, circuit_breaker_threshold=1, circuit_breaker_reset=3600
        )
        checker._consecutive_failures[svc.name] = 5
        checker._circuit_breakers[svc.name].record_failure()
        assert checker._circuit_breakers[svc.name].state == CircuitState.OPEN
        assert checker.needs_restart(svc.name) is False

    def test_reset_failures(self):
        svc = _make_service()
        checker = self._make_checker(services=[svc])
        checker._consecutive_failures[svc.name] = 10
        checker.reset_failures(svc.name)
        assert checker._consecutive_failures[svc.name] == 0

    def test_get_history(self):
        svc = _make_service()
        checker = self._make_checker(services=[svc])
        mock_resp = MagicMock(status_code=200)
        with patch("bmt_ai_os.controller.health.requests.get", return_value=mock_resp):
            checker.check_service(svc)
        history = checker.get_history(svc.name)
        assert len(history) == 1
        assert history[0].status == HealthStatus.HEALTHY

    def test_get_circuit_state(self):
        svc = _make_service()
        checker = self._make_checker(services=[svc])
        state = checker.get_circuit_state(svc.name)
        assert state == CircuitState.CLOSED
