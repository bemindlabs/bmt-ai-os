# Backup and Restore

This guide covers backup and restore procedures for all persistent data on BMT AI OS: the ChromaDB vector database, controller configuration, secrets, TLS certificates, OTA state, and Prometheus metrics.

---

## What to Back Up

| Data | Path | Priority | Size |
|------|------|----------|------|
| ChromaDB embeddings | `/var/lib/chromadb/` | Critical | Variable |
| Controller config | `/etc/bmt_ai_os/controller.yml` | High | < 1 KB |
| Secrets store | `/etc/bmt_ai_os/secrets/` | High | < 1 KB |
| TLS certificates | `/data/secrets/tls/` | High | < 10 KB |
| OTA state | `/data/bmt_ai_os/db/ota-state.json` | Medium | < 1 KB |
| Prometheus data | Docker volume `prometheus-data` | Low | Up to 5 GB |
| Ollama model cache | `/var/lib/ollama/` (or Docker volume) | Optional | 4–30 GB |

> Ollama models are large and can be re-pulled from the internet or a local registry. Back them up only if your deployment is fully air-gapped and re-download is not possible.

---

## 1. ChromaDB Backup

ChromaDB persists embeddings to `/var/lib/chromadb/` (mapped to the `chromadb-data` Docker volume). The recommended backup method is a filesystem snapshot while the container is paused, or using ChromaDB's HTTP API to export collections.

### 1.1 Cold Backup (Pause Container)

Pausing the container briefly prevents writes during the copy, ensuring a consistent snapshot.

```bash
#!/bin/sh
# /opt/bmt_ai_os/scripts/backup-chromadb.sh
set -eu

BACKUP_DIR="${1:-/data/backups/chromadb}"
TIMESTAMP=$(date +%Y%m%dT%H%M%S)
DEST="${BACKUP_DIR}/${TIMESTAMP}"

mkdir -p "$DEST"

echo "Pausing ChromaDB container..."
docker pause bmt-chromadb

echo "Copying ChromaDB data..."
cp -a /var/lib/chromadb/. "$DEST/"

echo "Resuming ChromaDB container..."
docker unpause bmt-chromadb

# Compress the snapshot
tar -czf "${DEST}.tar.gz" -C "$BACKUP_DIR" "$TIMESTAMP"
rm -rf "$DEST"

echo "ChromaDB backup complete: ${DEST}.tar.gz"
```

```bash
# Run the backup
sudo /opt/bmt_ai_os/scripts/backup-chromadb.sh /data/backups/chromadb
```

### 1.2 Via Docker Volume

```bash
# Backup the Docker-managed volume directly
docker run --rm \
  -v chromadb-data:/source:ro \
  -v /data/backups/chromadb:/dest \
  alpine:3 \
  tar -czf "/dest/chromadb-$(date +%Y%m%dT%H%M%S).tar.gz" -C /source .
```

### 1.3 Automated Daily Backup via Cron

```bash
# /etc/cron.d/bmt-chromadb-backup
0 3 * * * root /opt/bmt_ai_os/scripts/backup-chromadb.sh /data/backups/chromadb >> /var/log/bmt-backup.log 2>&1
```

### 1.4 Retention Policy

Keep the last 7 daily backups automatically:

```bash
# Add to backup script after creating the archive:
find /data/backups/chromadb -name "*.tar.gz" -mtime +7 -delete
```

---

## 2. Configuration and Secrets Backup

Configuration files and secrets are small and must be backed up together. Encrypt the archive before writing it to any external location.

```bash
#!/bin/sh
# /opt/bmt_ai_os/scripts/backup-config.sh
set -eu

BACKUP_DIR="${1:-/data/backups/config}"
TIMESTAMP=$(date +%Y%m%dT%H%M%S)
TMP_DIR=$(mktemp -d)
ARCHIVE="${BACKUP_DIR}/${TIMESTAMP}-config.tar"
ENCRYPTED="${ARCHIVE}.gpg"

mkdir -p "$BACKUP_DIR"

# Collect config files
cp /etc/bmt_ai_os/controller.yml "${TMP_DIR}/"
cp -r /data/secrets/tls/ "${TMP_DIR}/tls/"
cp /data/bmt_ai_os/db/ota-state.json "${TMP_DIR}/" 2>/dev/null || true

# Note: secrets at /etc/bmt_ai_os/secrets/ contain API keys.
# Include them only in the encrypted backup.
cp -r /etc/bmt_ai_os/secrets/ "${TMP_DIR}/secrets/"

# Create unencrypted tar
tar -cf "$ARCHIVE" -C "$TMP_DIR" .

# Encrypt with GPG symmetric encryption
# You will be prompted for a passphrase — store it in your password manager.
gpg --symmetric --cipher-algo AES256 --output "$ENCRYPTED" "$ARCHIVE"
rm "$ARCHIVE"

# Clean up
rm -rf "$TMP_DIR"

echo "Config backup: $ENCRYPTED"
```

```bash
sudo /opt/bmt_ai_os/scripts/backup-config.sh
```

> Never copy the unencrypted secrets archive to any external location. Always encrypt first.

---

## 3. Full System Backup

For a full device backup before an OTA update or hardware migration:

```bash
#!/bin/sh
# /opt/bmt_ai_os/scripts/backup-full.sh
# Creates a complete backup of all persistent data.
set -eu

BACKUP_BASE="/data/backups/full"
TIMESTAMP=$(date +%Y%m%dT%H%M%S)
DEST="${BACKUP_BASE}/${TIMESTAMP}"
mkdir -p "$DEST"

echo "=== Full backup started at ${TIMESTAMP} ==="

# ChromaDB
docker pause bmt-chromadb
cp -a /var/lib/chromadb/ "${DEST}/chromadb/"
docker unpause bmt-chromadb
echo "ChromaDB: done"

# Controller + OTA state
cp /etc/bmt_ai_os/controller.yml "${DEST}/"
cp /data/bmt_ai_os/db/ota-state.json "${DEST}/" 2>/dev/null || true
echo "Config: done"

# TLS certs
cp -r /data/secrets/tls/ "${DEST}/tls/"
echo "TLS: done"

# Prometheus (optional — can be large)
docker run --rm \
  -v prometheus-data:/source:ro \
  -v "${DEST}":/dest \
  alpine:3 \
  tar -czf /dest/prometheus.tar.gz -C /source .
echo "Prometheus: done"

# Compress full backup
tar -czf "${DEST}.tar.gz" -C "$BACKUP_BASE" "$TIMESTAMP"
rm -rf "$DEST"

echo "=== Full backup complete: ${DEST}.tar.gz ==="
```

---

## 4. Offsite Transfer

For air-gapped devices with occasional network access, copy backups to a remote location:

```bash
# rsync to a backup server over SSH
rsync -avz --progress /data/backups/ backup-user@backup-server:/backups/bmt-<device-name>/

# Or copy to a USB drive
mount /dev/sda1 /mnt/usb
cp /data/backups/chromadb/*.tar.gz /mnt/usb/
umount /mnt/usb
```

---

## 5. Restore Procedures

### 5.1 Restore ChromaDB

```bash
# Stop ChromaDB before restoring to prevent data corruption
docker stop bmt-chromadb

# Clear existing data (DESTRUCTIVE — ensure backup is verified first)
sudo rm -rf /var/lib/chromadb/*

# Restore from backup archive
BACKUP_FILE="/data/backups/chromadb/20260410T030000.tar.gz"
sudo tar -xzf "$BACKUP_FILE" -C /var/lib/chromadb/

# Fix ownership
sudo chown -R 1000:1000 /var/lib/chromadb/

# Restart ChromaDB
docker start bmt-chromadb

# Verify
sleep 5
curl -sf http://localhost:8000/api/v1/heartbeat && echo "ChromaDB restored successfully"
```

### 5.2 Restore Configuration

```bash
# Decrypt the config backup
gpg --decrypt 20260410T120000-config.tar.gpg > config-restore.tar

# Extract to temp dir for inspection
mkdir /tmp/config-restore
tar -xf config-restore.tar -C /tmp/config-restore

# Review the contents before restoring
ls -la /tmp/config-restore/

# Restore controller config
sudo cp /tmp/config-restore/controller.yml /etc/bmt_ai_os/controller.yml

# Restore TLS certs
sudo cp -r /tmp/config-restore/tls/. /data/secrets/tls/
sudo chmod 0600 /data/secrets/tls/server.key
sudo chmod 0644 /data/secrets/tls/server.crt

# Restore secrets (requires root)
sudo cp -r /tmp/config-restore/secrets/. /etc/bmt_ai_os/secrets/
sudo chmod -R 0600 /etc/bmt_ai_os/secrets/
sudo chown -R root:root /etc/bmt_ai_os/secrets/

# Restore OTA state
sudo cp /tmp/config-restore/ota-state.json /data/bmt_ai_os/db/ota-state.json

# Clean up
rm -rf /tmp/config-restore config-restore.tar

# Restart controller
sudo rc-service bmt-controller restart
```

### 5.3 Restore Prometheus Data

Restoring Prometheus data is optional — metrics are historical only and losing them does not affect system operation.

```bash
docker stop bmt-prometheus

docker run --rm \
  -v prometheus-data:/dest \
  -v /data/backups/full/20260410T030000:/src:ro \
  alpine:3 \
  sh -c "rm -rf /dest/* && tar -xzf /src/prometheus.tar.gz -C /dest"

docker start bmt-prometheus
```

### 5.4 Full Disaster Recovery

When recovering a device from scratch (hardware failure, SD card corruption):

1. Flash a fresh OS image following the [Deployment Runbook](deployment-runbook.md) steps 1.1–1.3.
2. Restore secrets: follow section 5.2 above.
3. Re-run security overlay setup (AppArmor profiles, container security overlay).
4. Start the AI stack.
5. Restore ChromaDB: follow section 5.1 above.
6. Pull Ollama models (or restore from a local model mirror if air-gapped):

```bash
ollama pull qwen2.5-coder:7b
```

7. Run smoke tests:

```bash
python3 -m pytest tests/smoke/ -q
```

8. Verify health endpoints:

```bash
curl -sf http://localhost:8080/healthz
curl -sf http://localhost:11434/api/tags
curl -sf http://localhost:8000/api/v1/heartbeat
```

---

## 6. Backup Verification

A backup is only useful if it can be restored. Test restore procedures monthly:

```bash
#!/bin/sh
# Verify ChromaDB backup integrity without a full restore
BACKUP_FILE="$1"
VERIFY_DIR=$(mktemp -d)

tar -tzf "$BACKUP_FILE" > /dev/null && echo "Archive integrity: OK"
tar -xzf "$BACKUP_FILE" -C "$VERIFY_DIR"

# Check for expected ChromaDB files
if [ -d "${VERIFY_DIR}/chroma" ]; then
    echo "ChromaDB structure: OK"
    ls "${VERIFY_DIR}/chroma/"
else
    echo "WARNING: Expected ChromaDB structure not found in backup"
    exit 1
fi

rm -rf "$VERIFY_DIR"
```

---

## 7. Backup Checklist

- [ ] ChromaDB automated daily backup enabled (`cron.d/bmt-chromadb-backup`)
- [ ] Config + secrets backup encrypted with GPG
- [ ] Backup retention policy configured (7 days local)
- [ ] Offsite or USB copy scheduled for air-gapped devices
- [ ] Restore procedure tested against a non-production device
- [ ] Backup encryption passphrase stored in password manager

---

## Related Guides

- [Deployment Runbook](deployment-runbook.md) — initial setup and OTA update guide
- [Monitoring Guide](monitoring-guide.md) — disk usage alerts before storage fills up
- [Troubleshooting](troubleshooting.md) — recovering from ChromaDB corruption
