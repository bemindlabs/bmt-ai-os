"""Lightweight per-provider request metrics."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class _ProviderStats:
    """Mutable stats for a single provider."""

    total_requests: int = 0
    successes: int = 0
    failures: int = 0
    total_latency_ms: float = 0.0
    last_used: float = 0.0  # monotonic timestamp

    @property
    def avg_latency_ms(self) -> float:
        if self.successes == 0:
            return 0.0
        return self.total_latency_ms / self.successes

    def to_dict(self) -> dict:
        return {
            "total_requests": self.total_requests,
            "successes": self.successes,
            "failures": self.failures,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "last_used": self.last_used,
        }


class ProviderMetrics:
    """Accumulates request metrics for every provider that has been called."""

    def __init__(self) -> None:
        self._stats: dict[str, _ProviderStats] = {}

    def _ensure(self, provider: str) -> _ProviderStats:
        if provider not in self._stats:
            self._stats[provider] = _ProviderStats()
        return self._stats[provider]

    def record_success(self, provider: str, latency_ms: float) -> None:
        s = self._ensure(provider)
        s.total_requests += 1
        s.successes += 1
        s.total_latency_ms += latency_ms
        s.last_used = time.monotonic()

    def record_failure(self, provider: str, latency_ms: float) -> None:
        s = self._ensure(provider)
        s.total_requests += 1
        s.failures += 1
        s.last_used = time.monotonic()

    def get_metrics(self) -> dict[str, dict]:
        """Return a snapshot of all provider metrics."""
        return {name: stats.to_dict() for name, stats in self._stats.items()}

    def reset(self, provider: str | None = None) -> None:
        """Reset metrics — for a single provider or all."""
        if provider:
            self._stats.pop(provider, None)
        else:
            self._stats.clear()
