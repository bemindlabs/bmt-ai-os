# Filesystem Layout and Storage Partitioning

BMT AI OS — ARM64 AI-First OS
BMTOS-19 | Epic: BMTOS-EPIC-3 (OS Foundation & Infrastructure)

---

## Partition Scheme

BMT AI OS uses a four-partition layout that supports A/B over-the-air (OTA) updates. Models,
vector data, and user data live on a separate data partition that persists across OS updates.

```
┌──────────────────────────────────────────────────────────────────────┐
│  Block Device  (eMMC / NVMe / SD — minimum 32GB recommended)         │
├────────────┬────────────┬────────────┬──────────────────────────────┤
│  p1 boot   │ p2 rootfs-a│ p3 rootfs-b│  p4 data                     │
│  256 MB    │  4 GB      │  4 GB      │  remaining space             │
│  FAT32     │  ext4      │  ext4      │  ext4                        │
│  LABEL=    │  LABEL=    │  LABEL=    │  LABEL=                      │
│  BMT_BOOT  │  BMT_ROOTFS│  BMT_ROOTFS│  BMT_DATA                    │
│            │  _A        │  _B        │                              │
└────────────┴────────────┴────────────┴──────────────────────────────┘
```

### Partition Details

| Partition | Number | Size    | Filesystem | Label         | Mount Point |
|-----------|--------|---------|------------|---------------|-------------|
| boot      | p1     | 256 MB  | FAT32      | BMT_BOOT      | /boot       |
| rootfs-a  | p2     | 4 GB    | ext4       | BMT_ROOTFS_A  | / (active)  |
| rootfs-b  | p3     | 4 GB    | ext4       | BMT_ROOTFS_B  | /rootfs-b   |
| data      | p4     | ~22+ GB | ext4       | BMT_DATA      | /data       |

### A/B OTA Update Strategy

- One rootfs slot is always active (mounted at `/`); the other is the standby slot.
- The OTA updater writes the new image to the standby slot while the system runs.
- U-Boot `bootenv` variable `active_slot` (value `a` or `b`) selects the boot slot.
- On successful first boot of the new slot, `bootcount` is reset and the slot is marked good.
- On boot failure (three consecutive failed boots), U-Boot rolls back to the previous slot.
- The `/data` partition is never touched during OTA updates — all user data and AI models
  survive every OS upgrade.

---

## Root Filesystem Layout

The rootfs (mounted at `/`) contains only the OS base, init scripts, and configuration.
All persistent AI data is stored under `/data` and bind-mounted into the expected locations.

```
/
├── boot/                        # FAT32 boot partition (mounted from p1)
│   ├── u-boot.env               # U-Boot environment (active_slot, bootcount)
│   ├── Image                    # ARM64 kernel image
│   ├── initramfs.cpio.gz        # Initial ramdisk
│   └── dtb/                     # Device tree blobs per board
│
├── etc/
│   ├── bmt-ai-os/               # BMT AI OS system configuration
│   │   ├── config.toml          # Main system config (preset, hardware, ports)
│   │   ├── hardware.toml        # Detected hardware profile (written at first boot)
│   │   ├── providers.toml       # LLM provider order and API key refs
│   │   ├── ota.toml             # OTA update server and channel config
│   │   └── secrets/             # Secrets dir (mode 0700, root only)
│   │       ├── api-keys.env     # Provider API keys (symlink → /data/secrets/api-keys.env)
│   │       └── .gitkeep
│   ├── fstab                    # Mount table (see fstab section below)
│   ├── hostname                 # Default: bmt-ai-os
│   ├── init.d/                  # OpenRC service scripts
│   │   ├── bmt-storage          # Mounts /data and bind mounts (runlevel: sysinit)
│   │   ├── bmt-containerd       # Starts containerd (runlevel: default)
│   │   ├── bmt-ai-stack         # docker compose up for AI services (runlevel: default)
│   │   ├── bmt-controller       # Python controller daemon (runlevel: default)
│   │   └── bmt-dashboard        # Next.js dashboard (runlevel: default)
│   └── docker/
│       └── daemon.json          # containerd/dockerd config (data-root → /data/docker)
│
├── opt/
│   └── bmt-ai-os/               # BMT AI OS application files (read-only after install)
│       ├── controller/          # Python controller source
│       │   └── main.py
│       ├── ai-stack/            # Docker Compose definitions
│       │   └── docker-compose.yml
│       ├── dashboard/           # Next.js static export
│       │   └── out/             # gzipped static files (< 2 MB)
│       ├── scripts/             # Runtime helper scripts
│       │   ├── first-boot.sh    # First-boot initialisation
│       │   ├── health-check.sh  # Service health polling
│       │   └── ota-apply.sh     # OTA slot switch helper
│       └── runtime/             # Partition and mount utilities
│           ├── partition-table.sh
│           └── fstab
│
├── var/
│   ├── lib/
│   │   ├── ollama/              # → bind mount from /data/ollama
│   │   ├── chromadb/            # → bind mount from /data/chromadb
│   │   ├── docker/              # → bind mount from /data/docker
│   │   └── bmt-ai-os/           # → bind mount from /data/bmt-ai-os
│   └── log/
│       └── bmt-ai-os/           # → bind mount from /data/logs/bmt-ai-os
│
├── tmp/                         # tmpfs (cleared on every boot)
├── run/                         # tmpfs (PID files, sockets)
└── data/                        # Mountpoint for p4 BMT_DATA (persistent)
```

---

## /data Partition Layout

The `/data` partition holds everything that must survive OS updates: AI models, vector database
state, training artefacts, notebooks, and user configuration.

```
/data/
├── ollama/                      # Ollama model storage
│   ├── models/
│   │   ├── manifests/           # Model registry metadata
│   │   └── blobs/               # Model weight blobs (5–20 GB each)
│   └── .ollama/                 # Ollama runtime state
│
├── chromadb/                    # ChromaDB persistent storage
│   ├── chroma.sqlite3           # Collection and segment metadata
│   └── collections/             # Vector segment files (HNSW indices)
│
├── training/                    # On-device training artefacts
│   ├── datasets/                # Raw and pre-processed training data
│   │   └── <dataset-name>/
│   │       ├── raw/
│   │       └── processed/
│   ├── runs/                    # Training run outputs (one dir per run)
│   │   └── <YYYYMMDD-HHMMSS-runname>/
│   │       ├── config.json      # Training hyperparameters
│   │       ├── checkpoint-*/    # Intermediate checkpoints
│   │       ├── adapter_model/   # LoRA/QLoRA adapter weights
│   │       └── logs/            # TensorBoard event files
│   └── adapters/                # Promoted/named adapters ready for serving
│       └── <adapter-name>/
│           ├── adapter_config.json
│           └── adapter_model.safetensors
│
├── notebooks/                   # Jupyter Lab workspace
│   ├── examples/                # Bundled example notebooks
│   └── workspace/               # User notebooks
│
├── docker/                      # Container layer cache and volumes
│   ├── volumes/
│   │   ├── ollama_models/       # Named volume for Ollama container
│   │   └── chromadb_data/       # Named volume for ChromaDB container
│   └── overlay2/                # Container image layers
│
├── bmt-ai-os/                   # Runtime state for controller and services
│   ├── db/
│   │   └── metadata.sqlite3     # Service registry, model catalogue, RAG metadata
│   ├── rag/
│   │   └── ingest-queue/        # Documents queued for RAG ingestion
│   └── cache/                   # Embedding and inference caches
│
├── secrets/                     # Sensitive credentials (mode 0700, root only)
│   ├── api-keys.env             # Provider API keys (never committed to git)
│   └── tls/                     # TLS certificates if HTTPS dashboard is enabled
│
└── logs/
    └── bmt-ai-os/               # Persistent structured logs (JSON)
        ├── controller.log
        ├── ai-stack.log
        └── ota.log
```

---

## Mount Points and Volume Mapping

### fstab Summary

| Source                    | Mount Point          | Type   | Notes                        |
|---------------------------|----------------------|--------|------------------------------|
| LABEL=BMT_BOOT            | /boot                | vfat   | U-Boot, kernel, DTB          |
| LABEL=BMT_ROOTFS_A or _B  | /                    | ext4   | Active rootfs slot           |
| LABEL=BMT_DATA            | /data                | ext4   | Persistent AI data           |
| /data/ollama              | /var/lib/ollama      | bind   | Ollama model dir             |
| /data/chromadb            | /var/lib/chromadb    | bind   | ChromaDB data dir            |
| /data/docker              | /var/lib/docker      | bind   | Docker/containerd data root  |
| /data/bmt-ai-os           | /var/lib/bmt-ai-os   | bind   | Controller state and cache   |
| /data/logs/bmt-ai-os      | /var/log/bmt-ai-os   | bind   | Persistent log storage       |
| tmpfs                     | /tmp                 | tmpfs  | 512 MB max, cleared on boot  |
| tmpfs                     | /run                 | tmpfs  | 256 MB max, PID files        |

### Docker Named Volume Mapping

Docker Compose uses named volumes. The Docker data root is bind-mounted from `/data/docker`,
so named volumes resolve to:

| Named Volume   | Host Path                             | Container Mount       |
|----------------|---------------------------------------|-----------------------|
| ollama_models  | /data/docker/volumes/ollama_models    | /root/.ollama         |
| chromadb_data  | /data/docker/volumes/chromadb_data    | /chroma/chroma        |

---

## Disk Usage by Preset

Preset selection happens at first boot based on detected RAM and storage capacity.

### Lite (~10 GB total on /data)

Suitable for: Raspberry Pi 5 + Hailo AI HAT+ (8 GB RAM), budget eMMC storage.
Default model: `qwen2.5-coder:3b` (2.0 GB)

| Directory              | Estimated Size | Contents                                  |
|------------------------|----------------|-------------------------------------------|
| /data/ollama/models    | 2.0 GB         | qwen2.5-coder:3b                          |
| /data/chromadb         | 200 MB         | Single collection, up to 50K vectors      |
| /data/docker           | 5.0 GB         | Container images (ollama, chroma, base)   |
| /data/training         | 500 MB         | No pre-loaded datasets                    |
| /data/notebooks        | 100 MB         | Example notebooks only                    |
| /data/bmt-ai-os        | 100 MB         | Metadata DB, cache                        |
| /data/logs             | 100 MB         | Log rotation at 50 MB                     |
| **Total**              | **~8 GB**      | Recommended minimum disk: 32 GB           |

### Standard (~15 GB total on /data)

Suitable for: Jetson Orin Nano Super (8 GB RAM), RK3588 (8–16 GB RAM).
Default model: `qwen2.5-coder:7b` (4.7 GB)

| Directory              | Estimated Size | Contents                                  |
|------------------------|----------------|-------------------------------------------|
| /data/ollama/models    | 7.0 GB         | qwen2.5-coder:7b + qwen2.5:3b (embedder) |
| /data/chromadb         | 500 MB         | Up to 250K vectors                        |
| /data/docker           | 5.0 GB         | Container images                          |
| /data/training         | 1.0 GB         | Example datasets, one checkpoint          |
| /data/notebooks        | 200 MB         | Examples + starter workspace              |
| /data/bmt-ai-os        | 300 MB         | Metadata DB, RAG ingest queue, cache      |
| /data/logs             | 200 MB         | Log rotation at 100 MB                    |
| **Total**              | **~14 GB**     | Recommended minimum disk: 64 GB           |

### Full (~25 GB total on /data)

Suitable for: Jetson Orin Nano Super (16 GB RAM), high-spec RK3588 boards.
Default model: `qwen2.5-coder:14b` (9.0 GB)

| Directory              | Estimated Size | Contents                                  |
|------------------------|----------------|-------------------------------------------|
| /data/ollama/models    | 14.0 GB        | qwen2.5-coder:14b + qwen2.5:7b + embedder|
| /data/chromadb         | 2.0 GB         | Up to 1M vectors                          |
| /data/docker           | 6.0 GB         | Container images + training image         |
| /data/training         | 2.0 GB         | Datasets, multiple checkpoints, adapters  |
| /data/notebooks        | 500 MB         | Full workspace with sample projects       |
| /data/bmt-ai-os        | 500 MB         | Extended cache for RAG                    |
| /data/logs             | 500 MB         | Log rotation at 200 MB                    |
| **Total**              | **~25.5 GB**   | Recommended minimum disk: 128 GB          |

---

## Storage Paths Reference

Quick-reference table for all paths used by services and scripts.

| Purpose               | Path                              | Owner       | Mode |
|-----------------------|-----------------------------------|-------------|------|
| Ollama models         | /data/ollama/models/blobs/        | root        | 0755 |
| Ollama manifests      | /data/ollama/models/manifests/    | root        | 0755 |
| ChromaDB data         | /data/chromadb/                   | nobody      | 0755 |
| Training datasets     | /data/training/datasets/          | bmt         | 0755 |
| Training runs         | /data/training/runs/              | bmt         | 0755 |
| Named adapters        | /data/training/adapters/          | bmt         | 0755 |
| Jupyter notebooks     | /data/notebooks/workspace/        | bmt         | 0755 |
| Docker data root      | /data/docker/                     | root        | 0710 |
| Controller state DB   | /data/bmt-ai-os/db/               | bmt         | 0755 |
| RAG ingest queue      | /data/bmt-ai-os/rag/ingest-queue/ | bmt         | 0755 |
| Inference cache       | /data/bmt-ai-os/cache/            | bmt         | 0755 |
| API keys / secrets    | /data/secrets/api-keys.env        | root        | 0600 |
| TLS certificates      | /data/secrets/tls/                | root        | 0700 |
| Controller logs       | /data/logs/bmt-ai-os/             | bmt         | 0755 |
| System config         | /etc/bmt-ai-os/config.toml        | root        | 0644 |
| Hardware profile      | /etc/bmt-ai-os/hardware.toml      | root        | 0644 |
| Provider config       | /etc/bmt-ai-os/providers.toml     | root        | 0644 |

---

## First-Boot Initialisation

On first boot, `/opt/bmt-ai-os/scripts/first-boot.sh` runs before any AI service starts:

1. Detect total RAM and available storage; write `/etc/bmt-ai-os/hardware.toml`.
2. Select preset (lite / standard / full) based on RAM: <8 GB → lite, 8–12 GB → standard, >12 GB → full.
3. Create all `/data/*` subdirectories with correct ownership and permissions.
4. Write Docker daemon config pointing data root at `/data/docker`.
5. Pull default Qwen model via Ollama.
6. Initialise ChromaDB default collection.
7. Generate coding tool configs (Claude Code, Aider, Continue) pointing at `:8080`.
8. Mark first boot complete via `/data/bmt-ai-os/.first-boot-done`.

---

## Security Considerations

- `/data/secrets/` is mode `0700` owned by root. API keys are never world-readable.
- The rootfs slots are mounted read-write only during OTA write; otherwise, consider
  remounting rootfs read-only post-boot for additional tamper resistance.
- `/tmp` and `/run` are tmpfs — no sensitive data persists across reboots from these paths.
- Log files under `/data/logs/` are rotated to prevent disk exhaustion (see logrotate config).

---

## Related Files

- `bmt-ai-os/runtime/partition-table.sh` — Script to partition a block device
- `bmt-ai-os/runtime/fstab` — Default fstab template
- `bmt-ai-os/ai-stack/docker-compose.yml` — Defines named volumes
- `docs/architecture/boot-sequence.md` — OpenRC service start order
- `docs/architecture/system-overview.md` — Full system layer diagram
