# Raspberry Pi 5 — Image Flash Guide

Flash BMT AI OS onto an SD card for the Raspberry Pi 5 + AI HAT+ 2.

## Prerequisites

- Raspberry Pi 5 (4GB or 8GB)
- AI HAT+ 2 (Hailo-10H, 40 TOPS) — optional but recommended
- microSD card (16GB+ recommended, Class 10 / A2)
- USB-C power supply (5V/5A, 27W — official Pi 5 PSU recommended)
- Ethernet cable (for initial setup) or USB-to-serial adapter

## Download the Image

```bash
# Build from source
./scripts/build.sh --target pi5

# Image output: output/images/bmt_ai_os-arm64.img
```

## Flash to SD Card

### Option 1: BMT Flash Tool (Linux)

```bash
# List available devices
./scripts/flash-pi5.sh --list

# Flash (replace /dev/sdX with your SD card device)
sudo ./scripts/flash-pi5.sh /dev/sdX

# Flash with verification
sudo ./scripts/flash-pi5.sh /dev/sdX --verify
```

### Option 2: Raspberry Pi Imager (All Platforms)

1. Download [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. Click **Choose OS** → **Use custom** → select `bmt_ai_os-arm64.img`
3. Click **Choose Storage** → select your SD card
4. Click **Write**

### Option 3: dd (Linux/macOS)

```bash
# Find your SD card device
lsblk  # Linux
diskutil list  # macOS

# Flash (replace /dev/sdX — TRIPLE CHECK THE DEVICE)
sudo dd if=output/images/bmt_ai_os-arm64.img of=/dev/sdX bs=4M conv=fsync status=progress
sudo sync
```

!!! warning
    Writing to the wrong device will destroy data. Always verify the target device before flashing.

## First Boot

1. Insert the SD card into the Pi 5
2. Connect the AI HAT+ 2 to the M.2 slot (if using)
3. Connect Ethernet
4. Connect HDMI (optional — for console output)
5. Power on with USB-C

### First Boot Sequence (~2 minutes)

The first boot performs automatic setup:

1. **Hardware detection** — identifies BCM2712 + Hailo-10H
2. **BSP setup** — installs HailoRT runtime, creates device groups
3. **SSH keys** — generates ed25519 + RSA host keys
4. **Rootfs resize** — expands partition to fill the SD card
5. **AI stack start** — launches Ollama + ChromaDB containers
6. **Model pull** — downloads default model (qwen2.5:1.5b, ~1GB)

### Boot Chain

```
Pi 5 EEPROM → config.txt → kernel (Image) → OpenRC
  → S90firstboot (once)
  → bmt-pi5-env (lite profile)
  → containerd → docker
  → ai-stack (Ollama + ChromaDB)
  → bmt-controller (:8080)
  → dashboard (:9090)
```

## Access the System

### Dashboard

Open a browser and navigate to:

```
http://<pi-ip>:9090
```

Default credentials: `admin` / `admin`

Find the Pi's IP address:
```bash
# From another machine on the same network
ping bmt-ai-os.local    # mDNS (if Avahi is running)
arp -a | grep -i "dc:a6" # Pi 5 MAC prefix
```

### SSH

```bash
ssh root@<pi-ip>
# or
ssh root@bmt-ai-os.local
```

### Serial Console

Connect a USB-to-serial adapter to GPIO 14 (TX) and GPIO 15 (RX):

```bash
screen /dev/ttyUSB0 115200
# or
minicom -D /dev/ttyUSB0 -b 115200
```

## Performance (Pi 5 + AI HAT+ 2, 8GB)

| Metric | Value |
|--------|-------|
| Boot to login | ~30s |
| Boot to AI ready | ~90s |
| LLM inference (1.5B) | ~9.5 tok/s |
| Hailo NPU throughput | 40 TOPS |
| RAM usage (idle) | ~1.5 GB |
| RAM usage (inference) | ~5.5 GB |

## Troubleshooting

### No HDMI output

- Check `config.txt` has `hdmi_force_hotplug=1`
- Try a different HDMI cable or monitor
- Use serial console instead

### Hailo not detected

- Verify AI HAT+ 2 is seated properly in M.2 slot
- Check `config.txt` has `dtparam=pciex1_gen=3` and `dtoverlay=hailo-8l`
- Run: `lspci | grep Hailo` — should show Hailo device
- Run: `ls /dev/hailo*` — should show `/dev/hailo0`

### Ollama not starting

- Check logs: `docker logs bmt-ai-os-ollama-1`
- Verify memory: `free -h` — needs ~4GB free for Ollama
- Check compose: `docker compose -f /etc/bmt-ai-os/ai-stack/docker-compose.yml ps`

### SD card too slow

- Use a Class 10 / A2 rated card (Samsung EVO Plus, SanDisk Extreme)
- Consider NVMe via M.2 HAT (requires different config — Hailo uses the M.2 slot)
- USB 3.0 SSD as rootfs (modify cmdline.txt root= parameter)
