"""Unit tests for Prometheus metrics export (BMTOS-49).

Tests cover:
- MetricsCollector: endpoint stats, provider router injection, get_summary
- prometheus.py: /metrics endpoint shape, metric label coverage
- System stats helper: psutil available / unavailable paths
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _fresh_collector():
    """Return a brand-new MetricsCollector with no singleton side-effects."""
    from bmt_ai_os.controller.metrics import MetricsCollector

    return MetricsCollector()


def _app_with_fresh_registry():
    """Build an isolated FastAPI app + prometheus router backed by a fresh collector.

    We patch ``bmt_ai_os.controller.prometheus.get_collector`` so each test
    gets its own state without touching the process-wide singleton.
    """
    collector = _fresh_collector()

    # Lazily import the router module — we will monkey-patch its internals.
    import bmt_ai_os.controller.prometheus as prom_module

    return collector, prom_module


# ---------------------------------------------------------------------------
# MetricsCollector tests
# ---------------------------------------------------------------------------


class TestMetricsCollector:
    def test_initial_summary(self):
        c = _fresh_collector()
        s = c.get_summary()
        assert s["total_requests"] == 0
        assert s["error_count"] == 0
        assert s["error_rate"] is None
        assert s["avg_latency_ms"] is None
        assert s["endpoint_stats"] == {}
        assert s["provider_metrics"] == {}
        assert s["circuit_states"] == {}
        assert s["uptime_seconds"] >= 0.0

    def test_record_request_increments_counters(self):
        c = _fresh_collector()
        c.record_request("ollama", "POST", latency_ms=120.0, success=True)
        c.record_request("ollama", "POST", latency_ms=200.0, success=False)
        s = c.get_summary()
        assert s["total_requests"] == 2
        assert s["error_count"] == 1
        assert s["requests_by_provider"]["ollama"] == 2
        assert s["error_rate"] == pytest.approx(0.5, abs=0.001)
        assert s["avg_latency_ms"] == pytest.approx(160.0, abs=1.0)

    def test_record_endpoint_request(self):
        c = _fresh_collector()
        c.record_endpoint_request("/v1/chat/completions", "POST", 300.0, success=True)
        c.record_endpoint_request("/v1/chat/completions", "POST", 500.0, success=True)
        c.record_endpoint_request("/v1/chat/completions", "POST", 100.0, success=False)
        s = c.get_summary()
        ep = s["endpoint_stats"]["/v1/chat/completions"]["POST"]
        assert ep["count"] == 3
        assert ep["success_count"] == 2
        assert ep["error_count"] == 1
        assert ep["latency_sum_s"] == pytest.approx((300 + 500 + 100) / 1000.0, abs=0.001)

    def test_record_health_check(self):
        c = _fresh_collector()
        c.record_health_check("ollama", healthy=True, latency_ms=15.0)
        c.record_health_check("ollama", healthy=False, latency_ms=5000.0)
        s = c.get_summary()
        history = s["health_check_history"]["ollama"]
        assert len(history) == 2
        assert history[0]["healthy"] is True
        assert history[1]["healthy"] is False
        assert history[1]["latency_ms"] == pytest.approx(5000.0, abs=1.0)

    def test_health_check_history_capped_at_10(self):
        c = _fresh_collector()
        for i in range(15):
            c.record_health_check("chromadb", healthy=True, latency_ms=float(i))
        history = c.get_summary()["health_check_history"]["chromadb"]
        assert len(history) == 10

    def test_multiple_providers(self):
        c = _fresh_collector()
        c.record_request("ollama", "POST", 100.0, True)
        c.record_request("openai", "POST", 300.0, True)
        c.record_request("openai", "POST", 200.0, False)
        s = c.get_summary()
        assert s["requests_by_provider"]["ollama"] == 1
        assert s["requests_by_provider"]["openai"] == 2
        assert s["total_requests"] == 3
        assert s["error_count"] == 1

    def test_set_provider_router_populates_provider_metrics(self):
        c = _fresh_collector()

        # Build a mock ProviderRouter-like object
        mock_router = MagicMock()
        mock_metrics = MagicMock()
        mock_metrics.get_metrics.return_value = {
            "ollama": {
                "total_requests": 10,
                "successes": 9,
                "failures": 1,
                "avg_latency_ms": 250.0,
                "last_used": 0.0,
            }
        }
        mock_router.metrics = mock_metrics

        mock_cb = MagicMock()
        mock_cb.state.value = "closed"
        mock_router.get_circuit_breaker.return_value = mock_cb

        c.set_provider_router(mock_router)
        s = c.get_summary()

        assert "ollama" in s["provider_metrics"]
        assert s["circuit_states"]["ollama"] == "closed"

    def test_circuit_state_open(self):
        c = _fresh_collector()
        mock_router = MagicMock()
        mock_router.metrics.get_metrics.return_value = {"vllm": {"avg_latency_ms": 0.0}}
        mock_cb = MagicMock()
        mock_cb.state.value = "open"
        mock_router.get_circuit_breaker.return_value = mock_cb
        c.set_provider_router(mock_router)
        s = c.get_summary()
        assert s["circuit_states"]["vllm"] == "open"

    def test_uptime_increases(self):
        c = _fresh_collector()
        s1 = c.get_summary()
        time.sleep(0.05)
        s2 = c.get_summary()
        assert s2["uptime_seconds"] > s1["uptime_seconds"]

    def test_thread_safety_concurrent_requests(self):
        """Multiple threads recording requests should not corrupt counters."""
        import threading

        c = _fresh_collector()
        errors = []

        def _worker():
            try:
                for _ in range(100):
                    c.record_request("ollama", "POST", 50.0, True)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert c.get_summary()["total_requests"] == 800


# ---------------------------------------------------------------------------
# /metrics endpoint tests
# ---------------------------------------------------------------------------


class TestPrometheusEndpoint:
    """Tests use the real FastAPI app with a mocked collector singleton."""

    @pytest.fixture()
    def client(self):
        """Test client with a fresh collector injected into the prometheus module."""
        from fastapi import FastAPI

        app = FastAPI()

        collector = _fresh_collector()

        # We need to patch the collector used inside prometheus.py
        with patch("bmt_ai_os.controller.prometheus.get_collector", return_value=collector):
            from bmt_ai_os.controller.prometheus import router

            app.include_router(router)
            with TestClient(app) as c:
                yield c, collector

    def test_metrics_endpoint_status_200(self, client):
        tc, _ = client
        resp = tc.get("/metrics")
        assert resp.status_code == 200

    def test_metrics_content_type(self, client):
        tc, _ = client
        resp = tc.get("/metrics")
        assert "text/plain" in resp.headers["content-type"]

    def test_metrics_contains_uptime(self, client):
        tc, _ = client
        body = tc.get("/metrics").text
        assert "bmt_uptime_seconds" in body

    def test_metrics_contains_service_healthy(self, client):
        tc, collector = client
        collector.record_health_check("ollama", healthy=True, latency_ms=10.0)
        body = tc.get("/metrics").text
        assert "bmt_service_healthy" in body
        assert 'service="ollama"' in body

    def test_metrics_service_healthy_value_1(self, client):
        tc, collector = client
        collector.record_health_check("ollama", healthy=True, latency_ms=5.0)
        body = tc.get("/metrics").text
        # Find the line with service="ollama" and assert value is 1.0
        for line in body.splitlines():
            if "bmt_service_healthy" in line and 'service="ollama"' in line:
                if not line.startswith("#"):
                    assert line.endswith("1.0"), f"Expected 1.0 got: {line}"

    def test_metrics_service_unhealthy_value_0(self, client):
        tc, collector = client
        collector.record_health_check("chromadb", healthy=False, latency_ms=100.0)
        body = tc.get("/metrics").text
        for line in body.splitlines():
            if "bmt_service_healthy" in line and 'service="chromadb"' in line:
                if not line.startswith("#"):
                    assert line.endswith("0.0"), f"Expected 0.0 got: {line}"

    def test_metrics_contains_error_rate(self, client):
        tc, collector = client
        collector.record_request("ollama", "POST", 100.0, False)
        body = tc.get("/metrics").text
        assert "bmt_error_rate" in body

    def test_metrics_contains_provider_requests(self, client):
        tc, collector = client
        collector.record_request("ollama", "POST", 100.0, True)
        body = tc.get("/metrics").text
        assert "bmt_provider_requests_total" in body

    def test_metrics_contains_request_latency_histogram(self, client):
        tc, _ = client
        body = tc.get("/metrics").text
        assert "bmt_request_latency_seconds" in body

    def test_metrics_contains_provider_latency_histogram(self, client):
        tc, _ = client
        body = tc.get("/metrics").text
        assert "bmt_provider_latency_seconds" in body

    def test_metrics_contains_system_metrics_when_psutil_available(self, client):
        tc, _ = client
        fake_psutil = MagicMock()
        fake_psutil.cpu_percent.return_value = 42.0
        mem = MagicMock()
        mem.used = 1_000_000_000
        mem.total = 4_000_000_000
        fake_psutil.virtual_memory.return_value = mem
        disk = MagicMock()
        disk.used = 20_000_000_000
        disk.total = 100_000_000_000
        disk.percent = 20.0
        fake_psutil.disk_usage.return_value = disk

        with patch.dict("sys.modules", {"psutil": fake_psutil}):
            body = tc.get("/metrics").text

        assert "bmt_system_cpu_usage_percent" in body
        assert "bmt_system_memory_usage_bytes" in body
        assert "bmt_system_disk_usage_percent" in body

    def test_metrics_graceful_when_psutil_missing(self, client):
        """The /metrics endpoint must succeed even when psutil is not installed."""
        tc, _ = client
        with patch(
            "bmt_ai_os.controller.prometheus._collect_system_stats",
            return_value={
                "cpu_percent": None,
                "memory_used": None,
                "memory_total": None,
                "disk_used": None,
                "disk_total": None,
                "disk_percent": None,
            },
        ):
            resp = tc.get("/metrics")
        assert resp.status_code == 200

    def test_metrics_provider_circuit_state_from_router(self, client):
        tc, collector = client
        mock_router = MagicMock()
        mock_router.metrics.get_metrics.return_value = {"ollama": {"avg_latency_ms": 150.0}}
        mock_cb = MagicMock()
        mock_cb.state.value = "open"
        mock_router.get_circuit_breaker.return_value = mock_cb
        collector.set_provider_router(mock_router)

        body = tc.get("/metrics").text
        assert "bmt_provider_circuit_state" in body

    def test_metrics_endpoint_stats_reflected(self, client):
        tc, collector = client
        collector.record_endpoint_request("/v1/chat/completions", "POST", 500.0, True)
        collector.record_endpoint_request("/v1/chat/completions", "POST", 600.0, False)
        body = tc.get("/metrics").text
        assert "bmt_request_errors_total" in body

    def test_metrics_response_time_gauge(self, client):
        tc, collector = client
        collector.record_health_check("ollama", healthy=True, latency_ms=42.5)
        body = tc.get("/metrics").text
        assert "bmt_service_response_time_ms" in body

    def test_metrics_zero_requests(self, client):
        """With no requests the endpoint must still return valid Prometheus text."""
        tc, _ = client
        resp = tc.get("/metrics")
        assert resp.status_code == 200
        body = resp.text
        assert "bmt_uptime_seconds" in body


# ---------------------------------------------------------------------------
# _collect_system_stats unit tests
# ---------------------------------------------------------------------------


class TestCollectSystemStats:
    def test_returns_none_when_psutil_missing(self):
        import sys

        # Temporarily hide psutil from imports
        original = sys.modules.pop("psutil", None)
        try:
            # Force the module-level import inside _collect_system_stats to fail
            import bmt_ai_os.controller.prometheus as prom

            with patch.dict("sys.modules", {"psutil": None}):
                stats = prom._collect_system_stats()
        finally:
            if original is not None:
                sys.modules["psutil"] = original

        assert stats["cpu_percent"] is None
        assert stats["memory_used"] is None
        assert stats["disk_total"] is None

    def test_returns_values_when_psutil_available(self):
        fake_psutil = MagicMock()
        fake_psutil.cpu_percent.return_value = 55.5
        mem = MagicMock(used=2_000_000_000, total=8_000_000_000)
        fake_psutil.virtual_memory.return_value = mem
        disk = MagicMock(used=50_000_000_000, total=200_000_000_000, percent=25.0)
        fake_psutil.disk_usage.return_value = disk

        with patch.dict("sys.modules", {"psutil": fake_psutil}):
            import bmt_ai_os.controller.prometheus as prom

            stats = prom._collect_system_stats()

        assert stats["cpu_percent"] == pytest.approx(55.5)
        assert stats["memory_used"] == 2_000_000_000
        assert stats["memory_total"] == 8_000_000_000
        assert stats["disk_used"] == 50_000_000_000
        assert stats["disk_total"] == 200_000_000_000
        assert stats["disk_percent"] == pytest.approx(25.0)

    def test_returns_none_on_psutil_exception(self):
        fake_psutil = MagicMock()
        fake_psutil.cpu_percent.side_effect = RuntimeError("no cpu info")

        with patch.dict("sys.modules", {"psutil": fake_psutil}):
            import bmt_ai_os.controller.prometheus as prom

            stats = prom._collect_system_stats()

        # Should not raise; values should fall back to None
        assert stats["cpu_percent"] is None


# ---------------------------------------------------------------------------
# Alert rules file existence
# ---------------------------------------------------------------------------


class TestAlertRulesFile:
    def test_alerts_yml_exists(self):
        from pathlib import Path

        alerts_path = (
            Path(__file__).parent.parent.parent
            / "bmt_ai_os"
            / "runtime"
            / "monitoring"
            / "alerts.yml"
        )
        assert alerts_path.exists(), f"alerts.yml not found at {alerts_path}"

    def test_alerts_yml_is_valid_yaml(self):
        from pathlib import Path

        import yaml

        alerts_path = (
            Path(__file__).parent.parent.parent
            / "bmt_ai_os"
            / "runtime"
            / "monitoring"
            / "alerts.yml"
        )
        content = alerts_path.read_text()
        data = yaml.safe_load(content)
        assert "groups" in data
        assert len(data["groups"]) > 0

    def test_alerts_yml_has_required_alert_names(self):
        from pathlib import Path

        import yaml

        alerts_path = (
            Path(__file__).parent.parent.parent
            / "bmt_ai_os"
            / "runtime"
            / "monitoring"
            / "alerts.yml"
        )
        data = yaml.safe_load(alerts_path.read_text())
        all_alert_names = [
            rule["alert"] for group in data["groups"] for rule in group.get("rules", [])
        ]
        required = {
            "BMTServiceDown",
            "BMTControllerDown",
            "BMTHighRequestLatency",
            "BMTHighErrorRate",
            "BMTDiskFull",
            "BMTCircuitBreakerOpen",
            "BMTLowMemory",
        }
        missing = required - set(all_alert_names)
        assert not missing, f"Missing alert rules: {missing}"

    def test_alerts_yml_all_rules_have_severity(self):
        from pathlib import Path

        import yaml

        alerts_path = (
            Path(__file__).parent.parent.parent
            / "bmt_ai_os"
            / "runtime"
            / "monitoring"
            / "alerts.yml"
        )
        data = yaml.safe_load(alerts_path.read_text())
        for group in data["groups"]:
            for rule in group.get("rules", []):
                labels = rule.get("labels", {})
                assert "severity" in labels, f"Alert '{rule['alert']}' is missing a severity label"


# ---------------------------------------------------------------------------
# Grafana dashboard file existence
# ---------------------------------------------------------------------------


class TestGrafanaDashboard:
    def test_grafana_dashboard_exists(self):
        from pathlib import Path

        dashboard_path = (
            Path(__file__).parent.parent.parent
            / "bmt_ai_os"
            / "runtime"
            / "monitoring"
            / "grafana-dashboard.json"
        )
        assert dashboard_path.exists(), f"grafana-dashboard.json not found at {dashboard_path}"

    def test_grafana_dashboard_is_valid_json(self):
        import json
        from pathlib import Path

        dashboard_path = (
            Path(__file__).parent.parent.parent
            / "bmt_ai_os"
            / "runtime"
            / "monitoring"
            / "grafana-dashboard.json"
        )
        data = json.loads(dashboard_path.read_text())
        assert "panels" in data
        assert "title" in data
        assert data["title"] == "BMT AI OS — Monitoring"

    def test_grafana_dashboard_has_expected_panels(self):
        import json
        from pathlib import Path

        dashboard_path = (
            Path(__file__).parent.parent.parent
            / "bmt_ai_os"
            / "runtime"
            / "monitoring"
            / "grafana-dashboard.json"
        )
        data = json.loads(dashboard_path.read_text())
        panel_titles = {p.get("title", "") for p in data["panels"]}

        required_titles = {
            "Controller Uptime",
            "Error Rate",
            "Service Health",
            "CPU Usage",
            "Memory Usage",
            "Disk Usage",
            "Provider Request Rate",
            "Circuit Breaker States",
        }
        missing = required_titles - panel_titles
        assert not missing, f"Missing dashboard panels: {missing}"

    def test_grafana_dashboard_uid_set(self):
        import json
        from pathlib import Path

        dashboard_path = (
            Path(__file__).parent.parent.parent
            / "bmt_ai_os"
            / "runtime"
            / "monitoring"
            / "grafana-dashboard.json"
        )
        data = json.loads(dashboard_path.read_text())
        assert data.get("uid"), "Dashboard must have a non-empty uid"
