# Installation Guide

## Hardware Requirements

### Minimum (Lite Preset)
- ARM64 board with 8GB RAM
- 32GB storage (SD card or eMMC)
- Ethernet or Wi-Fi for initial setup

### Recommended (Standard Preset)
- ARM64 board with 16GB RAM
- 64GB+ storage
- NPU/GPU accelerator

### Supported Boards

| Board | RAM | Storage | NPU | Status |
|-------|-----|---------|-----|--------|
| NVIDIA Jetson Orin Nano Super | 8GB | 128GB NVMe | 67 TOPS CUDA | Tier 1 |
| Orange Pi 5 / ROCK 5B (RK3588) | 8-32GB | eMMC/NVMe | 6 TOPS RKNN | Tier 1 |
| Raspberry Pi 5 + AI HAT+ 2 | 8GB | SD card | 40 TOPS Hailo | Tier 1 |

## Flash the OS Image

> **Note:** Pre-built images are not yet available. BMT AI OS is in active development. Use the [development setup](dev-setup.md) for now.

### When Available

```bash
# Download image for your board
wget https://releases.bmtaios.dev/2026.4.9/bmt_ai_os-jetson-orin-2026.4.9.img.gz

# Flash to SD card / eMMC
gunzip bmt_ai_os-jetson-orin-2026.4.9.img.gz
sudo dd if=bmt_ai_os-jetson-orin-2026.4.9.img of=/dev/sdX bs=4M status=progress

# Boot the board
# Dashboard available at http://<device-ip>:9090
```

## Build from Source

```bash
git clone https://github.com/bemindlabs/bmt_ai_os.git
cd bmt_ai_os

# Build ARM64 image
make O=output defconfig BR2_DEFCONFIG=bmt_ai_os/kernel/defconfig
make

# Test with QEMU
qemu-system-aarch64 \
  -M virt -cpu cortex-a72 -m 4G \
  -kernel output/images/Image \
  -drive file=output/images/rootfs.ext4,format=raw \
  -nographic
```

## First Boot

1. Connect Ethernet or configure Wi-Fi
2. The OS auto-starts: containerd → Ollama → ChromaDB → Controller
3. First-boot script pulls the default model preset based on detected hardware
4. Dashboard available at `http://<device-ip>:9090`
5. TUI available via SSH: `ssh user@<device-ip>` then `bmt_ai_os tui`

## Next Steps

- [Quick Start](quick-start.md) — run your first query
- [IDE Integration](../ide-integration/index.md) — connect Cursor, Copilot, or Cody
- [Provider Configuration](../architecture/provider-layer.md) — add cloud fallback
