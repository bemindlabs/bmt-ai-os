"""Unit tests for bmt_ai_os.providers.metrics.ProviderMetrics."""

from __future__ import annotations

from bmt_ai_os.providers.metrics import ProviderMetrics, _ProviderStats

# ---------------------------------------------------------------------------
# _ProviderStats
# ---------------------------------------------------------------------------


class TestProviderStats:
    def test_initial_values(self):
        s = _ProviderStats()
        assert s.total_requests == 0
        assert s.successes == 0
        assert s.failures == 0
        assert s.total_latency_ms == 0.0
        assert s.last_used == 0.0

    def test_avg_latency_zero_when_no_successes(self):
        s = _ProviderStats()
        assert s.avg_latency_ms == 0.0

    def test_avg_latency_calculated(self):
        s = _ProviderStats(successes=2, total_latency_ms=100.0)
        assert s.avg_latency_ms == 50.0

    def test_to_dict_keys(self):
        s = _ProviderStats(total_requests=5, successes=4, failures=1, total_latency_ms=200.0)
        d = s.to_dict()
        assert "total_requests" in d
        assert "successes" in d
        assert "failures" in d
        assert "avg_latency_ms" in d
        assert "last_used" in d

    def test_to_dict_values(self):
        s = _ProviderStats(total_requests=3, successes=2, failures=1, total_latency_ms=60.0)
        d = s.to_dict()
        assert d["total_requests"] == 3
        assert d["successes"] == 2
        assert d["failures"] == 1
        assert d["avg_latency_ms"] == 30.0

    def test_avg_latency_rounded(self):
        s = _ProviderStats(successes=3, total_latency_ms=100.0)
        assert s.to_dict()["avg_latency_ms"] == round(100.0 / 3, 2)


# ---------------------------------------------------------------------------
# ProviderMetrics
# ---------------------------------------------------------------------------


class TestProviderMetrics:
    def test_record_success_increments_counters(self):
        m = ProviderMetrics()
        m.record_success("ollama", 50.0)
        metrics = m.get_metrics()
        assert metrics["ollama"]["total_requests"] == 1
        assert metrics["ollama"]["successes"] == 1
        assert metrics["ollama"]["failures"] == 0

    def test_record_failure_increments_counters(self):
        m = ProviderMetrics()
        m.record_failure("ollama", 10.0)
        metrics = m.get_metrics()
        assert metrics["ollama"]["total_requests"] == 1
        assert metrics["ollama"]["failures"] == 1
        assert metrics["ollama"]["successes"] == 0

    def test_record_success_tracks_latency(self):
        m = ProviderMetrics()
        m.record_success("ollama", 100.0)
        m.record_success("ollama", 200.0)
        metrics = m.get_metrics()
        assert metrics["ollama"]["avg_latency_ms"] == 150.0

    def test_record_failure_does_not_track_latency(self):
        m = ProviderMetrics()
        m.record_failure("ollama", 999.0)
        metrics = m.get_metrics()
        assert metrics["ollama"]["avg_latency_ms"] == 0.0

    def test_multiple_providers_tracked_independently(self):
        m = ProviderMetrics()
        m.record_success("ollama", 50.0)
        m.record_success("ollama", 50.0)
        m.record_failure("openai", 10.0)
        metrics = m.get_metrics()
        assert metrics["ollama"]["successes"] == 2
        assert metrics["openai"]["failures"] == 1

    def test_get_metrics_returns_snapshot(self):
        m = ProviderMetrics()
        m.record_success("p1", 10.0)
        snapshot = m.get_metrics()
        m.record_success("p1", 20.0)
        # Snapshot should not be affected by subsequent calls
        assert snapshot["p1"]["successes"] == 1

    def test_get_metrics_empty(self):
        m = ProviderMetrics()
        assert m.get_metrics() == {}

    def test_reset_single_provider(self):
        m = ProviderMetrics()
        m.record_success("ollama", 10.0)
        m.record_success("openai", 20.0)
        m.reset("ollama")
        metrics = m.get_metrics()
        assert "ollama" not in metrics
        assert "openai" in metrics

    def test_reset_all_providers(self):
        m = ProviderMetrics()
        m.record_success("ollama", 10.0)
        m.record_success("openai", 20.0)
        m.reset()
        assert m.get_metrics() == {}

    def test_reset_nonexistent_is_noop(self):
        m = ProviderMetrics()
        m.record_success("ollama", 10.0)
        m.reset("ghost")
        assert "ollama" in m.get_metrics()

    def test_last_used_is_set_on_success(self):
        m = ProviderMetrics()
        m.record_success("ollama", 10.0)
        metrics = m.get_metrics()
        assert metrics["ollama"]["last_used"] > 0

    def test_last_used_is_set_on_failure(self):
        m = ProviderMetrics()
        m.record_failure("ollama", 10.0)
        metrics = m.get_metrics()
        assert metrics["ollama"]["last_used"] > 0

    def test_auto_creates_stats_on_first_record(self):
        m = ProviderMetrics()
        m.record_success("new-provider", 5.0)
        metrics = m.get_metrics()
        assert "new-provider" in metrics

    def test_cumulative_requests(self):
        m = ProviderMetrics()
        for _ in range(5):
            m.record_success("p", 10.0)
        for _ in range(3):
            m.record_failure("p", 5.0)
        metrics = m.get_metrics()
        assert metrics["p"]["total_requests"] == 8
        assert metrics["p"]["successes"] == 5
        assert metrics["p"]["failures"] == 3
