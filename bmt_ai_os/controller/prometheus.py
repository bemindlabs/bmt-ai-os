"""Prometheus metrics export for BMT AI OS controller.

Exposes a ``/metrics`` endpoint that renders all controller metrics in the
Prometheus text exposition format (Content-Type: text/plain; version=0.0.4).

Metrics exported
----------------
Request metrics:
- ``bmt_requests_total``              Counter   labels: endpoint, method, status_code
- ``bmt_request_latency_seconds``     Histogram labels: endpoint, method
- ``bmt_request_errors_total``        Counter   labels: endpoint, method

Provider metrics:
- ``bmt_provider_requests_total``     Counter   labels: provider, status
- ``bmt_provider_latency_seconds``    Histogram labels: provider
- ``bmt_provider_tokens_per_second``  Gauge     labels: provider
- ``bmt_provider_circuit_state``      Gauge     labels: provider

System metrics:
- ``bmt_system_cpu_usage_percent``    Gauge
- ``bmt_system_memory_usage_bytes``   Gauge
- ``bmt_system_memory_total_bytes``   Gauge
- ``bmt_system_disk_usage_bytes``     Gauge
- ``bmt_system_disk_total_bytes``     Gauge
- ``bmt_system_disk_usage_percent``   Gauge

Health check metrics:
- ``bmt_service_healthy``             Gauge     labels: service
- ``bmt_service_response_time_ms``    Gauge     labels: service

Controller metrics:
- ``bmt_uptime_seconds``              Gauge
- ``bmt_error_rate``                  Gauge

The module owns its own ``CollectorRegistry`` so it never collides with any
other prometheus_client usage in the same process (e.g. third-party libraries
that register to the default registry).

Design note on counters/histograms
-----------------------------------
The MetricsCollector stores *cumulative* totals, not per-scrape deltas.
To drive Prometheus Counters (which must only increase) we track the last
exported value in ``_prev_*`` dicts and call ``.inc(delta)`` on each scrape.
For Histograms we use ``.observe()`` with a single synthetic observation
equal to the average latency — this keeps bucket distributions approximate
but avoids storing every individual latency.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from .metrics import get_collector

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Private registry — isolated from the default prometheus_client registry
# ---------------------------------------------------------------------------

_registry = CollectorRegistry()

# ---------------------------------------------------------------------------
# Request metrics
# ---------------------------------------------------------------------------

_requests_total = Counter(
    "bmt_requests_total",
    "Total number of API requests handled by the controller.",
    labelnames=["endpoint", "method", "status_code"],
    registry=_registry,
)

_request_latency_seconds = Histogram(
    "bmt_request_latency_seconds",
    "Request latency in seconds.",
    labelnames=["endpoint", "method"],
    # Buckets cover the expected p50–p99 range for on-device LLM inference.
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=_registry,
)

_request_errors_total = Counter(
    "bmt_request_errors_total",
    "Total number of failed API requests.",
    labelnames=["endpoint", "method"],
    registry=_registry,
)

# ---------------------------------------------------------------------------
# Provider metrics
# ---------------------------------------------------------------------------

_provider_requests_total = Counter(
    "bmt_provider_requests_total",
    "Total number of requests sent to each LLM provider.",
    labelnames=["provider", "status"],
    registry=_registry,
)

_provider_latency_seconds = Histogram(
    "bmt_provider_latency_seconds",
    "Provider inference latency in seconds.",
    labelnames=["provider"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
    registry=_registry,
)

_provider_tokens_per_second = Gauge(
    "bmt_provider_tokens_per_second",
    "Estimated token throughput in tokens per second for each provider.",
    labelnames=["provider"],
    registry=_registry,
)

# Circuit breaker state encoded as numeric value:
# 0 = closed (healthy), 1 = half_open (recovering), 2 = open (unhealthy)
_provider_circuit_state = Gauge(
    "bmt_provider_circuit_state",
    "Circuit breaker state for the provider (0=closed, 1=half_open, 2=open).",
    labelnames=["provider"],
    registry=_registry,
)

# ---------------------------------------------------------------------------
# System metrics
# ---------------------------------------------------------------------------

_system_cpu_usage_percent = Gauge(
    "bmt_system_cpu_usage_percent",
    "Current CPU utilisation percentage (0–100).",
    registry=_registry,
)

_system_memory_usage_bytes = Gauge(
    "bmt_system_memory_usage_bytes",
    "Resident memory used by the process and its children, in bytes.",
    registry=_registry,
)

_system_memory_total_bytes = Gauge(
    "bmt_system_memory_total_bytes",
    "Total physical memory available on the host, in bytes.",
    registry=_registry,
)

_system_disk_usage_bytes = Gauge(
    "bmt_system_disk_usage_bytes",
    "Disk space used on the root filesystem, in bytes.",
    registry=_registry,
)

_system_disk_total_bytes = Gauge(
    "bmt_system_disk_total_bytes",
    "Total capacity of the root filesystem, in bytes.",
    registry=_registry,
)

_system_disk_usage_percent = Gauge(
    "bmt_system_disk_usage_percent",
    "Disk usage percentage on the root filesystem (0–100).",
    registry=_registry,
)

# ---------------------------------------------------------------------------
# Health check metrics
# ---------------------------------------------------------------------------

_service_healthy = Gauge(
    "bmt_service_healthy",
    "1 if the service is currently healthy, 0 otherwise.",
    labelnames=["service"],
    registry=_registry,
)

_service_response_time_ms = Gauge(
    "bmt_service_response_time_ms",
    "Most recent health check response time in milliseconds.",
    labelnames=["service"],
    registry=_registry,
)

# ---------------------------------------------------------------------------
# Controller metrics
# ---------------------------------------------------------------------------

_uptime_seconds = Gauge(
    "bmt_uptime_seconds",
    "Seconds since the MetricsCollector was initialised.",
    registry=_registry,
)

_error_rate = Gauge(
    "bmt_error_rate",
    "Fraction of requests that resulted in an error (0.0–1.0).",
    registry=_registry,
)

# ---------------------------------------------------------------------------
# Previous-value tracking for delta-based Counter increments
# ---------------------------------------------------------------------------

# endpoint -> method -> {success, error} -> last exported count
_prev_endpoint_counts: dict[str, dict[str, dict[str, int]]] = {}

# provider -> {success, error} -> last exported count
_prev_provider_counts: dict[str, dict[str, int]] = {}

# provider -> last exported count (for histogram observations)
_prev_provider_total: dict[str, int] = {}

# ---------------------------------------------------------------------------
# System stats helper
# ---------------------------------------------------------------------------


def _collect_system_stats() -> dict:
    """Collect CPU, memory, and disk metrics using psutil if available.

    Returns a dict with keys: cpu_percent, memory_used, memory_total,
    disk_used, disk_total, disk_percent.  Missing values are None.
    """
    stats: dict = {
        "cpu_percent": None,
        "memory_used": None,
        "memory_total": None,
        "disk_used": None,
        "disk_total": None,
        "disk_percent": None,
    }
    try:
        import psutil  # optional dependency

        stats["cpu_percent"] = psutil.cpu_percent(interval=None)

        mem = psutil.virtual_memory()
        stats["memory_used"] = mem.used
        stats["memory_total"] = mem.total

        disk = psutil.disk_usage("/")
        stats["disk_used"] = disk.used
        stats["disk_total"] = disk.total
        stats["disk_percent"] = disk.percent
    except ImportError:
        logger.debug("psutil not installed — system metrics unavailable")
    except Exception as exc:
        logger.debug("Failed to collect system metrics: %s", exc)

    return stats


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter()

_CIRCUIT_STATE_VALUES = {
    "closed": 0.0,
    "half_open": 1.0,
    "open": 2.0,
}


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics() -> Response:
    """Render controller metrics in Prometheus text exposition format.

    Reads the current snapshot from :func:`~.metrics.get_collector` and
    updates all metric objects before generating the output.  This keeps
    all metric state inside the ``MetricsCollector`` singleton as a single
    source of truth; prometheus_client objects are used only for serialisation.

    Provider metrics and circuit breaker state are pulled from the provider
    router when it is available via the controller reference.
    """
    collector = get_collector()
    summary = collector.get_summary()

    # --- controller uptime & error rate ---
    _uptime_seconds.set(summary["uptime_seconds"])
    if summary["error_rate"] is not None:
        _error_rate.set(summary["error_rate"])

    # --- request metrics (endpoint × method × status_code) ---
    endpoint_stats: dict[str, dict] = summary.get("endpoint_stats", {})
    for endpoint, methods in endpoint_stats.items():
        for method, stats in methods.items():
            success_total: int = stats.get("success_count", 0)
            error_total: int = stats.get("error_count", 0)
            count_total: int = stats.get("count", 0)
            lat_sum_s: float = stats.get("latency_sum_s", 0.0)

            prev_ep = _prev_endpoint_counts.setdefault(endpoint, {}).setdefault(
                method, {"success": 0, "error": 0, "count": 0}
            )

            # Increment counters by the delta since last scrape
            delta_success = success_total - prev_ep["success"]
            delta_error = error_total - prev_ep["error"]
            delta_count = count_total - prev_ep["count"]

            if delta_success > 0:
                _requests_total.labels(endpoint=endpoint, method=method, status_code="2xx").inc(
                    delta_success
                )
            if delta_error > 0:
                _requests_total.labels(endpoint=endpoint, method=method, status_code="5xx").inc(
                    delta_error
                )
                _request_errors_total.labels(endpoint=endpoint, method=method).inc(delta_error)

            # Record latency observations for the new requests
            if delta_count > 0 and lat_sum_s > 0:
                avg_lat_s = lat_sum_s / count_total  # overall average
                for _ in range(delta_count):
                    _request_latency_seconds.labels(endpoint=endpoint, method=method).observe(
                        avg_lat_s
                    )

            prev_ep["success"] = success_total
            prev_ep["error"] = error_total
            prev_ep["count"] = count_total

    # --- legacy per-provider request counters (from MetricsCollector) ---
    total: int = summary["total_requests"]
    error_count: int = summary["error_count"]
    requests_by_provider: dict[str, int] = summary["requests_by_provider"]
    avg_latency_ms: float | None = summary["avg_latency_ms"]

    for provider, count in requests_by_provider.items():
        if total > 0:
            provider_errors = round(error_count * count / total)
            provider_successes = count - provider_errors
        else:
            provider_errors = 0
            provider_successes = count

        prev_p = _prev_provider_counts.setdefault(provider, {"success": 0, "error": 0})

        delta_succ = provider_successes - prev_p["success"]
        delta_err = provider_errors - prev_p["error"]

        if delta_succ > 0:
            _provider_requests_total.labels(provider=provider, status="success").inc(delta_succ)
        if delta_err > 0:
            _provider_requests_total.labels(provider=provider, status="error").inc(delta_err)

        prev_p["success"] = provider_successes
        prev_p["error"] = provider_errors

        # Provider latency histogram: observe for new requests since last scrape
        prev_tot = _prev_provider_total.get(provider, 0)
        delta_total = count - prev_tot
        if delta_total > 0 and avg_latency_ms is not None:
            avg_lat_s = avg_latency_ms / 1000.0
            for _ in range(delta_total):
                _provider_latency_seconds.labels(provider=provider).observe(avg_lat_s)
        _prev_provider_total[provider] = count

    # --- provider metrics from ProviderMetrics (tok/s, circuit state) ---
    provider_metrics: dict[str, dict] = summary.get("provider_metrics", {})
    circuit_states: dict[str, str] = summary.get("circuit_states", {})

    for provider, pm in provider_metrics.items():
        avg_ms = pm.get("avg_latency_ms", 0.0)
        # Rough tok/s estimate: assume ~50 tokens average per request at avg_latency_ms
        if avg_ms > 0:
            tps = 50.0 / (avg_ms / 1000.0)
        else:
            tps = 0.0
        _provider_tokens_per_second.labels(provider=provider).set(tps)

        state_str = circuit_states.get(provider, "closed")
        _provider_circuit_state.labels(provider=provider).set(
            _CIRCUIT_STATE_VALUES.get(state_str, 0.0)
        )

    # --- health check metrics ---
    health_history: dict[str, list] = summary["health_check_history"]
    for service, history in health_history.items():
        if history:
            latest = history[-1]
            is_healthy: bool = latest.get("healthy", False)
            response_time: float = latest.get("latency_ms", 0.0)
            _service_healthy.labels(service=service).set(1.0 if is_healthy else 0.0)
            _service_response_time_ms.labels(service=service).set(response_time)
        else:
            _service_healthy.labels(service=service).set(0.0)
            _service_response_time_ms.labels(service=service).set(0.0)

    # --- system metrics ---
    sys_stats = _collect_system_stats()
    if sys_stats["cpu_percent"] is not None:
        _system_cpu_usage_percent.set(sys_stats["cpu_percent"])
    if sys_stats["memory_used"] is not None:
        _system_memory_usage_bytes.set(float(sys_stats["memory_used"]))
    if sys_stats["memory_total"] is not None:
        _system_memory_total_bytes.set(float(sys_stats["memory_total"]))
    if sys_stats["disk_used"] is not None:
        _system_disk_usage_bytes.set(float(sys_stats["disk_used"]))
    if sys_stats["disk_total"] is not None:
        _system_disk_total_bytes.set(float(sys_stats["disk_total"]))
    if sys_stats["disk_percent"] is not None:
        _system_disk_usage_percent.set(sys_stats["disk_percent"])

    output = generate_latest(_registry)
    return Response(content=output, media_type=CONTENT_TYPE_LATEST)
