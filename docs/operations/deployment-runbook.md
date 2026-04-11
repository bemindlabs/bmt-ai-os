# BMT AI OS — Production Deployment Runbook

Version: v2026.4.11 | Audience: Platform / DevOps Engineers

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Bare-Metal ARM64 Deployment](#2-bare-metal-arm64-deployment)
3. [Docker Compose Deployment](#3-docker-compose-deployment)
4. [Fleet Deployment](#4-fleet-deployment)
5. [Post-Deployment Verification Checklist](#5-post-deployment-verification-checklist)
6. [Rollback Procedure](#6-rollback-procedure)
7. [Monitoring Setup](#7-monitoring-setup)
8. [Troubleshooting Common Issues](#8-troubleshooting-common-issues)

---

## 1. Prerequisites

### 1.1 Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| Architecture | ARM64 (aarch64) | ARM64 (aarch64) |
| CPU cores | 4 | 8+ |
| RAM | 8 GB | 16 GB+ |
| Disk (OS) | 32 GB | 64 GB+ |
| Disk (models) | 20 GB | 100 GB+ |

Supported boards:
- Apple Silicon (M-series) — CPU-only inference
- NVIDIA Jetson Orin Nano Super — CUDA NPU passthrough
- Rockchip RK3588 — RKNN NPU passthrough
- Raspberry Pi 5 + Hailo AI HAT+ — HailoRT NPU passthrough

### 1.2 Network Requirements

- Outbound HTTPS (port 443) required for initial model downloads (can be firewalled after setup)
- Internal subnet: `172.30.0.0/16` (bmt-ai-net bridge) — must not conflict with existing VLANs
- Controller API port: `8080` (HTTP) or `8443` (HTTPS/mTLS)
- Fleet heartbeat: agents POST to `http://<fleet-server>:8080/api/v1/fleet/heartbeat`

Firewall rules (incoming on the controller host):

```
ACCEPT tcp 8080   # Controller API (HTTP)
ACCEPT tcp 8443   # Controller API (HTTPS, if TLS enabled)
ACCEPT tcp 9090   # Dashboard (Web UI)
DROP   tcp 11434  # Ollama — internal only, never expose externally
DROP   tcp 8000   # ChromaDB — internal only, never expose externally
```

### 1.3 DNS Requirements

- Point `<hostname>.local` (mDNS) or your FQDN to the controller host IP
- For fleet deployments, a stable DNS name for the fleet controller is required
- mTLS deployments require a CA-signed certificate with the correct SAN

### 1.4 Software Dependencies

```bash
# Verify on the target host before deployment
docker --version          # Docker 24.0+
docker compose version    # Compose v2.20+
python3 --version         # Python 3.11+
curl --version            # Any recent version
```

---

## 2. Bare-Metal ARM64 Deployment

### 2.1 Flash the OS Image

```bash
# Download the release image
curl -LO https://github.com/bemind/ai-first-os/releases/download/v2026.4.11/bmt-ai-os-arm64.img.zst

# Verify integrity
sha256sum bmt-ai-os-arm64.img.zst
# compare with SHA-256 from the release page

# Flash to storage (replace /dev/sdX with your device)
zstd -d bmt-ai-os-arm64.img.zst --stdout | sudo dd of=/dev/sdX bs=4M status=progress conv=fsync
sudo sync
```

### 2.2 First Boot Configuration

After flashing and booting:

```bash
# SSH in (default credentials — change immediately)
ssh bmt@<device-ip>
# default password: bmt (prompted to change on first login)

# Set required secrets
sudo tee /etc/bmt_ai_os/secrets.env > /dev/null <<'EOF'
BMT_JWT_SECRET=<generate with: openssl rand -hex 32>
BMT_API_KEY=<optional legacy key>
EOF
sudo chmod 600 /etc/bmt_ai_os/secrets.env
```

### 2.3 Configure the Controller

```bash
sudo cp /etc/bmt_ai_os/controller.yml.example /etc/bmt_ai_os/controller.yml
sudo nano /etc/bmt_ai_os/controller.yml
```

Minimum required changes:

```yaml
api_host: 0.0.0.0
api_port: 8080
log_level: INFO
log_file: /var/log/bmt-controller.log
```

### 2.4 Enable and Start Services

```bash
# Start the AI stack (Ollama + ChromaDB)
sudo rc-service bmt-ai-stack start
sudo rc-update add bmt-ai-stack default

# Start the controller
sudo rc-service bmt-controller start
sudo rc-update add bmt-controller default

# Pull the default model
curl -s http://localhost:11434/api/pull \
  -d '{"name":"qwen2.5-coder:7b"}' | jq .
```

### 2.5 Create the Initial Admin User

```bash
# On the controller host (first user automatically gets admin role)
curl -s -X POST http://localhost:8080/api/v1/auth/users \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<strong-password>","role":"admin"}' | jq .
```

---

## 3. Docker Compose Deployment

This method runs the full stack on any host with Docker (development, staging, cloud VM).

### 3.1 Clone and Configure

```bash
git clone https://github.com/bemind/ai-first-os.git
cd ai-first-os

# Copy and edit the environment file
cp .env.example .env
# Edit .env: set BMT_JWT_SECRET, BMT_API_KEY (optional)
```

### 3.2 Start the AI Stack

```bash
# Lite profile (4 GB RAM minimum)
docker compose -f bmt_ai_os/ai-stack/docker-compose.yml \
  --profile lite up -d

# Full profile (16 GB RAM recommended)
docker compose -f bmt_ai_os/ai-stack/docker-compose.yml \
  --profile full up -d
```

### 3.3 Start the Controller

```bash
BMT_COMPOSE_FILE=$(pwd)/bmt_ai_os/ai-stack/docker-compose.yml \
BMT_JWT_SECRET=$(openssl rand -hex 32) \
  python3 -m bmt_ai_os.controller.main
```

Or using Docker:

```bash
docker build -t bmt-ai-os .
docker run -d \
  --name bmt-controller \
  --network bmt-ai-net \
  -p 8080:8080 \
  -e BMT_JWT_SECRET="$(openssl rand -hex 32)" \
  bmt-ai-os
```

### 3.4 Verify the Stack

```bash
# Check all containers are running
docker compose -f bmt_ai_os/ai-stack/docker-compose.yml ps

# Health check
curl -s http://localhost:8080/healthz | jq .
# Expected: {"status":"ok"}

curl -s http://localhost:11434/api/tags | jq .models[].name
```

---

## 4. Fleet Deployment

Fleet deployment pushes configuration and models to multiple remote devices from a central controller.

### 4.1 Fleet Server Setup

The fleet server runs alongside the main controller. No extra process is needed — the `/api/v1/fleet/*` routes are part of the controller.

```yaml
# /etc/bmt_ai_os/controller.yml (fleet server)
api_host: 0.0.0.0
api_port: 8080
```

Ensure the fleet server is reachable from all edge devices on port 8080.

### 4.2 Device Agent Configuration

On each edge device:

```bash
# /etc/bmt_ai_os/agent.yml
fleet_server: http://fleet.example.com:8080
device_id: device-001          # unique per device
heartbeat_interval: 60         # seconds
offline_queue_size: 100        # commands to buffer while offline
```

```bash
# Start the agent
sudo rc-service bmt-fleet-agent start
sudo rc-update add bmt-fleet-agent default
```

### 4.3 Bulk Model Deployment

```bash
# Push a model pull command to all registered devices
curl -s -X POST http://fleet.example.com:8080/api/v1/fleet/command \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "target": "all",
    "action": "pull-model",
    "params": {"model": "qwen2.5-coder:7b"}
  }' | jq .
```

### 4.4 Staged Rollout

```bash
# Deploy to a subset first (canary)
curl -s -X POST http://fleet.example.com:8080/api/v1/fleet/command \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "target": ["device-001", "device-002"],
    "action": "update",
    "params": {"version": "2026.4.11"}
  }' | jq .

# Monitor health of canary devices
curl -s http://fleet.example.com:8080/api/v1/fleet/devices | \
  jq '.[] | select(.device_id | test("device-00[12]")) | {id: .device_id, status: .status}'

# Roll out to remaining devices after 30-minute soak
curl -s -X POST http://fleet.example.com:8080/api/v1/fleet/command \
  -H "Authorization: Bearer <admin-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "target": "remaining",
    "action": "update",
    "params": {"version": "2026.4.11"}
  }' | jq .
```

---

## 5. Post-Deployment Verification Checklist

Run through this checklist after every deployment.

### 5.1 Service Health

```bash
# Controller
curl -sf http://localhost:8080/healthz && echo "PASS: controller" || echo "FAIL: controller"

# Ollama
curl -sf http://localhost:11434/api/tags && echo "PASS: ollama" || echo "FAIL: ollama"

# ChromaDB
curl -sf http://localhost:8000/api/v1/heartbeat && echo "PASS: chromadb" || echo "FAIL: chromadb"
```

### 5.2 Authentication

```bash
# Obtain a token
TOKEN=$(curl -s -X POST http://localhost:8080/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<password>"}' | jq -r .access_token)

# Verify token
curl -s http://localhost:8080/api/v1/auth/me \
  -H "Authorization: Bearer $TOKEN" | jq .
# Expected: {"username":"admin","role":"admin"}
```

### 5.3 Inference

```bash
# Basic completion
curl -s http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen2.5-coder:7b",
    "messages": [{"role":"user","content":"Say hello in one sentence."}]
  }' | jq .choices[0].message.content
```

### 5.4 RAG Pipeline

```bash
curl -s -X POST http://localhost:8080/api/v1/query \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"question":"What is BMT AI OS?","collection":"default"}' | jq .answer
```

### 5.5 Metrics Endpoint

```bash
curl -sf http://localhost:8080/metrics | grep -c "^bmt_" && echo "PASS: prometheus metrics"
```

### 5.6 Full Verification Script

```bash
#!/bin/bash
set -euo pipefail
HOST=${1:-localhost}
PORT=${2:-8080}
BASE="http://${HOST}:${PORT}"
PASS=0; FAIL=0

check() {
  if eval "$2" &>/dev/null; then
    echo "  [PASS] $1"; ((PASS++))
  else
    echo "  [FAIL] $1"; ((FAIL++))
  fi
}

echo "=== BMT AI OS Post-Deployment Verification ==="
check "Controller /healthz"   "curl -sf ${BASE}/healthz"
check "Ollama reachable"      "curl -sf http://${HOST}:11434/api/tags"
check "ChromaDB reachable"    "curl -sf http://${HOST}:8000/api/v1/heartbeat"
check "Prometheus metrics"    "curl -sf ${BASE}/metrics | grep -q bmt_"
check "API status endpoint"   "curl -sf ${BASE}/api/v1/status"

echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
[[ $FAIL -eq 0 ]] && exit 0 || exit 1
```

---

## 6. Rollback Procedure

### 6.1 OTA A/B Slot Rollback (bare metal)

BMT AI OS uses A/B partition slots. If the new slot is unhealthy, roll back:

```bash
# Check current slot
cat /proc/cmdline | grep -oP 'root=\S+'

# Mark current slot as bad and reboot to previous slot
bmt-ota rollback
# or manually:
fw_setenv upgrade_available 0
fw_setenv bootcount 0
reboot
```

### 6.2 Docker Compose Rollback

```bash
# Tag the running image before upgrading
docker tag bmt-ai-os bmt-ai-os:previous

# After a failed upgrade, restore
docker stop bmt-controller
docker run -d \
  --name bmt-controller \
  --network bmt-ai-net \
  -p 8080:8080 \
  -e BMT_JWT_SECRET="${BMT_JWT_SECRET}" \
  bmt-ai-os:previous

# Roll back the AI stack
docker compose -f bmt_ai_os/ai-stack/docker-compose.yml down
git checkout v2026.4.10  # previous release tag
docker compose -f bmt_ai_os/ai-stack/docker-compose.yml up -d
```

### 6.3 Fleet Rollback

```bash
# Send rollback command to affected devices
curl -s -X POST http://fleet.example.com:8080/api/v1/fleet/command \
  -H "Authorization: Bearer <admin-token>" \
  -H 'Content-Type: application/json' \
  -d '{
    "target": "all",
    "action": "update",
    "params": {"version": "2026.4.10"}
  }' | jq .
```

### 6.4 Database Recovery

Auth and fleet SQLite databases default to `/tmp/bmt-auth.db` and `/tmp/bmt-fleet.db`. For production, set `BMT_AUTH_DB` and `BMT_FLEET_DB` to a persistent path and back up regularly:

```bash
# Backup
cp /var/lib/bmt/auth.db /var/lib/bmt/auth.db.$(date +%Y%m%d%H%M%S)

# Restore
cp /var/lib/bmt/auth.db.20260411120000 /var/lib/bmt/auth.db
sudo rc-service bmt-controller restart
```

---

## 7. Monitoring Setup

### 7.1 Prometheus Configuration

Add the controller scrape target to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: bmt-ai-os
    static_configs:
      - targets:
          - localhost:8080   # controller /metrics
    metrics_path: /metrics
    scrape_interval: 15s
    scrape_timeout: 10s
```

Key metrics exposed:

| Metric | Type | Description |
|--------|------|-------------|
| `bmt_requests_total` | Counter | HTTP requests by method, path, status |
| `bmt_request_duration_seconds` | Histogram | Request latency |
| `bmt_health_checks_total` | Counter | Health check results by service |
| `bmt_provider_requests_total` | Counter | LLM provider calls |
| `bmt_provider_errors_total` | Counter | LLM provider errors |

### 7.2 Grafana Dashboard

Import the bundled dashboard from `bmt_ai_os/runtime/monitoring/`:

```bash
# Via Grafana API
curl -s -X POST http://grafana:3000/api/dashboards/import \
  -H 'Content-Type: application/json' \
  -u admin:admin \
  -d @bmt_ai_os/runtime/monitoring/grafana-dashboard.json
```

### 7.3 Alerting Rules

Example Prometheus alerting rules (adapt thresholds to your SLA):

```yaml
# bmt_ai_os/runtime/monitoring/alerts.yml
groups:
  - name: bmt-ai-os
    rules:
      - alert: ControllerDown
        expr: up{job="bmt-ai-os"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "BMT AI OS controller is down"

      - alert: OllamaUnhealthy
        expr: bmt_health_checks_total{service="ollama",status="unhealthy"} > 3
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Ollama service is repeatedly failing health checks"

      - alert: HighErrorRate
        expr: |
          rate(bmt_requests_total{status=~"5.."}[5m]) /
          rate(bmt_requests_total[5m]) > 0.05
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "Error rate above 5%"
```

### 7.4 Log Aggregation

Controller emits structured JSON logs to `/var/log/bmt-controller.log`.

Promtail (Loki) snippet:

```yaml
scrape_configs:
  - job_name: bmt-controller
    static_configs:
      - targets: [localhost]
        labels:
          job: bmt-controller
          __path__: /var/log/bmt-controller.log
    pipeline_stages:
      - json:
          expressions:
            level: level
            request_id: request_id
            path: path
```

---

## 8. Troubleshooting Common Issues

### 8.1 Controller Fails to Start

**Symptom:** `bmt-controller` exits immediately after launch.

```bash
# Check logs
sudo journalctl -u bmt-controller -n 50
# or
tail -n 50 /var/log/bmt-controller.log
```

Common causes:

| Error | Fix |
|-------|-----|
| `BMT_JWT_SECRET not configured` | Set `BMT_JWT_SECRET` env var (min 32 chars) |
| `Port 8080 already in use` | `sudo lsof -i :8080` — kill conflicting process |
| `BMT_COMPOSE_FILE not found` | Set correct path; default is `/opt/bmt_ai_os/ai-stack/docker-compose.yml` |
| `ModuleNotFoundError: bmt_ai_os` | Set `PYTHONPATH=$(pwd)` or install the package |

### 8.2 Ollama Not Responding

```bash
# Check container status
docker ps | grep bmt-ollama

# View container logs
docker logs bmt-ollama --tail 50

# Manual restart
docker restart bmt-ollama
# wait ~30 s then check
curl -sf http://localhost:11434/api/tags
```

### 8.3 Authentication Failures

```bash
# 401 "Missing or malformed Authorization header"
# → Include the header: -H "Authorization: Bearer <token>"

# 401 "Token has expired"
# → Re-login to obtain a fresh token (tokens expire after 24 h)

# 403 "Role 'viewer' is not permitted to POST ..."
# → Use an account with 'operator' or 'admin' role for write operations

# Forgot admin password
# → On the host:
sqlite3 /var/lib/bmt/auth.db "DELETE FROM users WHERE username='admin';"
# Then re-create via the API (unauthenticated creation allowed when no users exist)
```

### 8.4 Model Inference is Slow

```bash
# Check CPU usage
top -b -n1 | head -20

# Check if model is loaded in Ollama
curl -s http://localhost:11434/api/ps | jq .

# For Apple Silicon — verify you are NOT running under Rosetta
uname -m  # should be arm64

# For Jetson — verify CUDA is available to the container
docker exec bmt-ollama nvidia-smi
```

### 8.5 ChromaDB Collection Not Found

```bash
# List existing collections
curl -s http://localhost:8000/api/v1/collections | jq .[].name

# Create missing collection via ingest API
curl -s -X POST http://localhost:8080/api/v1/ingest \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"path":"/data/docs","collection":"default","recursive":true}'
```

### 8.6 Fleet Devices Not Checking In

```bash
# On the edge device — check agent logs
tail -f /var/log/bmt-fleet-agent.log

# Common causes:
# 1. fleet_server URL is wrong or unreachable
ping fleet.example.com
curl -sf http://fleet.example.com:8080/healthz

# 2. Firewall blocking outbound port 8080
sudo iptables -L OUTPUT -n | grep DROP

# 3. Device clock skew (JWT validation fails)
date; ssh fleet.example.com date
# fix with: sudo ntpdate -u pool.ntp.org
```

### 8.7 Disk Full — Model Storage

```bash
# Check disk usage
df -h /var/lib/docker

# List Ollama models by size
docker exec bmt-ollama ollama list

# Remove an unused model
docker exec bmt-ollama ollama rm qwen2.5:72b

# Prune Docker build cache
docker system prune -f
```

---

*For further assistance, open an issue at https://github.com/bemind/ai-first-os or consult the architecture docs in `docs/architecture/`.*
