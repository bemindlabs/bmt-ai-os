"""Health checking with circuit-breaker pattern for AI stack services."""

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

import requests

from .config import ControllerConfig, ServiceDef

logger = logging.getLogger("bmt-controller.health")


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class CircuitState(str, Enum):
    CLOSED = "closed"  # Normal operation, restarts allowed
    OPEN = "open"  # Too many failures, restarts blocked
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class HealthResult:
    """Single health check result."""

    service: str
    status: HealthStatus
    response_time_ms: float = 0.0
    error: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class CircuitBreaker:
    """Circuit breaker to stop restarting a persistently failing service."""

    threshold: int
    reset_timeout: int
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: float = 0.0

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.threshold:
            self.state = CircuitState.OPEN
            logger.warning("Circuit breaker OPEN after %d failures", self.failure_count)

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = CircuitState.CLOSED

    def allow_restart(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            elapsed = time.time() - self.last_failure_time
            if elapsed >= self.reset_timeout:
                self.state = CircuitState.HALF_OPEN
                logger.info("Circuit breaker HALF_OPEN, allowing test restart")
                return True
            return False
        # HALF_OPEN: allow one restart attempt
        return True


class HealthChecker:
    """Per-service health checking with history and circuit breakers."""

    def __init__(self, config: ControllerConfig) -> None:
        self.config = config
        self._history: dict[str, deque[HealthResult]] = {}
        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        self._consecutive_failures: dict[str, int] = {}

        for svc in config.services:
            self._history[svc.name] = deque(maxlen=config.health_history_size)
            self._circuit_breakers[svc.name] = CircuitBreaker(
                threshold=config.circuit_breaker_threshold,
                reset_timeout=config.circuit_breaker_reset,
            )
            self._consecutive_failures[svc.name] = 0

    def check_service(self, service: ServiceDef) -> HealthResult:
        """Run an HTTP health check against a single service."""
        start = time.time()
        try:
            resp = requests.get(service.health_url, timeout=self.config.health_timeout)
            elapsed_ms = (time.time() - start) * 1000
            if resp.status_code == 200:
                result = HealthResult(
                    service=service.name,
                    status=HealthStatus.HEALTHY,
                    response_time_ms=elapsed_ms,
                )
                self._consecutive_failures[service.name] = 0
                self._circuit_breakers[service.name].record_success()
            else:
                result = HealthResult(
                    service=service.name,
                    status=HealthStatus.UNHEALTHY,
                    response_time_ms=elapsed_ms,
                    error=f"HTTP {resp.status_code}",
                )
                self._consecutive_failures[service.name] += 1
                self._circuit_breakers[service.name].record_failure()
        except requests.RequestException as exc:
            elapsed_ms = (time.time() - start) * 1000
            result = HealthResult(
                service=service.name,
                status=HealthStatus.UNHEALTHY,
                response_time_ms=elapsed_ms,
                error=str(exc),
            )
            self._consecutive_failures[service.name] += 1
            self._circuit_breakers[service.name].record_failure()

        self._history[service.name].append(result)
        return result

    def check_all(self) -> list[HealthResult]:
        """Check all configured services."""
        return [self.check_service(svc) for svc in self.config.services]

    def needs_restart(self, service_name: str) -> bool:
        """True if service has exceeded max consecutive failures and circuit allows restart."""
        failures = self._consecutive_failures.get(service_name, 0)
        if failures < self.config.max_restarts:
            return False
        cb = self._circuit_breakers.get(service_name)
        if cb and not cb.allow_restart():
            logger.warning(
                "Service %s needs restart but circuit breaker is OPEN",
                service_name,
            )
            return False
        return True

    def reset_failures(self, service_name: str) -> None:
        """Reset the consecutive failure counter after a restart."""
        self._consecutive_failures[service_name] = 0

    def get_history(self, service_name: str) -> list[HealthResult]:
        """Return recent health check results for a service."""
        return list(self._history.get(service_name, []))

    def get_circuit_state(self, service_name: str) -> CircuitState:
        cb = self._circuit_breakers.get(service_name)
        return cb.state if cb else CircuitState.CLOSED
