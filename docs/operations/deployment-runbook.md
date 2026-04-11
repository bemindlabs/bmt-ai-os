# Production Deployment Runbook

This runbook covers every step required to bring a BMT AI OS device from a freshly flashed image to a fully operational, production-hardened state. Follow sections in order on first boot; individual sections can be referenced in isolation for ongoing maintenance.

---

## Prerequisites

| Item | Requirement |
|------|-------------|
| Hardware | ARM64 board — Jetson Orin Nano Super, RK3588, or Pi 5 + Hailo AI HAT+ |
| Storage | 32 GB minimum (64 GB+ recommended) |
| RAM | 8 GB minimum |
| Network | Ethernet connection for initial setup |
| Host workstation | SSH client, `curl`, `openssl` |

---

## 1. First-Boot Checklist

### 1.1 Flash and Boot

```bash
# Download the release image for your board
wget https://releases.bmtaios.dev/2026.4.10/bmt-ai-os-<board>-2026.4.10.img.zst

# Verify the download
sha256sum -c bmt-ai-os-<board>-2026.4.10.img.zst.sha256

# Decompress and flash (replace /dev/sdX with your target device)
zstd -d bmt-ai-os-<board>-2026.4.10.img.zst -o bmt-ai-os.img
sudo dd if=bmt-ai-os.img of=/dev/sdX bs=4M conv=fsync status=progress
```

Connect Ethernet and power on. The OS boots into OpenRC, which starts containerd, then the AI stack. Allow 2–3 minutes for first boot to complete.

Verify network connectivity from the device:

```bash
ssh bmt@<device-ip>
ping -c 3 8.8.8.8
```

### 1.2 Change Default Credentials

The default SSH account is `bmt` with password `bmt`. Change it immediately.

```bash
# On the device
passwd bmt

# Generate an ed25519 key pair on your workstation and copy it
ssh-keygen -t ed25519 -C "ops@your-org.com" -f ~/.ssh/bmt_device
ssh-copy-id -i ~/.ssh/bmt_device.pub bmt@<device-ip>

# Disable password authentication
sudo sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo rc-service sshd restart
```

### 1.3 Set the Hostname

```bash
sudo hostname bmt-device-<location>
echo "bmt-device-<location>" | sudo tee /etc/hostname
```

### 1.4 Initialise the Secrets Store

The secrets manager stores API keys and service credentials under `/etc/bmt_ai_os/secrets/` with mode `0600 root:root`.

```bash
# Initialise the directory tree (must be root)
sudo /opt/bmt_ai_os/bin/secrets-manager.sh init

# Verify the structure was created
sudo /opt/bmt_ai_os/bin/secrets-manager.sh list
```

Expected output:

```
Stored secrets:
  [ ] OPENAI_API_KEY
  [ ] ANTHROPIC_API_KEY
  [ ] GOOGLE_API_KEY
  [ ] MISTRAL_API_KEY
  [ ] GROQ_API_KEY
  [ ] CHROMA_AUTH_CREDENTIALS
```

Store any remote-provider API keys you intend to use. Keys for providers you will not use can be left empty — the fallback router handles missing providers gracefully.

```bash
# Example: store OpenAI key for fallback inference
sudo /opt/bmt_ai_os/bin/secrets-manager.sh set OPENAI_API_KEY sk-...

# Set ChromaDB auth credentials
sudo /opt/bmt_ai_os/bin/secrets-manager.sh set CHROMA_AUTH_CREDENTIALS "admin:$(openssl rand -hex 16)"

# Inject per-service secrets into service mount dirs
sudo /opt/bmt_ai_os/bin/secrets-manager.sh inject ollama
sudo /opt/bmt_ai_os/bin/secrets-manager.sh inject chromadb
```

### 1.5 Configure TLS

TLS is opt-in. For air-gapped deployments, plain HTTP on port 8080 is acceptable. For any deployment reachable over a network, enable TLS.

**Option A: Auto-generated self-signed certificate (default)**

```bash
# Enable TLS in the environment — add to /etc/bmt_ai_os/env
sudo tee -a /etc/bmt_ai_os/env <<'EOF'
BMT_TLS_ENABLED=true
BMT_TLS_PORT=8443
BMT_TLS_REDIRECT=true
BMT_TLS_HOSTNAME=bmt-device-<location>.your-org.com
EOF
```

On next controller start, certs are auto-generated at `/data/secrets/tls/server.crt` and `/data/secrets/tls/server.key` (RSA 4096, 365-day validity).

**Option B: CA-signed certificate**

```bash
# Generate a CSR on the device
openssl req -newkey rsa:4096 -keyout /data/secrets/tls/server.key \
  -out /data/secrets/tls/server.csr -nodes \
  -subj "/CN=bmt-device.your-org.com/O=Your Org"

# Sign the CSR with your CA, then install the signed cert
sudo cp signed-cert.pem /data/secrets/tls/server.crt
sudo chmod 0644 /data/secrets/tls/server.crt
sudo chmod 0600 /data/secrets/tls/server.key

# Point the controller at the explicit paths
sudo tee -a /etc/bmt_ai_os/env <<'EOF'
BMT_TLS_ENABLED=true
BMT_TLS_CERT=/data/secrets/tls/server.crt
BMT_TLS_KEY=/data/secrets/tls/server.key
BMT_TLS_PORT=8443
BMT_TLS_REDIRECT=true
EOF
```

### 1.6 Create the Admin User Account

The controller exposes an admin API. Create an initial admin token:

```bash
# Generate a strong token
ADMIN_TOKEN=$(openssl rand -hex 32)
sudo /opt/bmt_ai_os/bin/secrets-manager.sh set BMT_ADMIN_TOKEN "$ADMIN_TOKEN"
echo "Admin token (save this): $ADMIN_TOKEN"
```

Store the token in your password manager. It is not retrievable after this point without root on the device.

### 1.7 Apply the Security Overlay

The container security overlay drops all unnecessary Linux capabilities and applies AppArmor profiles and seccomp filters.

```bash
# Load AppArmor profiles
sudo apparmor_parser -r /opt/bmt_ai_os/security/apparmor-ollama.profile
sudo apparmor_parser -r /opt/bmt_ai_os/security/apparmor-chromadb.profile
sudo apparmor_parser -r /opt/bmt_ai_os/security/apparmor-controller.profile

# Restart the stack with the security overlay
docker compose \
  -f /opt/bmt_ai_os/ai-stack/docker-compose.yml \
  -f /opt/bmt_ai_os/security/container-security.yml \
  up -d
```

Verify all containers are running:

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

Expected:

```
NAMES           STATUS          PORTS
bmt-ollama      Up X minutes    0.0.0.0:11434->11434/tcp
bmt-chromadb    Up X minutes    0.0.0.0:8000->8000/tcp
bmt-controller  Up X minutes    0.0.0.0:8080->8080/tcp
```

### 1.8 Validate the Stack

Run the health check against all three service endpoints:

```bash
# Controller
curl -sf http://localhost:8080/healthz | python3 -m json.tool

# Ollama
curl -sf http://localhost:11434/api/tags | python3 -m json.tool

# ChromaDB
curl -sf http://localhost:8000/api/v1/heartbeat
```

Run the smoke tests:

```bash
cd /opt/bmt_ai_os
python3 -m pytest tests/smoke/ -q
```

All tests should pass before the device enters production service.

### 1.9 Pull the Default Model

```bash
# The controller selects the model preset based on available RAM automatically.
# To manually pull the recommended Qwen coding model:
ollama pull qwen2.5-coder:7b

# For devices with 16 GB+ RAM:
ollama pull qwen2.5-coder:14b
```

### 1.10 Configure Firewall

```bash
# Allow only required ports; deny everything else
sudo iptables -A INPUT -p tcp --dport 22 -j ACCEPT      # SSH
sudo iptables -A INPUT -p tcp --dport 8080 -j ACCEPT    # Controller API
sudo iptables -A INPUT -p tcp --dport 8443 -j ACCEPT    # Controller API (TLS)
sudo iptables -A INPUT -p tcp --dport 9090 -j ACCEPT    # Dashboard
sudo iptables -A INPUT -i lo -j ACCEPT                  # Loopback (Ollama, ChromaDB)
sudo iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
sudo iptables -P INPUT DROP

# Save rules
sudo /etc/init.d/iptables save
```

> Ollama (11434) and ChromaDB (8000) should only be accessible on localhost. Never expose them directly to the network.

---

## 2. Controller Configuration

The controller reads `/etc/bmt_ai_os/controller.yml`. The defaults are production-ready; adjust only if your deployment requires different values.

```yaml
# /etc/bmt_ai_os/controller.yml (key production settings)
compose_file: /opt/bmt_ai_os/ai-stack/docker-compose.yml

health_interval: 30          # seconds between health checks
max_restarts: 3              # consecutive failures before restart
circuit_breaker_threshold: 5 # max restart attempts before circuit opens
circuit_breaker_reset: 300   # seconds before circuit resets

api_port: 8080
api_host: 0.0.0.0

log_level: INFO
log_file: /var/log/bmt-controller.log
```

After editing, restart the controller service:

```bash
sudo rc-service bmt-controller restart
```

---

## 3. OpenRC Service Management

All core services are managed by OpenRC.

```bash
# Check service status
rc-status

# Start / stop individual services
sudo rc-service bmt-controller start
sudo rc-service bmt-controller stop
sudo rc-service bmt-controller restart

# Enable a service to start at boot
sudo rc-update add bmt-controller default

# View recent service output
sudo logread -f | grep bmt-controller
```

---

## 4. Deployment Verification Checklist

Before declaring a device production-ready, confirm each item:

- [ ] Default SSH password changed, key-based auth enabled, password auth disabled
- [ ] Secrets store initialised (`secrets-manager.sh list` shows no blanks for required keys)
- [ ] TLS configured and controller responds on port 8443
- [ ] Admin token stored securely off-device
- [ ] AppArmor profiles loaded (`aa-status | grep bmt`)
- [ ] Container security overlay applied (`docker inspect bmt-ollama | grep no-new-priv`)
- [ ] Firewall rules saved and active (`iptables -L -n`)
- [ ] All health checks pass (`/healthz` returns `{"status": "ok"}`)
- [ ] Smoke tests pass (`pytest tests/smoke/ -q`)
- [ ] Default model pulled and returns a valid inference response
- [ ] Monitoring agent configured (see [Monitoring Guide](monitoring-guide.md))
- [ ] Backup schedule configured (see [Backup and Restore](backup-restore.md))
- [ ] OTA update channel configured (see [OTA Guide](#5-ota-update-operational-guide))

---

## 5. OTA Update Operational Guide

BMT AI OS uses A/B partition slots for atomic, rollback-safe updates.

### 5.1 How A/B Updates Work

| Step | Description |
|------|-------------|
| 1. Check | Query release server for a newer version |
| 2. Download | Stream image to `/data/bmt_ai_os/ota/<version>.img.zst`, verify SHA-256 |
| 3. Apply | Write image to standby slot via `dd`, readback-verify |
| 4. Reboot | U-Boot switches `slot_name` to the standby slot |
| 5. Confirm | `confirm_boot()` resets `bootcount=0, upgrade_available=0` |
| 6. Rollback | If bootcount exceeds threshold before confirmation, U-Boot reverts to the previous slot |

### 5.2 Check for Updates

```bash
# Via the OTA CLI
python3 -c "
from bmt_ai_os.ota.engine import check_update
info = check_update('https://releases.bmtaios.dev/latest.json', current_version='2026.4.10')
print(info)
"

# Check current slot
python3 -c "
from bmt_ai_os.ota.engine import get_current_slot
print('Current slot:', get_current_slot())
"
```

### 5.3 Apply an Update

```bash
# 1. Download the update image (the engine verifies SHA-256 automatically)
python3 -c "
from bmt_ai_os.ota.engine import download_image
ok = download_image(
    url='https://releases.bmtaios.dev/2026.5.1/bmt-ai-os-rk3588-2026.5.1.img.zst',
    dest_path='/data/bmt_ai_os/ota/2026.5.1.img',
    expected_sha256='<sha256-from-release-manifest>',
    progress_cb=lambda recv, total: print(f'{recv}/{total}')
)
print('Download OK:', ok)
"

# 2. Apply to standby slot
python3 -c "
from bmt_ai_os.ota.engine import apply_update, get_current_slot
current = get_current_slot()
target = 'b' if current == 'a' else 'a'
ok = apply_update('/data/bmt_ai_os/ota/2026.5.1.img', target_slot=target)
print('Apply OK:', ok, '| Target slot:', target)
"

# 3. Reboot into the new slot
sudo reboot
```

After reboot, the system boots from the new slot. The bootcount is incremented automatically. Confirm the boot once the system is verified healthy:

```bash
# 4. Confirm the boot (run after verifying the new version is healthy)
python3 -c "
from bmt_ai_os.ota.engine import confirm_boot
confirm_boot()
print('Boot confirmed.')
"

# Verify
python3 -c "
from bmt_ai_os.ota.state import StateManager
import json
sm = StateManager()
print(json.dumps(sm.load().to_dict(), indent=2))
"
```

### 5.4 Manual Rollback

If the update is unhealthy and you need to roll back without waiting for U-Boot's automatic bootcount rollback:

```bash
# Force slot switch back
python3 -c "
from bmt_ai_os.ota.state import StateManager
sm = StateManager()
sm.switch_slots()
"
sudo reboot
```

### 5.5 Check OTA State

```bash
cat /data/bmt_ai_os/db/ota-state.json
```

Expected healthy state:

```json
{
  "current_slot": "a",
  "standby_slot": "b",
  "last_update": "2026-04-10T12:00:00+00:00",
  "bootcount": 0,
  "confirmed": true
}
```

`confirmed: false` with `bootcount > 0` means the current boot has not been confirmed — run `confirm_boot()` if the system is healthy.

### 5.6 Automate OTA Checks

Add to cron to check for updates nightly:

```bash
# /etc/cron.d/bmt-ota
0 2 * * * root /opt/bmt_ai_os/bin/bmt-ota-check.sh >> /var/log/bmt-ota.log 2>&1
```

---

## 6. Log Management

Logs rotate automatically on BMT AI OS. Key log paths:

| Log | Path |
|-----|------|
| Controller | `/var/log/bmt-controller.log` |
| Ollama | `docker logs bmt-ollama` |
| ChromaDB | `docker logs bmt-chromadb` |
| OpenRC | `logread` or `/var/log/messages` |
| OTA | `/var/log/bmt-ota.log` |

```bash
# Tail all service logs simultaneously
tail -f /var/log/bmt-controller.log &
docker logs -f bmt-ollama &
docker logs -f bmt-chromadb &
```

---

## Related Guides

- [Monitoring Guide](monitoring-guide.md) — Prometheus metrics and Grafana dashboards
- [Backup and Restore](backup-restore.md) — ChromaDB and config backups
- [Troubleshooting](troubleshooting.md) — OOM, thermal, model eviction, and other common issues
