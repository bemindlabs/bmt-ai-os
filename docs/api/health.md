# Health & Status API

The controller exposes health and observability endpoints for monitoring and orchestration.

## Liveness Check

### `GET /healthz`

Returns `200 OK` if the controller process is running. Use this for load balancer health checks.

```bash
curl http://localhost:8080/healthz
```

```json
{"status": "ok"}
```

## System Status

### `GET /api/v1/status`

Returns the controller version, uptime, and health status of all managed services.

```bash
curl http://localhost:8080/api/v1/status
```

```json
{
  "version": "2026.4.11",
  "status": "running",
  "uptime_seconds": 3621.4,
  "services": [
    {
      "name": "ollama",
      "status": "healthy",
      "container": "bmt-ollama",
      "port": 11434
    },
    {
      "name": "chromadb",
      "status": "healthy",
      "container": "bmt-chromadb",
      "port": 8000
    }
  ]
}
```

## Metrics Summary

### `GET /api/v1/metrics`

Returns request counters and health-check metrics collected by the controller.

```bash
curl http://localhost:8080/api/v1/metrics
```

```json
{
  "requests_total": 1024,
  "requests_success": 1018,
  "requests_error": 6,
  "health_checks_total": 120,
  "health_checks_failed": 2
}
```

## Prometheus Metrics

### `GET /metrics`

Prometheus-format metrics for scraping with Prometheus, Grafana, or similar tools.

```bash
curl http://localhost:8080/metrics
```

```
# HELP bmt_requests_total Total number of API requests
# TYPE bmt_requests_total counter
bmt_requests_total{status="success"} 1018
bmt_requests_total{status="error"} 6
...
```

## Service Health Check URLs

The controller polls these endpoints to determine service health:

| Service | Health URL | Interval |
|---------|-----------|----------|
| Ollama | `GET http://localhost:11434/api/tags` | 30s |
| ChromaDB | `GET http://localhost:8000/api/v1/heartbeat` | 30s |

Failed services are automatically restarted by the controller (up to `max_restarts` times, default 3).
