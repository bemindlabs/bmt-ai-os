"""Additional unit tests for ProviderMetrics edge cases and ota/state coverage."""

from __future__ import annotations

from bmt_ai_os.providers.metrics import ProviderMetrics


class TestProviderMetricsEdgeCases:
    def test_record_success_multiple_providers(self):
        m = ProviderMetrics()
        for provider in ["ollama", "openai", "groq", "anthropic", "mistral"]:
            m.record_success(provider, 100.0)
        metrics = m.get_metrics()
        assert len(metrics) == 5

    def test_record_failure_does_not_update_latency(self):
        m = ProviderMetrics()
        m.record_success("p", 100.0)
        m.record_failure("p", 999.0)
        # Latency only from successes; 1 success at 100ms = avg 100ms
        assert m.get_metrics()["p"]["avg_latency_ms"] == 100.0

    def test_reset_all_clears_all_providers(self):
        m = ProviderMetrics()
        for p in ["a", "b", "c"]:
            m.record_success(p, 50.0)
        m.reset()
        assert m.get_metrics() == {}

    def test_reset_specific_leaves_others(self):
        m = ProviderMetrics()
        m.record_success("keep", 10.0)
        m.record_success("remove", 20.0)
        m.reset("remove")
        remaining = m.get_metrics()
        assert "keep" in remaining
        assert "remove" not in remaining

    def test_successive_successes_accumulate_latency(self):
        m = ProviderMetrics()
        m.record_success("p", 10.0)
        m.record_success("p", 20.0)
        m.record_success("p", 30.0)
        metrics = m.get_metrics()
        assert metrics["p"]["successes"] == 3
        assert metrics["p"]["avg_latency_ms"] == 20.0

    def test_get_metrics_returns_copy(self):
        m = ProviderMetrics()
        m.record_success("p", 50.0)
        snap1 = m.get_metrics()
        m.record_success("p", 100.0)
        snap2 = m.get_metrics()
        # snap1 was a fresh call, check values differ
        assert snap2["p"]["successes"] == 2
        assert snap1["p"]["successes"] == 1

    def test_zero_latency_success(self):
        m = ProviderMetrics()
        m.record_success("p", 0.0)
        assert m.get_metrics()["p"]["avg_latency_ms"] == 0.0

    def test_very_high_latency(self):
        m = ProviderMetrics()
        m.record_success("p", 99999.9)
        assert m.get_metrics()["p"]["total_requests"] == 1

    def test_many_failures_total_requests(self):
        m = ProviderMetrics()
        for _ in range(100):
            m.record_failure("p", 0.0)
        assert m.get_metrics()["p"]["total_requests"] == 100
        assert m.get_metrics()["p"]["failures"] == 100


class TestOtaStateManagerExtra:
    """Additional OTA state manager tests for edge cases."""

    def test_load_handles_empty_json_file(self, tmp_path):
        from bmt_ai_os.ota.state import StateManager

        f = tmp_path / "state.json"
        f.write_text("{}")
        mgr = StateManager(path=f)
        state = mgr.load()
        # Empty JSON -> all defaults
        assert state.current_slot == "a"

    def test_save_overwrites_existing(self, tmp_path):
        from bmt_ai_os.ota.state import OTAState, StateManager

        f = tmp_path / "state.json"
        mgr = StateManager(path=f)
        mgr.save(OTAState(bootcount=1))
        mgr.save(OTAState(bootcount=99))
        state = mgr.load()
        assert state.bootcount == 99

    def test_confirm_after_increment(self, tmp_path):
        from bmt_ai_os.ota.state import StateManager

        mgr = StateManager(path=tmp_path / "state.json")
        mgr.increment_bootcount()
        mgr.increment_bootcount()
        final = mgr.confirm()
        assert final.bootcount == 0
        assert final.confirmed is True

    def test_set_last_update_persisted(self, tmp_path):
        from bmt_ai_os.ota.state import StateManager

        mgr = StateManager(path=tmp_path / "state.json")
        mgr.set_last_update("2026-01-01T00:00:00+00:00")
        loaded = mgr.load()
        assert loaded.last_update == "2026-01-01T00:00:00+00:00"

    def test_ota_state_from_dict_preserves_none_last_update(self):
        from bmt_ai_os.ota.state import OTAState

        s = OTAState.from_dict({"last_update": None})
        assert s.last_update is None

    def test_ota_state_bootcount_zero_is_valid(self):
        from bmt_ai_os.ota.state import OTAState

        s = OTAState(bootcount=0)
        assert s.bootcount == 0

    def test_ota_state_confirmed_false(self):
        from bmt_ai_os.ota.state import OTAState

        s = OTAState(confirmed=False)
        assert s.confirmed is False


class TestCircuitBreakerEdgeCases:
    """Additional edge-case tests for ProviderCircuitBreaker."""

    def test_multiple_resets(self):
        import asyncio

        from bmt_ai_os.providers.circuit_breaker import CircuitState, ProviderCircuitBreaker

        cb = ProviderCircuitBreaker(failure_threshold=1)
        asyncio.run(cb.record_failure())
        cb.reset()
        cb.reset()  # double reset should be idempotent
        assert cb.state is CircuitState.CLOSED

    def test_record_success_from_closed_is_idempotent(self):
        import asyncio

        from bmt_ai_os.providers.circuit_breaker import CircuitState, ProviderCircuitBreaker

        cb = ProviderCircuitBreaker()
        asyncio.run(cb.record_success())
        assert cb.state is CircuitState.CLOSED
        assert cb._failure_count == 0

    def test_half_open_max_one_request(self):
        import asyncio

        from bmt_ai_os.providers.circuit_breaker import CircuitState, ProviderCircuitBreaker

        cb = ProviderCircuitBreaker(
            failure_threshold=1, cooldown_seconds=0.0, half_open_max_requests=1
        )
        asyncio.run(cb.record_failure())
        # Force to HALF_OPEN
        cb._state = CircuitState.HALF_OPEN
        cb._half_open_attempts = 0
        assert cb.is_available() is True
        asyncio.run(cb.record_half_open_attempt())
        assert cb.is_available() is False
