# Boot Sequence

## Service Start Order

```
Power On
  │
  ├── U-Boot (bootloader)
  │
  ├── Linux Kernel (ARM64)
  │     └── cgroups, namespaces, overlayfs, networking
  │
  ├── OpenRC Init System
  │     ├── 1. Networking (dhcp, dns)
  │     ├── 2. Storage (mount data partition, volumes)
  │     ├── 3. containerd
  │     ├── 4. Ollama (LLM inference)
  │     ├── 5. ChromaDB (vector database)
  │     ├── 6. Controller (orchestration)
  │     └── 7. Dashboard (:9090)
  │
  └── Ready — all services healthy
```

## First Boot

On first boot, an additional initialization step runs:

1. Create data partition and volumes
2. Detect hardware (RAM, NPU type)
3. Select model preset (lite/standard/full)
4. Pull default model from Ollama registry
5. Initialize ChromaDB collections
6. Generate coding CLI configurations

## Service Dependencies

```
networking
  └── containerd
        ├── ollama (needs containerd)
        │     └── controller (needs ollama healthy)
        │           └── dashboard (needs controller API)
        └── chromadb (needs containerd)
              └── controller (needs chromadb healthy)
```

## Health Checks

Each service has a health check polled by the controller:

| Service | Health Endpoint | Interval |
|---------|----------------|----------|
| Ollama | `GET /api/tags` | 30s |
| ChromaDB | `GET /api/v1/heartbeat` | 30s |
| Controller | `GET /health` | 30s |
| Dashboard | `GET /` | 60s |

Failed services are automatically restarted by the controller.
