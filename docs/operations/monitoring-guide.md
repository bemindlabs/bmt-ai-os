# Monitoring Guide

This guide covers how to collect, visualise, and alert on BMT AI OS metrics using Prometheus and Grafana. Both tools run as additional Docker Compose services alongside the existing AI stack.

---

## Architecture Overview

```
Device
  ├── bmt-controller  :8080  — /metrics (Prometheus exposition)
  ├── bmt-ollama      :11434 — /metrics (via ollama-exporter sidecar)
  ├── bmt-chromadb    :8000  — /metrics (native Prometheus endpoint)
  ├── node-exporter   :9100  — host OS metrics (CPU, RAM, disk, temp)
  ├── prometheus      :9090  — scrapes all exporters, evaluates alerts
  └── grafana         :3000  — dashboards + alerting UI
```

All monitoring services run on the existing `bmt-ai-net` bridge network (`172.30.0.0/16`).

---

## 1. Deploy Monitoring Services

### 1.1 Docker Compose Overlay

Create `/opt/bmt_ai_os/monitoring/docker-compose.monitoring.yml`:

```yaml
# /opt/bmt_ai_os/monitoring/docker-compose.monitoring.yml
services:
  prometheus:
    image: prom/prometheus:v2.51.0
    container_name: bmt-prometheus
    restart: unless-stopped
    user: "65534:65534"
    volumes:
      - /opt/bmt_ai_os/monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - /opt/bmt_ai_os/monitoring/alerts.yml:/etc/prometheus/alerts.yml:ro
      - prometheus-data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=30d'
      - '--storage.tsdb.retention.size=5GB'
      - '--web.enable-lifecycle'
    ports:
      - "127.0.0.1:9090:9090"
    networks:
      - bmt-ai-net

  grafana:
    image: grafana/grafana:10.4.0
    container_name: bmt-grafana
    restart: unless-stopped
    user: "472:472"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD__FILE=/run/secrets/grafana_admin_password
      - GF_USERS_ALLOW_SIGN_UP=false
      - GF_SERVER_DOMAIN=localhost
      - GF_ANALYTICS_REPORTING_ENABLED=false
      - GF_ANALYTICS_CHECK_FOR_UPDATES=false
    volumes:
      - /opt/bmt_ai_os/monitoring/grafana/provisioning:/etc/grafana/provisioning:ro
      - grafana-data:/var/lib/grafana
    secrets:
      - grafana_admin_password
    ports:
      - "127.0.0.1:3000:3000"
    depends_on:
      - prometheus
    networks:
      - bmt-ai-net

  node-exporter:
    image: prom/node-exporter:v1.7.0
    container_name: bmt-node-exporter
    restart: unless-stopped
    pid: host
    network_mode: host
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'
      - '--path.rootfs=/rootfs'
      - '--collector.thermal_zone'
      - '--collector.hwmon'
      - '--collector.filesystem.mount-points-exclude=^/(dev|proc|sys|var/lib/docker)($|/)'

volumes:
  prometheus-data:
  grafana-data:

networks:
  bmt-ai-net:
    external: true

secrets:
  grafana_admin_password:
    file: /etc/bmt_ai_os/secrets/grafana_admin_password
```

### 1.2 Set the Grafana Admin Password

```bash
# Generate a strong password
GRAFANA_PASS=$(openssl rand -base64 24)
echo "$GRAFANA_PASS" | sudo tee /etc/bmt_ai_os/secrets/grafana_admin_password > /dev/null
sudo chmod 0600 /etc/bmt_ai_os/secrets/grafana_admin_password
echo "Grafana admin password: $GRAFANA_PASS"
```

### 1.3 Start Monitoring Services

```bash
docker compose \
  -f /opt/bmt_ai_os/ai-stack/docker-compose.yml \
  -f /opt/bmt_ai_os/monitoring/docker-compose.monitoring.yml \
  up -d prometheus grafana node-exporter
```

Verify:

```bash
docker ps --filter "name=bmt-prometheus" --filter "name=bmt-grafana" --filter "name=bmt-node-exporter"
curl -sf http://localhost:9090/-/ready
```

---

## 2. Prometheus Configuration

Create `/opt/bmt_ai_os/monitoring/prometheus.yml`:

```yaml
# /opt/bmt_ai_os/monitoring/prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  external_labels:
    device: '{{ env "HOSTNAME" }}'

rule_files:
  - /etc/prometheus/alerts.yml

scrape_configs:
  - job_name: 'bmt-controller'
    static_configs:
      - targets: ['bmt-controller:8080']
    metrics_path: /metrics

  - job_name: 'chromadb'
    static_configs:
      - targets: ['bmt-chromadb:8000']
    metrics_path: /metrics

  - job_name: 'node'
    static_configs:
      - targets: ['localhost:9100']

  - job_name: 'docker'
    static_configs:
      - targets: ['172.30.0.1:9323']   # Docker daemon metrics (enable in daemon.json)
```

Enable Docker daemon metrics by adding to `/etc/docker/daemon.json`:

```json
{
  "metrics-addr": "172.30.0.1:9323",
  "experimental": true
}
```

Then restart Docker: `sudo rc-service docker restart`

---

## 3. Alert Rules

Create `/opt/bmt_ai_os/monitoring/alerts.yml`:

```yaml
# /opt/bmt_ai_os/monitoring/alerts.yml
groups:
  - name: bmt-ai-os
    interval: 30s
    rules:
      # -----------------------------------------------------------------------
      # Memory
      # -----------------------------------------------------------------------
      - alert: HighMemoryUsage
        expr: (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) > 0.90
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Memory usage above 90%"
          description: "{{ $value | humanizePercentage }} of RAM in use. Consider evicting models."

      - alert: CriticalMemoryUsage
        expr: (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) > 0.97
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Memory usage critical (>97%)"
          description: "OOM kill imminent. Immediate action required."

      # -----------------------------------------------------------------------
      # CPU Temperature (thermal throttling)
      # -----------------------------------------------------------------------
      - alert: ThermalWarning
        expr: node_hwmon_temp_celsius{chip=~".*thermal.*"} > 75
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "CPU temperature above 75°C"
          description: "Temperature {{ $value }}°C. Inference may be throttled."

      - alert: ThermalCritical
        expr: node_hwmon_temp_celsius{chip=~".*thermal.*"} > 85
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "CPU temperature above 85°C"
          description: "Temperature {{ $value }}°C. Throttling active. Check cooling."

      # -----------------------------------------------------------------------
      # Disk
      # -----------------------------------------------------------------------
      - alert: DiskSpaceLow
        expr: (1 - (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})) > 0.80
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Disk usage above 80%"
          description: "{{ $value | humanizePercentage }} of root filesystem used."

      - alert: ModelStorageLow
        expr: node_filesystem_avail_bytes{mountpoint="/data"} < 5e9
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Model storage below 5 GB"
          description: "Only {{ $value | humanize1024 }}B free in /data. Evict unused models."

      # -----------------------------------------------------------------------
      # Service health
      # -----------------------------------------------------------------------
      - alert: OllamaDown
        expr: absent(up{job="bmt-controller"}) or up{job="bmt-controller"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "BMT Controller is unreachable"
          description: "The controller health endpoint has not responded for 1 minute."

      - alert: ContainerRestarting
        expr: rate(container_last_seen{name=~"bmt-.*"}[5m]) == 0
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Container {{ $labels.name }} appears to have restarted"
```

Reload Prometheus after changing alert rules (no restart required):

```bash
curl -X POST http://localhost:9090/-/reload
```

---

## 4. Grafana Setup

### 4.1 Provision the Prometheus Data Source

Create `/opt/bmt_ai_os/monitoring/grafana/provisioning/datasources/prometheus.yml`:

```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    url: http://bmt-prometheus:9090
    access: proxy
    isDefault: true
    jsonData:
      timeInterval: 15s
```

### 4.2 Access Grafana

Forward port 3000 from your workstation:

```bash
ssh -L 3000:localhost:3000 bmt@<device-ip>
```

Open `http://localhost:3000` in your browser. Login: `admin` / `<grafana_admin_password from secrets>`.

### 4.3 Import Pre-built Dashboards

In Grafana, go to **Dashboards → Import**:

| Dashboard | Grafana ID | Purpose |
|-----------|-----------|---------|
| Node Exporter Full | 1860 | Host OS metrics (CPU, RAM, disk, temperature) |
| Docker Container Metrics | 193 | Per-container resource usage |

For BMT-specific dashboards, import from `/opt/bmt_ai_os/monitoring/grafana/dashboards/` once available.

### 4.4 Key Panels to Build

For a BMT AI OS overview dashboard, create panels for:

**Inference Performance**
```promql
# Requests per second to controller
rate(http_requests_total{job="bmt-controller"}[1m])

# P95 latency
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{job="bmt-controller"}[5m]))
```

**Memory Pressure**
```promql
# Available RAM in GB
node_memory_MemAvailable_bytes / 1e9

# Memory used by Ollama container
container_memory_usage_bytes{name="bmt-ollama"} / 1e9
```

**Thermal Status**
```promql
# Per-zone temperature
node_hwmon_temp_celsius
```

**Model Cache Hit Rate** (when metric is exposed by controller):
```promql
rate(bmt_model_cache_hits_total[5m]) / rate(bmt_model_cache_requests_total[5m])
```

---

## 5. Alert Notification Channels

Configure Grafana alert contact points at **Alerting → Contact Points**:

**Webhook (generic)**

```json
{
  "url": "https://your-webhook.example.com/alerts",
  "httpMethod": "POST"
}
```

**Email**

Set `GF_SMTP_*` environment variables in the Grafana container:

```yaml
environment:
  - GF_SMTP_ENABLED=true
  - GF_SMTP_HOST=smtp.your-org.com:587
  - GF_SMTP_FROM_ADDRESS=bmt-monitor@your-org.com
```

---

## 6. Verifying Metrics Collection

```bash
# Check all scrape targets are UP
curl -sf 'http://localhost:9090/api/v1/targets' | python3 -m json.tool | grep '"health"'

# Query memory available
curl -sg 'http://localhost:9090/api/v1/query?query=node_memory_MemAvailable_bytes' \
  | python3 -m json.tool

# Query CPU temperature
curl -sg 'http://localhost:9090/api/v1/query?query=node_hwmon_temp_celsius' \
  | python3 -m json.tool
```

All targets should show `"health": "up"`. If a target shows `"health": "down"`, check container logs:

```bash
docker logs bmt-prometheus --tail 50
```

---

## 7. Retention and Storage

Prometheus retains 30 days of data by default (configured via `--storage.tsdb.retention.time`) with a 5 GB cap. Adjust in `docker-compose.monitoring.yml` for your storage constraints:

| Device RAM | Recommended Retention | Storage Budget |
|-----------|----------------------|---------------|
| 8 GB | 14 days | 2 GB |
| 16 GB | 30 days | 5 GB |
| 32 GB | 90 days | 15 GB |

---

## Related Guides

- [Deployment Runbook](deployment-runbook.md) — first-boot setup
- [Troubleshooting](troubleshooting.md) — OOM, thermal, and inference issues
- [Backup and Restore](backup-restore.md) — backing up Prometheus data
