"""Load tests for BMT AI OS controller API.

Tests concurrent request handling, throughput, and latency under load.
Uses threading to simulate multiple simultaneous clients hitting the
FastAPI controller via TestClient.

Run: python -m pytest tests/load/ -v --tb=short
"""

from __future__ import annotations

import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def load_env(tmp_path_factory) -> dict[str, str]:
    tmp = tmp_path_factory.mktemp("load")
    return {
        "BMT_AUTH_DB": str(tmp / "auth.db"),
        "BMT_JWT_SECRET": "load-test-secret-key-at-least-32-bytes!!",
        "BMT_PLUGIN_STATE": str(tmp / "plugins.json"),
        "BMT_PLUGIN_DIR": str(tmp / "plugins"),
        "BMT_LOG_FORMAT": "text",
    }


@pytest.fixture(scope="module")
def load_client(load_env: dict[str, str], tmp_path_factory) -> TestClient:
    tmp = tmp_path_factory.mktemp("load_plugins")
    load_env["BMT_PLUGIN_DIR"] = str(tmp)

    import bmt_ai_os.controller.auth as auth_mod

    orig_store = getattr(auth_mod, "_default_store", None)

    with patch.dict(os.environ, load_env):
        auth_mod._default_store = None
        from bmt_ai_os.controller.api import app

        client = TestClient(app, raise_server_exceptions=False)
        yield client

    auth_mod._default_store = orig_store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _measure_requests(
    client: TestClient,
    method: str,
    path: str,
    n: int,
    concurrency: int,
    **kwargs,
) -> dict:
    """Fire *n* requests at *path* with *concurrency* threads.

    Returns a dict with latency stats and error count.
    """
    latencies: list[float] = []
    errors = 0
    status_codes: dict[int, int] = {}

    def _do_request():
        t0 = time.perf_counter()
        if method == "GET":
            resp = client.get(path, **kwargs)
        elif method == "POST":
            resp = client.post(path, **kwargs)
        else:
            raise ValueError(f"Unsupported method: {method}")
        elapsed = time.perf_counter() - t0
        return resp.status_code, elapsed

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(_do_request) for _ in range(n)]
        for f in as_completed(futures):
            code, elapsed = f.result()
            latencies.append(elapsed)
            status_codes[code] = status_codes.get(code, 0) + 1
            if code >= 500:
                errors += 1

    latencies.sort()
    return {
        "total_requests": n,
        "concurrency": concurrency,
        "errors": errors,
        "status_codes": status_codes,
        "min_ms": round(latencies[0] * 1000, 2),
        "max_ms": round(latencies[-1] * 1000, 2),
        "mean_ms": round(statistics.mean(latencies) * 1000, 2),
        "median_ms": round(statistics.median(latencies) * 1000, 2),
        "p95_ms": round(latencies[int(len(latencies) * 0.95)] * 1000, 2),
        "p99_ms": round(latencies[int(len(latencies) * 0.99)] * 1000, 2),
        "total_time_s": round(sum(latencies), 3),
        "rps": round(n / max(sum(latencies) / concurrency, 0.001), 1),
    }


# ---------------------------------------------------------------------------
# 1. Health Endpoint Load
# ---------------------------------------------------------------------------


class TestHealthzLoad:
    """Load test /healthz — the lightest endpoint, baseline performance."""

    def test_healthz_100_sequential(self, load_client: TestClient):
        result = _measure_requests(load_client, "GET", "/healthz", n=100, concurrency=1)
        assert result["errors"] == 0
        assert result["p95_ms"] < 500  # generous for TestClient overhead

    def test_healthz_200_concurrent_10(self, load_client: TestClient):
        result = _measure_requests(load_client, "GET", "/healthz", n=200, concurrency=10)
        assert result["errors"] == 0
        assert result["p99_ms"] < 1000

    def test_healthz_500_concurrent_20(self, load_client: TestClient):
        result = _measure_requests(load_client, "GET", "/healthz", n=500, concurrency=20)
        assert result["errors"] == 0


# ---------------------------------------------------------------------------
# 2. Status Endpoint Load
# ---------------------------------------------------------------------------


class TestStatusLoad:
    """Load test /api/v1/status — includes version, uptime, services."""

    def test_status_100_concurrent_10(self, load_client: TestClient):
        result = _measure_requests(load_client, "GET", "/api/v1/status", n=100, concurrency=10)
        assert result["errors"] == 0

    def test_status_200_concurrent_20(self, load_client: TestClient):
        result = _measure_requests(load_client, "GET", "/api/v1/status", n=200, concurrency=20)
        assert result["errors"] == 0


# ---------------------------------------------------------------------------
# 3. Metrics Endpoint Load
# ---------------------------------------------------------------------------


class TestMetricsLoad:
    """Load test /metrics — Prometheus scrape simulation."""

    def test_metrics_100_concurrent_5(self, load_client: TestClient):
        """Simulate 5 Prometheus scrapers hitting /metrics simultaneously."""
        result = _measure_requests(load_client, "GET", "/metrics", n=100, concurrency=5)
        assert result["errors"] == 0

    def test_metrics_summary_100(self, load_client: TestClient):
        result = _measure_requests(load_client, "GET", "/api/v1/metrics", n=100, concurrency=10)
        assert result["errors"] == 0


# ---------------------------------------------------------------------------
# 4. Fleet Endpoint Load
# ---------------------------------------------------------------------------


class TestFleetLoad:
    """Load test fleet endpoints — heartbeat burst simulation."""

    def test_fleet_register_50_devices(self, load_client: TestClient):
        """Register 50 devices concurrently."""
        errors = 0
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = []
            for i in range(50):
                futures.append(
                    pool.submit(
                        load_client.post,
                        "/api/v1/fleet/register",
                        json={
                            "device_id": f"load-device-{i:03d}",
                            "hostname": f"node-{i:03d}",
                            "hardware": {"board": "rk3588", "memory_mb": 8192},
                        },
                    )
                )
            for f in as_completed(futures):
                resp = f.result()
                if resp.status_code >= 500:
                    errors += 1

        assert errors == 0

        # Verify all registered
        resp = load_client.get("/api/v1/fleet/summary")
        assert resp.status_code == 200
        assert resp.json()["total_devices"] >= 50

    def test_fleet_heartbeat_burst_200(self, load_client: TestClient):
        """Simulate 200 heartbeats from 50 devices — 4 heartbeats each."""
        from datetime import datetime, timezone

        errors = 0
        with ThreadPoolExecutor(max_workers=20) as pool:
            futures = []
            for i in range(200):
                device_id = f"load-device-{i % 50:03d}"
                futures.append(
                    pool.submit(
                        load_client.post,
                        "/api/v1/fleet/heartbeat",
                        json={
                            "device_id": device_id,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "cpu_percent": 20.0 + (i % 60),
                            "memory_percent": 30.0 + (i % 40),
                            "loaded_models": ["qwen2.5-coder:1.5b"],
                        },
                    )
                )
            for f in as_completed(futures):
                resp = f.result()
                if resp.status_code >= 500:
                    errors += 1

        assert errors == 0

    def test_fleet_list_under_load(self, load_client: TestClient):
        """List devices while heartbeats are flowing."""
        result = _measure_requests(
            load_client, "GET", "/api/v1/fleet/devices", n=50, concurrency=10
        )
        assert result["errors"] == 0


# ---------------------------------------------------------------------------
# 5. Mixed Workload
# ---------------------------------------------------------------------------


class TestMixedWorkload:
    """Simulate realistic mixed traffic: health checks + status + metrics + fleet."""

    def test_mixed_500_requests(self, load_client: TestClient):
        """500 requests across 4 endpoint types, 20 threads."""
        endpoints = [
            ("GET", "/healthz"),
            ("GET", "/api/v1/status"),
            ("GET", "/metrics"),
            ("GET", "/api/v1/fleet/summary"),
        ]
        errors = 0
        latencies: list[float] = []

        def _do_request(method, path):
            t0 = time.perf_counter()
            if method == "GET":
                resp = load_client.get(path)
            else:
                resp = load_client.post(path)
            elapsed = time.perf_counter() - t0
            return resp.status_code, elapsed

        with ThreadPoolExecutor(max_workers=20) as pool:
            futures = []
            for i in range(500):
                method, path = endpoints[i % len(endpoints)]
                futures.append(pool.submit(_do_request, method, path))
            for f in as_completed(futures):
                code, elapsed = f.result()
                latencies.append(elapsed)
                if code >= 500:
                    errors += 1

        latencies.sort()
        p99 = latencies[int(len(latencies) * 0.99)] * 1000

        assert errors == 0, f"Got {errors} server errors under mixed load"
        # TestClient is in-process so latencies are low; fail on extreme outliers
        assert p99 < 2000, f"p99 latency {p99:.0f}ms exceeds 2s threshold"


# ---------------------------------------------------------------------------
# 6. Sustained Load
# ---------------------------------------------------------------------------


class TestSustainedLoad:
    """Sustained request rate over a longer window."""

    def test_sustained_1000_requests(self, load_client: TestClient):
        """1000 requests at concurrency 10 — verify zero errors and stable latency."""
        result = _measure_requests(load_client, "GET", "/healthz", n=1000, concurrency=10)
        assert result["errors"] == 0

        # Verify latency doesn't degrade: p99 should be < 5x median
        assert result["p99_ms"] < result["median_ms"] * 5, (
            f"Latency degradation: p99={result['p99_ms']}ms, median={result['median_ms']}ms"
        )
