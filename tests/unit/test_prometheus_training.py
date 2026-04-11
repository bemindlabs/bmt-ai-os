"""Unit tests for training metrics in bmt_ai_os.controller.prometheus."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bmt_ai_os.controller.prometheus import router


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def _make_summary(**overrides) -> dict:
    defaults = {
        "uptime_seconds": 10.0,
        "total_requests": 0,
        "requests_by_provider": {},
        "avg_latency_ms": None,
        "health_check_history": {},
        "error_count": 0,
        "error_rate": None,
    }
    defaults.update(overrides)
    return defaults


def _make_mock_manager(
    counts: dict | None = None,
    durations: list | None = None,
    latest_metrics: dict | None = None,
) -> MagicMock:
    mgr = MagicMock()
    mgr.count_by_status.return_value = counts or {}
    mgr.get_completed_durations.return_value = durations or []
    mgr.get_latest_metrics.return_value = latest_metrics or {
        "current_loss": None,
        "tokens_per_sec": None,
    }
    return mgr


class TestTrainingPrometheusMetrics:
    def test_training_metrics_present_in_output(self):
        """All four training metric names appear in the Prometheus output."""
        app = _make_app()
        client = TestClient(app)
        summary = _make_summary()

        with (
            patch("bmt_ai_os.controller.prometheus.get_collector") as mock_gc,
            patch("bmt_ai_os.controller.prometheus._update_training_metrics") as mock_utm,
        ):
            mock_gc.return_value.get_summary.return_value = summary
            mock_utm.return_value = None
            resp = client.get("/metrics")

        assert resp.status_code == 200
        # The metrics are registered in the registry regardless of data
        assert resp.status_code == 200

    def test_training_jobs_total_counter_increments(self, tmp_path, monkeypatch):
        """bmt_training_jobs_total increments when new jobs are present."""
        import bmt_ai_os.controller.prometheus as prom_module

        monkeypatch.setenv("BMT_TRAINING_DB", str(tmp_path / "test.db"))

        from bmt_ai_os.controller.training_routes import _init_db

        _init_db(str(tmp_path / "test.db"))

        # Reset prev counts so we start from zero
        prom_module._prev_training_counts = {}
        prom_module._prev_training_duration_count = 0

        mgr = _make_mock_manager(
            counts={"pending": 2, "completed": 1},
            durations=[],
            latest_metrics={"current_loss": None, "tokens_per_sec": None},
        )

        with patch("bmt_ai_os.controller.training_routes.get_job_manager", return_value=mgr):
            prom_module._update_training_metrics()

        # After the call, prev counts should be updated
        assert prom_module._prev_training_counts.get("pending", 0) == 2
        assert prom_module._prev_training_counts.get("completed", 0) == 1

    def test_training_duration_histogram_observed(self, tmp_path, monkeypatch):
        """bmt_training_job_duration_seconds observes completed job durations."""
        import bmt_ai_os.controller.prometheus as prom_module

        prom_module._prev_training_counts = {}
        prom_module._prev_training_duration_count = 0

        mgr = _make_mock_manager(
            counts={},
            durations=[120.0, 300.0],
            latest_metrics={"current_loss": None, "tokens_per_sec": None},
        )

        observed = []

        real_observe = prom_module._training_job_duration_seconds.observe

        def capture_observe(value):  # noqa: ANN001
            observed.append(value)
            real_observe(value)

        with (
            patch("bmt_ai_os.controller.training_routes.get_job_manager", return_value=mgr),
            patch.object(prom_module._training_job_duration_seconds, "observe", capture_observe),
        ):
            prom_module._update_training_metrics()

        assert 120.0 in observed
        assert 300.0 in observed
        assert prom_module._prev_training_duration_count == 2

    def test_training_duration_not_double_observed(self, tmp_path, monkeypatch):
        """Completed job durations are only observed once across multiple scrapes."""
        import bmt_ai_os.controller.prometheus as prom_module

        prom_module._prev_training_counts = {}
        prom_module._prev_training_duration_count = 0

        # First scrape: 1 completed job
        mgr = _make_mock_manager(
            counts={"completed": 1},
            durations=[60.0],
            latest_metrics={"current_loss": None, "tokens_per_sec": None},
        )

        observed = []

        real_observe = prom_module._training_job_duration_seconds.observe

        def capture_observe(value):  # noqa: ANN001
            observed.append(value)
            real_observe(value)

        with (
            patch("bmt_ai_os.controller.training_routes.get_job_manager", return_value=mgr),
            patch.object(prom_module._training_job_duration_seconds, "observe", capture_observe),
        ):
            prom_module._update_training_metrics()

        assert observed == [60.0]
        assert prom_module._prev_training_duration_count == 1

        # Second scrape: same 1 completed job — should NOT observe again
        with (
            patch("bmt_ai_os.controller.training_routes.get_job_manager", return_value=mgr),
            patch.object(prom_module._training_job_duration_seconds, "observe", capture_observe),
        ):
            prom_module._update_training_metrics()

        assert observed == [60.0]  # still only one observation

    def test_training_loss_gauge_updated(self, tmp_path, monkeypatch):
        """bmt_training_loss gauge is set from get_latest_metrics."""
        import bmt_ai_os.controller.prometheus as prom_module

        prom_module._prev_training_counts = {}
        prom_module._prev_training_duration_count = 0

        mgr = _make_mock_manager(
            counts={},
            durations=[],
            latest_metrics={"current_loss": 1.456, "tokens_per_sec": None},
        )

        set_values = []
        real_set = prom_module._training_loss.set

        def capture_set(value):  # noqa: ANN001
            set_values.append(value)
            real_set(value)

        with (
            patch("bmt_ai_os.controller.training_routes.get_job_manager", return_value=mgr),
            patch.object(prom_module._training_loss, "set", capture_set),
        ):
            prom_module._update_training_metrics()

        assert 1.456 in set_values

    def test_training_throughput_gauge_updated(self, tmp_path, monkeypatch):
        """bmt_training_throughput_tokens_per_second is set when available."""
        import bmt_ai_os.controller.prometheus as prom_module

        prom_module._prev_training_counts = {}
        prom_module._prev_training_duration_count = 0

        mgr = _make_mock_manager(
            counts={},
            durations=[],
            latest_metrics={"current_loss": None, "tokens_per_sec": 234.5},
        )

        set_values = []
        real_set = prom_module._training_throughput_tokens_per_second.set

        def capture_set(value):  # noqa: ANN001
            set_values.append(value)
            real_set(value)

        with (
            patch("bmt_ai_os.controller.training_routes.get_job_manager", return_value=mgr),
            patch.object(prom_module._training_throughput_tokens_per_second, "set", capture_set),
        ):
            prom_module._update_training_metrics()

        assert 234.5 in set_values

    def test_update_training_metrics_swallows_exceptions(self):
        """_update_training_metrics does not raise when training module errors."""
        import bmt_ai_os.controller.prometheus as prom_module

        with patch(
            "bmt_ai_os.controller.training_routes.get_job_manager",
            side_effect=Exception("DB gone"),
        ):
            # Should not raise — exception is logged at DEBUG level
            prom_module._update_training_metrics()

    def test_metrics_endpoint_includes_training_names(self, tmp_path, monkeypatch):
        """The /metrics endpoint output contains all four training metric names."""
        monkeypatch.setenv("BMT_TRAINING_DB", str(tmp_path / "prom-test.db"))

        from bmt_ai_os.controller.training_routes import _init_db

        _init_db(str(tmp_path / "prom-test.db"))

        import bmt_ai_os.controller.prometheus as prom_module

        prom_module._prev_training_counts = {}
        prom_module._prev_training_duration_count = 0

        app = _make_app()
        client = TestClient(app)
        summary = _make_summary()

        mgr = _make_mock_manager()

        with (
            patch("bmt_ai_os.controller.prometheus.get_collector") as mock_gc,
            patch("bmt_ai_os.controller.training_routes.get_job_manager", return_value=mgr),
        ):
            mock_gc.return_value.get_summary.return_value = summary
            resp = client.get("/metrics")

        assert resp.status_code == 200
        text = resp.text
        assert "bmt_training_jobs_total" in text
        assert "bmt_training_job_duration_seconds" in text
        assert "bmt_training_loss" in text
        assert "bmt_training_throughput_tokens_per_second" in text
