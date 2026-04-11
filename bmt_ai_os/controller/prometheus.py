"""Prometheus metrics export for BMT AI OS controller.

Exposes a ``/metrics`` endpoint that renders all controller metrics in the
Prometheus text exposition format (Content-Type: text/plain; version=0.0.4).

Metrics exported
----------------
- ``bmt_requests_total``         Counter   labels: provider, method, status
- ``bmt_request_latency_seconds`` Histogram labels: provider
- ``bmt_service_healthy``        Gauge     labels: service
- ``bmt_uptime_seconds``         Gauge

The module owns its own ``CollectorRegistry`` so it never collides with any
other prometheus_client usage in the same process (e.g. third-party libraries
that register to the default registry).
"""

from __future__ import annotations

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

# ---------------------------------------------------------------------------
# Private registry — isolated from the default prometheus_client registry
# ---------------------------------------------------------------------------

_registry = CollectorRegistry()

# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------

_requests_total = Counter(
    "bmt_requests_total",
    "Total number of API requests handled by the controller.",
    labelnames=["provider", "method", "status"],
    registry=_registry,
)

_request_latency_seconds = Histogram(
    "bmt_request_latency_seconds",
    "Request latency in seconds.",
    labelnames=["provider"],
    # Buckets cover the expected p50–p99 range for on-device LLM inference.
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=_registry,
)

_service_healthy = Gauge(
    "bmt_service_healthy",
    "1 if the service is currently healthy, 0 otherwise.",
    labelnames=["service"],
    registry=_registry,
)

_uptime_seconds = Gauge(
    "bmt_uptime_seconds",
    "Seconds since the MetricsCollector was initialised.",
    registry=_registry,
)

# ---------------------------------------------------------------------------
# Internal state: track which (provider, method) combos have been seen so
# that we can emit both "success" and "error" label combinations consistently.
# ---------------------------------------------------------------------------

_seen_provider_methods: set[tuple[str, str]] = set()

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter()


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics() -> Response:
    """Render controller metrics in Prometheus text exposition format.

    The handler reads the current snapshot from :func:`~.metrics.get_collector`
    and updates all metric objects before generating the output.  This approach
    keeps all metric state inside the existing ``MetricsCollector`` singleton
    so there is a single source of truth; prometheus_client objects are only
    used for serialisation.
    """
    summary = get_collector().get_summary()

    # --- uptime ---
    _uptime_seconds.set(summary["uptime_seconds"])

    # --- requests_total (provider × method × status) ---
    # The MetricsCollector tracks total requests per provider but not per
    # method/status label.  We reconstruct the counters from the available
    # data: per-provider totals are split into "success" and "error" buckets
    # using the global error count as a proportion.
    total: int = summary["total_requests"]
    error_count: int = summary["error_count"]
    success_count: int = total - error_count

    requests_by_provider: dict[str, int] = summary["requests_by_provider"]
    for provider, count in requests_by_provider.items():
        # Distribute errors proportionally across providers when we only have
        # a global error counter.  For providers with zero requests the counts
        # are zero; this avoids division-by-zero.
        if total > 0:
            provider_errors = round(error_count * count / total)
            provider_successes = count - provider_errors
        else:
            provider_errors = 0
            provider_successes = 0

        _requests_total.labels(provider=provider, method="POST", status="success")._value.set(
            float(provider_successes)
        )
        _requests_total.labels(provider=provider, method="POST", status="error")._value.set(
            float(provider_errors)
        )
        _seen_provider_methods.add((provider, "POST"))

    # Ensure every previously-seen (provider, method) pair has an entry even
    # if the provider has dropped to zero requests in a subsequent snapshot.
    for provider, method in _seen_provider_methods:
        if provider not in requests_by_provider:
            _requests_total.labels(provider=provider, method=method, status="success")
            _requests_total.labels(provider=provider, method=method, status="error")

    # --- request_latency_seconds ---
    # MetricsCollector keeps a rolling window of latencies in milliseconds.
    # We expose the aggregate via the Histogram's sum/count which prometheus_client
    # allows us to set directly on the underlying _sum/_count attributes.
    avg_latency_ms: float | None = summary["avg_latency_ms"]
    if avg_latency_ms is not None and total > 0:
        avg_latency_s = avg_latency_ms / 1000.0
        # Reconstruct approximate sum from average × count (best we can do
        # without storing every individual latency per provider).
        for provider, count in requests_by_provider.items():
            hist = _request_latency_seconds.labels(provider=provider)
            hist._sum.set(avg_latency_s * count)
            hist._count.set(float(count))

    # --- service_healthy ---
    health_history: dict[str, list] = summary["health_check_history"]
    for service, history in health_history.items():
        if history:
            latest_healthy: bool = history[-1].get("healthy", False)
            _service_healthy.labels(service=service).set(1.0 if latest_healthy else 0.0)
        else:
            _service_healthy.labels(service=service).set(0.0)

    output = generate_latest(_registry)
    return Response(content=output, media_type=CONTENT_TYPE_LATEST)
