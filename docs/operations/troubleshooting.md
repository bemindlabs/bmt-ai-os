# Troubleshooting Guide

This guide covers diagnosis and resolution of the most common operational issues on BMT AI OS: out-of-memory conditions, thermal throttling, model eviction, and service failures.

---

## Quick Diagnostic Commands

Run these first when something is wrong:

```bash
# System overview
free -h && df -h /data && uptime

# All service health
curl -sf http://localhost:8080/healthz | python3 -m json.tool
curl -sf http://localhost:11434/api/tags | python3 -m json.tool
curl -sf http://localhost:8000/api/v1/heartbeat

# Container status
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Recent kernel messages (OOM, thermal)
dmesg -T | tail -50

# Controller log
tail -100 /var/log/bmt-controller.log
```

---

## 1. Out-of-Memory (OOM) Issues

### 1.1 Symptoms

- Services crash unexpectedly and restart
- `dmesg` shows messages like `Out of memory: Killed process` or `oom_kill_process`
- `docker ps` shows containers with high restart counts
- Inference requests return 500 errors

### 1.2 Confirm OOM is the Cause

```bash
# Check kernel OOM messages
dmesg -T | grep -i "out of memory\|oom\|killed process"

# Check which container was killed
dmesg -T | grep -i "docker\|containerd" | tail -20

# Current memory pressure
free -h
cat /proc/meminfo | grep -E "MemTotal|MemFree|MemAvailable|Cached|SwapTotal|SwapFree"

# Per-container memory usage
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}"
```

### 1.3 Immediate Mitigation

**Option A: Switch to a smaller model**

```bash
# List loaded models
curl -sf http://localhost:11434/api/tags | python3 -m json.tool

# Stop the current large model and load a smaller one
ollama stop qwen2.5-coder:14b
ollama pull qwen2.5-coder:3b
```

**Option B: Free memory by stopping unused services**

```bash
# Stop ChromaDB if RAG is not required
docker stop bmt-chromadb

# Verify memory freed
free -h
```

**Option C: Unload Ollama models from VRAM/RAM**

```bash
# Ollama unloads models automatically after a timeout.
# Force unload by setting keep_alive to 0:
curl -X POST http://localhost:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d '{"model": "qwen2.5-coder:14b", "keep_alive": 0}'
```

### 1.4 Permanent Fix: Match Model Size to Available RAM

| Device RAM | Maximum safe model | Recommended Qwen model |
|-----------|-------------------|------------------------|
| 8 GB | 7B Q4_K_M (~4.1 GB) | `qwen2.5-coder:7b` |
| 16 GB | 14B Q4_K_M (~8.4 GB) | `qwen2.5-coder:14b` |
| 32 GB | 32B Q4_K_M (~19 GB) | `qwen2.5-coder:32b` |

Always leave at least 2 GB RAM free for the OS, controller, and ChromaDB.

### 1.5 Configure Memory Limits

Prevent runaway containers from consuming all RAM by setting explicit limits in your Docker Compose override:

```yaml
# docker-compose.override.yml
services:
  ollama:
    mem_limit: 12g        # Adjust for your board
    memswap_limit: 12g    # Equal to mem_limit to disable swap for this container
  chromadb:
    mem_limit: 2g
    memswap_limit: 2g
```

### 1.6 Enable Swap as a Safety Buffer

On boards that lack it by default (not a performance solution — inference over swap is slow):

```bash
# Create a 4 GB swap file on /data
sudo fallocate -l 4G /data/swapfile
sudo chmod 0600 /data/swapfile
sudo mkswap /data/swapfile
sudo swapon /data/swapfile

# Make permanent
echo "/data/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab
```

---

## 2. Thermal Throttling

### 2.1 Symptoms

- Inference tokens/second drops suddenly mid-generation
- CPU frequency reports lower than rated max
- `sensors` or `dmesg` shows high temperatures
- System may become unresponsive under sustained load

### 2.2 Check Current Temperatures

```bash
# Kernel thermal zones
cat /sys/class/thermal/thermal_zone*/temp | awk '{print $1/1000 "°C"}'

# CPU frequency (compare against rated max)
cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq | awk '{print $1/1000 " MHz"}'
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq | awk '{print $1/1000 " MHz max"}'

# Check if throttling is active (1 = throttled)
cat /sys/devices/system/cpu/cpu*/cpufreq/throttled 2>/dev/null || echo "throttling info not available"

# Board-specific: Jetson
tegrastats 2>/dev/null | head -5 || true

# Board-specific: RK3588
cat /sys/class/devfreq/*/cur_freq 2>/dev/null || true
```

### 2.3 Thermal Thresholds

| Temperature | Status |
|-------------|--------|
| < 60°C | Normal |
| 60–75°C | Elevated — monitor |
| 75–85°C | Warning — throttling begins on most boards |
| > 85°C | Critical — significant throttling, risk of shutdown |

### 2.4 Resolution Steps

1. **Check physical cooling.** Ensure the heatsink is seated properly and the fan (if fitted) is spinning.

2. **Reduce sustained load.** Limit concurrent inference requests:

```bash
# Check concurrent requests to controller
grep "POST /v1/chat" /var/log/bmt-controller.log | tail -20
```

3. **Lower the CPU governor to reduce peak heat at the cost of speed:**

```bash
# Check current governor
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor

# Switch to conservative (less aggressive frequency scaling)
echo conservative | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor

# Or cap the max frequency (example: cap at 1.5 GHz)
echo 1500000 | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_max_freq
```

4. **Use a more aggressively quantized model.** Q4_K_M generates less heat than Q8 or FP16.

### 2.5 Persistent Thermal Monitoring Alert

See the [Monitoring Guide](monitoring-guide.md) for Prometheus alert rules that fire at 75°C and 85°C.

---

## 3. Model Eviction and Loading Issues

### 3.1 Model Not Loading — Insufficient Memory

**Symptom:** `ollama run` or an API request fails with an error referencing memory or VRAM.

```bash
# Check available memory before load
free -h

# Check model sizes
ollama list

# Attempt load and watch logs
docker logs -f bmt-ollama &
ollama run qwen2.5-coder:7b "hello"
```

**Fix:** See the OOM section. Choose a model whose Q4_K_M size fits in available RAM.

### 3.2 Model Evicted from Memory

Ollama evicts models from RAM after a period of inactivity (default keep_alive: 5 minutes). The next request re-loads the model, causing a 30–60 second cold-start delay.

**Increase keep_alive for always-on deployments:**

```bash
# Per-request keep_alive (in seconds; -1 = keep forever)
curl -X POST http://localhost:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d '{"model": "qwen2.5-coder:7b", "prompt": "", "keep_alive": -1}'
```

Or set globally via environment variable in the Ollama container:

```yaml
# docker-compose.override.yml
services:
  ollama:
    environment:
      - OLLAMA_KEEP_ALIVE=-1
```

Then restart: `docker restart bmt-ollama`

> On 8 GB devices, use keep_alive -1 only with a model that comfortably fits in RAM. Keeping a large model loaded when ChromaDB also needs memory causes OOM.

### 3.3 Corrupted Model File

**Symptom:** Model load fails with a checksum or GGUF parsing error in Ollama logs.

```bash
# View detailed Ollama logs
docker logs bmt-ollama 2>&1 | grep -i "error\|failed\|corrupt" | tail -20

# Remove the corrupted model and re-pull
ollama rm qwen2.5-coder:7b
ollama pull qwen2.5-coder:7b
```

### 3.4 Model Not Found After OTA Update

If a model was stored in the Ollama volume but the OTA update landed on a new partition slot, the volume reference may differ.

```bash
# Check which volumes are mounted
docker inspect bmt-ollama | python3 -m json.tool | grep -A3 '"Mounts"'

# List models from inside the container
docker exec bmt-ollama ollama list
```

If the volume is empty after an update, re-pull models. Consider backing up the model volume before major OTA updates if air-gapped.

---

## 4. Controller API Not Responding

### 4.1 Symptom

`curl http://localhost:8080/healthz` hangs or returns a connection refused error.

### 4.2 Diagnosis

```bash
# Is the controller process running?
docker ps | grep bmt-controller
rc-status | grep bmt-controller

# View controller logs
tail -100 /var/log/bmt-controller.log
docker logs bmt-controller --tail 100

# Is port 8080 listening?
ss -tlnp | grep 8080
```

### 4.3 Recovery

```bash
# Restart via Docker
docker restart bmt-controller

# Restart via OpenRC (if running as a system service)
sudo rc-service bmt-controller restart

# If the circuit breaker has opened due to repeated Ollama failures:
# Wait for circuit_breaker_reset (default 300s) or restart the controller
# to force an immediate reset.
```

### 4.4 Circuit Breaker Tripped

The controller has a circuit breaker that stops auto-restarting Ollama after 5 consecutive failures (configurable via `circuit_breaker_threshold`). Check controller logs:

```bash
grep -i "circuit\|breaker" /var/log/bmt-controller.log | tail -20
```

If the circuit breaker is open:

1. Resolve the underlying Ollama issue first (OOM, disk space, etc.)
2. Restart the controller to reset the circuit breaker:

```bash
docker restart bmt-controller
```

---

## 5. ChromaDB Issues

### 5.1 ChromaDB Not Responding

```bash
curl -sf http://localhost:8000/api/v1/heartbeat

# Check logs
docker logs bmt-chromadb --tail 50

# Check disk space (ChromaDB fails silently when disk is full)
df -h /var/lib/chromadb/
```

### 5.2 Disk Full — ChromaDB Stops Writing

```bash
# Check disk usage
df -h

# Find large files
du -sh /var/lib/chromadb/*
du -sh /var/lib/ollama/

# Free space by removing unused models
ollama rm <unused-model>

# Or clean Docker build cache
docker system prune --volumes --filter "until=24h"
```

Set up the disk space alert in Prometheus (see [Monitoring Guide](monitoring-guide.md)) to receive warnings before the disk fills completely.

### 5.3 ChromaDB Data Corruption

**Symptom:** ChromaDB starts but queries return errors, or the container crash-loops on startup.

```bash
# Check container exit code
docker inspect bmt-chromadb | python3 -m json.tool | grep '"ExitCode"'

# View crash logs
docker logs bmt-chromadb 2>&1 | tail -50
```

If the data directory is corrupted, restore from backup:

```bash
# Stop container
docker stop bmt-chromadb

# Restore from latest backup (see Backup and Restore guide)
sudo tar -xzf /data/backups/chromadb/latest.tar.gz -C /var/lib/chromadb/
sudo chown -R 1000:1000 /var/lib/chromadb/

docker start bmt-chromadb
curl -sf http://localhost:8000/api/v1/heartbeat
```

---

## 6. OTA Update Failures

### 6.1 Download Fails

```bash
# Check network connectivity to release server
curl -I https://releases.bmtaios.dev/latest.json

# Check disk space for the image download
df -h /data/bmt_ai_os/ota/
```

Minimum free space required: image size + 10% buffer (typically 1–3 GB for a compressed image).

### 6.2 SHA-256 Mismatch

The OTA engine rejects images that do not match the expected hash and deletes the partial download.

```bash
# Re-download — the engine re-verifies automatically
python3 -c "
from bmt_ai_os.ota.engine import download_image
ok = download_image(
    url='<url>',
    dest_path='/data/bmt_ai_os/ota/<version>.img',
    expected_sha256='<sha256>',
)
print('Download OK:', ok)
"
```

If the mismatch persists, verify the expected SHA-256 from the official release manifest, as the release server response may have been corrupted in transit.

### 6.3 Boot Fails After Update — Automatic Rollback

If the system does not confirm the new boot within U-Boot's bootcount limit, U-Boot automatically reverts to the previous slot on the next reboot.

Check OTA state to verify:

```bash
cat /data/bmt_ai_os/db/ota-state.json
```

If `confirmed` is `false` and `bootcount` is elevated, the system is in an unconfirmed state. Either confirm it (if the system is healthy) or reboot to trigger rollback.

### 6.4 Slot State Mismatch

If `fw_printenv` and the state file disagree:

```bash
# Check U-Boot env
fw_printenv slot_name bootcount upgrade_available

# Check state file
cat /data/bmt_ai_os/db/ota-state.json
```

Reconcile by setting the state file to match the confirmed U-Boot slot:

```bash
python3 -c "
from bmt_ai_os.ota.state import StateManager, OTAState
sm = StateManager()
state = sm.load()
state.current_slot = 'a'   # match fw_printenv slot_name output
state.standby_slot = 'b'
state.confirmed = True
state.bootcount = 0
sm.save(state)
print('State reconciled.')
"
```

---

## 7. TLS Certificate Issues

### 7.1 Certificate Expired

TLS certs auto-generated by the system are valid for 365 days. Check expiry:

```bash
openssl x509 -in /data/secrets/tls/server.crt -noout -dates
```

Regenerate by removing the existing certs (the system auto-generates on next controller start):

```bash
sudo rm /data/secrets/tls/server.crt /data/secrets/tls/server.key
sudo rc-service bmt-controller restart
# Verify new cert
openssl x509 -in /data/secrets/tls/server.crt -noout -dates
```

### 7.2 TLS Handshake Failure

```bash
# Test TLS connection
openssl s_client -connect localhost:8443 -servername localhost 2>&1 | head -30

# Check if cert and key are a matched pair
openssl x509 -noout -modulus -in /data/secrets/tls/server.crt | openssl md5
openssl rsa -noout -modulus -in /data/secrets/tls/server.key | openssl md5
# Both hashes must match
```

---

## 8. Dashboard Not Loading

```bash
# Check if the dashboard process is running
ps aux | grep next | grep -v grep
docker ps | grep bmt-dashboard

# Check port 9090
ss -tlnp | grep 9090

# View dashboard logs
docker logs bmt-dashboard --tail 50

# Rebuild if necessary (development setup)
cd /opt/bmt_ai_os/dashboard
npm run build && npm start
```

---

## 9. SSH and Network Issues

### 9.1 Cannot Connect via SSH

```bash
# From the device console (serial or direct):
# Check sshd status
rc-service sshd status
rc-service sshd start

# Verify sshd is listening
ss -tlnp | grep 22

# Check firewall rules
iptables -L INPUT -n | grep 22
```

### 9.2 bmt-ai-net Bridge Missing

If containers cannot communicate with each other:

```bash
# Check network exists
docker network ls | grep bmt-ai-net

# Re-create if missing
docker network create --driver bridge --subnet 172.30.0.0/16 bmt-ai-net

# Restart the stack
docker compose -f /opt/bmt_ai_os/ai-stack/docker-compose.yml down
docker compose -f /opt/bmt_ai_os/ai-stack/docker-compose.yml up -d
```

---

## 10. Collecting Diagnostic Information

When filing a bug report or requesting support, collect the following:

```bash
#!/bin/sh
# /opt/bmt_ai_os/scripts/collect-diagnostics.sh
DIAG_DIR="/tmp/bmt-diag-$(date +%Y%m%dT%H%M%S)"
mkdir -p "$DIAG_DIR"

# System info
uname -a > "${DIAG_DIR}/uname.txt"
free -h > "${DIAG_DIR}/memory.txt"
df -h > "${DIAG_DIR}/disk.txt"
uptime > "${DIAG_DIR}/uptime.txt"

# Container status
docker ps -a > "${DIAG_DIR}/containers.txt"
docker stats --no-stream > "${DIAG_DIR}/container-stats.txt"

# Service health
curl -sf http://localhost:8080/healthz > "${DIAG_DIR}/healthz.json" 2>&1 || true
curl -sf http://localhost:11434/api/tags > "${DIAG_DIR}/ollama-tags.json" 2>&1 || true

# Logs (last 500 lines each, no secrets)
tail -500 /var/log/bmt-controller.log > "${DIAG_DIR}/controller.log" 2>/dev/null || true
docker logs bmt-ollama --tail 200 > "${DIAG_DIR}/ollama.log" 2>&1 || true
docker logs bmt-chromadb --tail 200 > "${DIAG_DIR}/chromadb.log" 2>&1 || true

# Kernel messages
dmesg -T | tail -200 > "${DIAG_DIR}/dmesg.txt"

# OTA state (no secrets)
cp /data/bmt_ai_os/db/ota-state.json "${DIAG_DIR}/" 2>/dev/null || true

# Bundle
tar -czf "${DIAG_DIR}.tar.gz" -C /tmp "$(basename "$DIAG_DIR")"
rm -rf "$DIAG_DIR"

echo "Diagnostics saved to: ${DIAG_DIR}.tar.gz"
echo "Review before sharing — remove any sensitive paths or tokens."
```

```bash
sudo /opt/bmt_ai_os/scripts/collect-diagnostics.sh
```

---

## Getting Help

- GitHub Issues: https://github.com/bemindlabs/bmt-ai-os/issues
- Security issues: security@bemind.tech
- Reference FAQ: [../reference/faq.md](../reference/faq.md)

---

## Related Guides

- [Deployment Runbook](deployment-runbook.md) — initial setup and OTA guide
- [Monitoring Guide](monitoring-guide.md) — set up alerts before problems occur
- [Backup and Restore](backup-restore.md) — recover from data loss
