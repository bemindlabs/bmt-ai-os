"""System metrics collector for BMT AI OS controller."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Any


class MetricsCollector:
    """In-memory metrics collector for controller API requests and health checks.

    All public methods are thread-safe.  No external dependencies — stdlib only.
    """

    # Maximum number of health-check records kept per service.
    _HEALTH_HISTORY_MAXLEN = 10

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._start_time: float = time.monotonic()

        # Request tracking
        self._total_requests: int = 0
        self._requests_by_provider: dict[str, int] = defaultdict(int)
        self._latencies_ms: deque[float] = deque(maxlen=1000)
        self._error_count: int = 0

        # Health-check tracking: service -> deque of result dicts
        self._health_history: dict[str, deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=self._HEALTH_HISTORY_MAXLEN)
        )

    # ------------------------------------------------------------------
    # Recording helpers
    # ------------------------------------------------------------------

    def record_request(
        self,
        provider: str,
        method: str,
        latency_ms: float,
        success: bool,
    ) -> None:
        """Record a single API request.

        Args:
            provider: Provider name (e.g. ``"ollama"``).
            method: HTTP method or operation name (e.g. ``"POST"``).
            latency_ms: Round-trip latency in milliseconds.
            success: ``True`` if the request completed without error.
        """
        with self._lock:
            self._total_requests += 1
            self._requests_by_provider[provider] += 1
            self._latencies_ms.append(latency_ms)
            if not success:
                self._error_count += 1

    def record_health_check(
        self,
        service: str,
        healthy: bool,
        latency_ms: float,
    ) -> None:
        """Record the result of a single health check.

        Args:
            service: Service name (e.g. ``"ollama"``).
            healthy: ``True`` if the service responded as healthy.
            latency_ms: Time taken for the health check in milliseconds.
        """
        entry: dict[str, Any] = {
            "timestamp": time.time(),
            "healthy": healthy,
            "latency_ms": round(latency_ms, 1),
        }
        with self._lock:
            self._health_history[service].append(entry)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def get_summary(self) -> dict[str, Any]:
        """Return a JSON-serialisable snapshot of all collected metrics.

        Returns a dict with the following keys:

        - ``uptime_seconds`` — seconds since the collector was created.
        - ``total_requests`` — cumulative request count.
        - ``requests_by_provider`` — per-provider request counts.
        - ``avg_latency_ms`` — mean latency across the rolling window, or
          ``None`` when no requests have been recorded yet.
        - ``health_check_history`` — mapping of service name to the last 10
          health-check results (each a dict with ``timestamp``, ``healthy``,
          and ``latency_ms``).
        - ``error_count`` — cumulative failed-request count.
        - ``error_rate`` — fraction of requests that failed (0.0–1.0), or
          ``None`` when no requests have been recorded yet.
        """
        with self._lock:
            uptime = time.monotonic() - self._start_time

            latencies = list(self._latencies_ms)
            avg_latency = (sum(latencies) / len(latencies)) if latencies else None

            total = self._total_requests
            error_rate = (self._error_count / total) if total > 0 else None

            return {
                "uptime_seconds": round(uptime, 2),
                "total_requests": total,
                "requests_by_provider": dict(self._requests_by_provider),
                "avg_latency_ms": round(avg_latency, 2) if avg_latency is not None else None,
                "health_check_history": {
                    svc: list(history) for svc, history in self._health_history.items()
                },
                "error_count": self._error_count,
                "error_rate": round(error_rate, 4) if error_rate is not None else None,
            }


# ---------------------------------------------------------------------------
# Module-level singleton — shared across the controller process
# ---------------------------------------------------------------------------

_collector: MetricsCollector | None = None
_collector_lock = threading.Lock()


def get_collector() -> MetricsCollector:
    """Return the process-wide :class:`MetricsCollector` instance.

    Creates the instance on first call (lazy singleton).
    """
    global _collector
    if _collector is None:
        with _collector_lock:
            if _collector is None:
                _collector = MetricsCollector()
    return _collector
