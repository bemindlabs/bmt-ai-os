"""Per-provider circuit breaker for the fallback router.

States
------
CLOSED   — normal operation, requests flow through.
OPEN     — provider is unhealthy; requests are rejected immediately.
HALF_OPEN — cooldown expired; allow a limited number of test requests.
"""

from __future__ import annotations

import asyncio
import enum
import time
from dataclasses import dataclass, field


class CircuitState(enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class ProviderCircuitBreaker:
    """Circuit breaker that tracks failures for a single provider.

    Thread-safe via an asyncio lock — safe for concurrent coroutine access
    within a single event loop.
    """

    failure_threshold: int = 3
    cooldown_seconds: float = 60.0
    half_open_max_requests: int = 1

    # --- internal state (not meant for external construction) ---
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _half_open_attempts: int = field(default=0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    @property
    def state(self) -> CircuitState:
        """Return the current circuit state, transitioning OPEN -> HALF_OPEN
        if the cooldown has elapsed."""
        if self._state is CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time >= self.cooldown_seconds:
                self._state = CircuitState.HALF_OPEN
                self._half_open_attempts = 0
        return self._state

    def is_available(self) -> bool:
        """Return True if the provider should be tried.

        * CLOSED  -> always available
        * OPEN    -> available only after cooldown (transitions to HALF_OPEN)
        * HALF_OPEN -> available until half_open_max_requests exhausted
        """
        current = self.state  # triggers OPEN -> HALF_OPEN if cooldown passed
        if current is CircuitState.CLOSED:
            return True
        if current is CircuitState.HALF_OPEN:
            return self._half_open_attempts < self.half_open_max_requests
        # OPEN
        return False

    async def record_success(self) -> None:
        """Record a successful request — resets the breaker to CLOSED."""
        async with self._lock:
            self._failure_count = 0
            self._half_open_attempts = 0
            self._state = CircuitState.CLOSED

    async def record_failure(self) -> None:
        """Record a failed request — may trip the breaker to OPEN."""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state is CircuitState.HALF_OPEN:
                # Any failure during half-open re-opens immediately.
                self._state = CircuitState.OPEN
                return

            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN

    async def record_half_open_attempt(self) -> None:
        """Increment the half-open attempt counter (call before the request)."""
        async with self._lock:
            self._half_open_attempts += 1

    def reset(self) -> None:
        """Reset to pristine CLOSED state (e.g. on provider restart)."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._half_open_attempts = 0
