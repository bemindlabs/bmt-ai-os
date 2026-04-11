"""Unit tests for bmt_ai_os.controller.metrics."""

from __future__ import annotations

import threading
import time

from bmt_ai_os.controller.metrics import MetricsCollector, get_collector


class TestMetricsCollector:
    def _make(self) -> MetricsCollector:
        return MetricsCollector()

    def test_initial_state(self):
        mc = self._make()
        summary = mc.get_summary()
        assert summary["total_requests"] == 0
        assert summary["error_count"] == 0
        assert summary["avg_latency_ms"] is None
        assert summary["error_rate"] is None
        assert summary["requests_by_provider"] == {}

    def test_record_request_increments_total(self):
        mc = self._make()
        mc.record_request("ollama", "POST", 100.0, success=True)
        summary = mc.get_summary()
        assert summary["total_requests"] == 1
        assert summary["requests_by_provider"]["ollama"] == 1

    def test_record_multiple_providers(self):
        mc = self._make()
        mc.record_request("ollama", "POST", 50.0, success=True)
        mc.record_request("openai", "POST", 150.0, success=True)
        mc.record_request("ollama", "POST", 75.0, success=True)
        summary = mc.get_summary()
        assert summary["total_requests"] == 3
        assert summary["requests_by_provider"]["ollama"] == 2
        assert summary["requests_by_provider"]["openai"] == 1

    def test_error_count_increments_on_failure(self):
        mc = self._make()
        mc.record_request("ollama", "POST", 100.0, success=False)
        mc.record_request("ollama", "POST", 50.0, success=True)
        summary = mc.get_summary()
        assert summary["error_count"] == 1
        assert summary["total_requests"] == 2

    def test_error_rate_computed(self):
        mc = self._make()
        mc.record_request("ollama", "POST", 100.0, success=True)
        mc.record_request("ollama", "POST", 100.0, success=False)
        summary = mc.get_summary()
        assert summary["error_rate"] == 0.5

    def test_avg_latency_computed(self):
        mc = self._make()
        mc.record_request("ollama", "POST", 100.0, success=True)
        mc.record_request("ollama", "POST", 200.0, success=True)
        summary = mc.get_summary()
        assert summary["avg_latency_ms"] == 150.0

    def test_record_health_check(self):
        mc = self._make()
        mc.record_health_check("ollama", healthy=True, latency_ms=5.0)
        mc.record_health_check("ollama", healthy=False, latency_ms=10.0)
        summary = mc.get_summary()
        history = summary["health_check_history"]["ollama"]
        assert len(history) == 2
        assert history[0]["healthy"] is True
        assert history[1]["healthy"] is False

    def test_uptime_positive(self):
        mc = self._make()
        time.sleep(0.01)
        summary = mc.get_summary()
        assert summary["uptime_seconds"] > 0

    def test_thread_safety(self):
        """Multiple threads recording concurrently should not corrupt state."""
        mc = self._make()
        errors = []

        def _worker():
            try:
                for _ in range(50):
                    mc.record_request("ollama", "POST", 10.0, success=True)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert mc.get_summary()["total_requests"] == 400

    def test_health_history_capped(self):
        """Health history per service should not grow unboundedly."""
        mc = self._make()
        for i in range(25):
            mc.record_health_check("svc", healthy=(i % 2 == 0), latency_ms=1.0)
        history = mc.get_summary()["health_check_history"]["svc"]
        # maxlen is 10
        assert len(history) <= 10


class TestGetCollector:
    def test_returns_same_instance(self):
        from bmt_ai_os.controller import metrics as _metrics_mod

        # Reset singleton for test isolation
        original = _metrics_mod._collector
        _metrics_mod._collector = None
        try:
            c1 = get_collector()
            c2 = get_collector()
            assert c1 is c2
        finally:
            _metrics_mod._collector = original

    def test_returns_metrics_collector_instance(self):
        c = get_collector()
        assert isinstance(c, MetricsCollector)
