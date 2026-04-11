"""Unit tests for bmt_ai_os.providers.circuit_breaker.ProviderCircuitBreaker."""

from __future__ import annotations

import asyncio

from bmt_ai_os.providers.circuit_breaker import CircuitState, ProviderCircuitBreaker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------


class TestInitialState:
    def test_initial_state_is_closed(self):
        cb = ProviderCircuitBreaker()
        assert cb.state is CircuitState.CLOSED

    def test_is_available_when_closed(self):
        cb = ProviderCircuitBreaker()
        assert cb.is_available() is True

    def test_default_threshold(self):
        cb = ProviderCircuitBreaker()
        assert cb.failure_threshold == 3

    def test_default_cooldown(self):
        cb = ProviderCircuitBreaker()
        assert cb.cooldown_seconds == 60.0

    def test_default_half_open_max(self):
        cb = ProviderCircuitBreaker()
        assert cb.half_open_max_requests == 1


# ---------------------------------------------------------------------------
# Closed -> Open
# ---------------------------------------------------------------------------


class TestClosedToOpen:
    def test_opens_after_threshold(self):
        cb = ProviderCircuitBreaker(failure_threshold=3)
        for _ in range(3):
            run(cb.record_failure())
        assert cb.state is CircuitState.OPEN

    def test_does_not_open_below_threshold(self):
        cb = ProviderCircuitBreaker(failure_threshold=3)
        run(cb.record_failure())
        run(cb.record_failure())
        assert cb.state is CircuitState.CLOSED

    def test_not_available_when_open(self):
        cb = ProviderCircuitBreaker(failure_threshold=1, cooldown_seconds=9999)
        run(cb.record_failure())
        assert cb.is_available() is False

    def test_failure_count_increments(self):
        cb = ProviderCircuitBreaker(failure_threshold=10)
        run(cb.record_failure())
        run(cb.record_failure())
        assert cb._failure_count == 2


# ---------------------------------------------------------------------------
# Open -> Half-Open (cooldown)
# ---------------------------------------------------------------------------


class TestOpenToHalfOpen:
    def test_transitions_to_half_open_after_cooldown(self):
        cb = ProviderCircuitBreaker(failure_threshold=1, cooldown_seconds=0.0)
        run(cb.record_failure())
        # With cooldown_seconds=0 the state property immediately transitions
        # OPEN -> HALF_OPEN on first access (elapsed >= 0).
        assert cb.state is CircuitState.HALF_OPEN

    def test_still_open_before_cooldown(self):
        cb = ProviderCircuitBreaker(failure_threshold=1, cooldown_seconds=9999)
        run(cb.record_failure())
        assert cb.state is CircuitState.OPEN
        # Not enough time has passed
        assert cb.is_available() is False

    def test_available_after_cooldown(self):
        cb = ProviderCircuitBreaker(failure_threshold=1, cooldown_seconds=0.0)
        run(cb.record_failure())
        # After cooldown elapses, should be available (half-open)
        assert cb.is_available() is True


# ---------------------------------------------------------------------------
# Half-Open behavior
# ---------------------------------------------------------------------------


class TestHalfOpen:
    def test_available_when_half_open_and_attempts_not_exhausted(self):
        cb = ProviderCircuitBreaker(
            failure_threshold=1, cooldown_seconds=0.0, half_open_max_requests=2
        )
        run(cb.record_failure())
        cb._state = CircuitState.HALF_OPEN
        cb._half_open_attempts = 0
        assert cb.is_available() is True

    def test_not_available_when_half_open_attempts_exhausted(self):
        cb = ProviderCircuitBreaker(
            failure_threshold=1, cooldown_seconds=0.0, half_open_max_requests=1
        )
        run(cb.record_failure())
        cb._state = CircuitState.HALF_OPEN
        cb._half_open_attempts = 1
        assert cb.is_available() is False

    def test_failure_during_half_open_reopens(self):
        cb = ProviderCircuitBreaker(failure_threshold=3)
        cb._state = CircuitState.HALF_OPEN
        run(cb.record_failure())
        assert cb.state is CircuitState.OPEN

    def test_record_half_open_attempt_increments(self):
        cb = ProviderCircuitBreaker()
        cb._state = CircuitState.HALF_OPEN
        run(cb.record_half_open_attempt())
        assert cb._half_open_attempts == 1


# ---------------------------------------------------------------------------
# Half-Open -> Closed (success)
# ---------------------------------------------------------------------------


class TestRecordSuccess:
    def test_success_closes_circuit_from_half_open(self):
        cb = ProviderCircuitBreaker(failure_threshold=1, cooldown_seconds=0.0)
        run(cb.record_failure())
        cb._state = CircuitState.HALF_OPEN
        run(cb.record_success())
        assert cb.state is CircuitState.CLOSED

    def test_success_resets_failure_count(self):
        cb = ProviderCircuitBreaker(failure_threshold=10)
        run(cb.record_failure())
        run(cb.record_failure())
        run(cb.record_success())
        assert cb._failure_count == 0

    def test_success_resets_half_open_attempts(self):
        cb = ProviderCircuitBreaker()
        cb._half_open_attempts = 3
        run(cb.record_success())
        assert cb._half_open_attempts == 0

    def test_closed_after_success_allows_requests(self):
        cb = ProviderCircuitBreaker(failure_threshold=1, cooldown_seconds=0.0)
        run(cb.record_failure())
        cb._state = CircuitState.HALF_OPEN
        run(cb.record_success())
        assert cb.is_available() is True


# ---------------------------------------------------------------------------
# reset()
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_clears_all_state(self):
        cb = ProviderCircuitBreaker(failure_threshold=1)
        run(cb.record_failure())
        cb.reset()
        assert cb._state is CircuitState.CLOSED
        assert cb._failure_count == 0
        assert cb._last_failure_time == 0.0
        assert cb._half_open_attempts == 0

    def test_available_after_reset(self):
        cb = ProviderCircuitBreaker(failure_threshold=1, cooldown_seconds=9999)
        run(cb.record_failure())
        assert not cb.is_available()
        cb.reset()
        assert cb.is_available()

    def test_reset_from_any_state(self):
        for initial_state in [CircuitState.CLOSED, CircuitState.OPEN, CircuitState.HALF_OPEN]:
            cb = ProviderCircuitBreaker()
            cb._state = initial_state
            cb.reset()
            assert cb.state is CircuitState.CLOSED


# ---------------------------------------------------------------------------
# Custom configuration
# ---------------------------------------------------------------------------


class TestCustomConfig:
    def test_custom_threshold(self):
        cb = ProviderCircuitBreaker(failure_threshold=5)
        for _ in range(4):
            run(cb.record_failure())
        assert cb.state is CircuitState.CLOSED
        run(cb.record_failure())
        assert cb.state is CircuitState.OPEN

    def test_custom_half_open_max(self):
        cb = ProviderCircuitBreaker(
            failure_threshold=1, cooldown_seconds=0.0, half_open_max_requests=3
        )
        run(cb.record_failure())
        cb._state = CircuitState.HALF_OPEN
        cb._half_open_attempts = 2
        assert cb.is_available() is True  # 2 < 3
        cb._half_open_attempts = 3
        assert cb.is_available() is False  # 3 >= 3
