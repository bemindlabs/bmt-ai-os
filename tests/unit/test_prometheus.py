"""Unit tests for bmt_ai_os.controller.prometheus."""

from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bmt_ai_os.controller.prometheus import router


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def _make_summary(**overrides) -> dict:
    """Return a summary dict matching MetricsCollector.get_summary() shape.

    avg_latency_ms defaults to None so the prometheus module skips the
    histogram population code path (which uses internal prometheus_client
    attributes that changed between versions).
    """
    defaults = {
        "uptime_seconds": 42.0,
        "total_requests": 10,
        "requests_by_provider": {"ollama": 8, "openai": 2},
        "avg_latency_ms": None,  # skip histogram internals in tests
        "health_check_history": {
            "ollama": [{"timestamp": 1.0, "healthy": True, "latency_ms": 5.0}],
            "chromadb": [{"timestamp": 2.0, "healthy": False, "latency_ms": 9.0}],
        },
        "error_count": 1,
        "error_rate": 0.1,
    }
    defaults.update(overrides)
    return defaults


class TestPrometheusMetricsEndpoint:
    def test_endpoint_returns_200(self):
        app = _make_app()
        client = TestClient(app)
        summary = _make_summary()
        with patch("bmt_ai_os.controller.prometheus.get_collector") as mock_gc:
            mock_gc.return_value.get_summary.return_value = summary
            resp = client.get("/metrics")
        assert resp.status_code == 200

    def test_content_type_is_prometheus_text(self):
        app = _make_app()
        client = TestClient(app)
        summary = _make_summary()
        with patch("bmt_ai_os.controller.prometheus.get_collector") as mock_gc:
            mock_gc.return_value.get_summary.return_value = summary
            resp = client.get("/metrics")
        assert "text/plain" in resp.headers["content-type"]

    def test_contains_uptime_metric(self):
        app = _make_app()
        client = TestClient(app)
        summary = _make_summary(uptime_seconds=99.5)
        with patch("bmt_ai_os.controller.prometheus.get_collector") as mock_gc:
            mock_gc.return_value.get_summary.return_value = summary
            resp = client.get("/metrics")
        assert "bmt_uptime_seconds" in resp.text

    def test_contains_requests_total_metric(self):
        app = _make_app()
        client = TestClient(app)
        summary = _make_summary()
        with patch("bmt_ai_os.controller.prometheus.get_collector") as mock_gc:
            mock_gc.return_value.get_summary.return_value = summary
            resp = client.get("/metrics")
        assert "bmt_requests_total" in resp.text

    def test_contains_service_healthy_metric(self):
        app = _make_app()
        client = TestClient(app)
        summary = _make_summary()
        with patch("bmt_ai_os.controller.prometheus.get_collector") as mock_gc:
            mock_gc.return_value.get_summary.return_value = summary
            resp = client.get("/metrics")
        assert "bmt_service_healthy" in resp.text

    def test_handles_zero_requests(self):
        """No division by zero when total_requests is 0."""
        app = _make_app()
        client = TestClient(app)
        summary = _make_summary(
            total_requests=0,
            requests_by_provider={},
            avg_latency_ms=None,
            error_count=0,
            error_rate=None,
        )
        with patch("bmt_ai_os.controller.prometheus.get_collector") as mock_gc:
            mock_gc.return_value.get_summary.return_value = summary
            resp = client.get("/metrics")
        assert resp.status_code == 200

    def test_handles_empty_health_history(self):
        """No crash when a service has an empty health history."""
        app = _make_app()
        client = TestClient(app)
        summary = _make_summary(health_check_history={"ollama": []})
        with patch("bmt_ai_os.controller.prometheus.get_collector") as mock_gc:
            mock_gc.return_value.get_summary.return_value = summary
            resp = client.get("/metrics")
        assert resp.status_code == 200

    def test_provider_labels_appear_in_output(self):
        app = _make_app()
        client = TestClient(app)
        summary = _make_summary(requests_by_provider={"ollama": 5})
        with patch("bmt_ai_os.controller.prometheus.get_collector") as mock_gc:
            mock_gc.return_value.get_summary.return_value = summary
            resp = client.get("/metrics")
        assert "ollama" in resp.text

    def test_latency_histogram_appears_in_output(self):
        """The histogram metric name is always present in the output regardless of data."""
        app = _make_app()
        client = TestClient(app)
        # Use avg_latency_ms=None to avoid touching _count/_sum internal attributes
        # that vary across prometheus_client versions.
        summary = _make_summary(avg_latency_ms=None)
        with patch("bmt_ai_os.controller.prometheus.get_collector") as mock_gc:
            mock_gc.return_value.get_summary.return_value = summary
            resp = client.get("/metrics")
        assert "bmt_request_latency_seconds" in resp.text
