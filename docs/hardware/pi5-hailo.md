# Raspberry Pi 5 + AI HAT+ 2 Setup

The Raspberry Pi 5 with the AI HAT+ 2 (Hailo-10H) provides 40 TOPS of dedicated AI acceleration, making it a capable and accessible edge inference platform with the largest community of any ARM64 board.

## Specifications

| Attribute | Value |
|-----------|-------|
| SoC | BCM2712 (Cortex-A76 quad-core) |
| NPU | Hailo-10H (40 TOPS) via AI HAT+ 2 |
| RAM | 8 GB LPDDR4X |
| Inference (1.5B, Hailo) | ~9.5 tok/s |
| Inference (7B Q4, CPU) | 2–4 tok/s |
| Training | LoRA <1B CPU only (~6 hrs) |
| Price | ~$80 (Pi 5) + ~$130 (AI HAT+ 2) = ~$210 total |

!!! note "Hailo model size limit"
    The Hailo-10H effectively accelerates models up to ~1.5B parameters. Larger models fall back to CPU automatically. For 7B inference, expect 2–4 tok/s on the A76 CPU cores.

## Prerequisites

- Raspberry Pi 5 (8GB recommended)
- Raspberry Pi AI HAT+ 2 (Hailo-10H)
- 64GB+ microSD card or USB SSD
- Raspberry Pi OS (64-bit, Bookworm)

## Hardware Assembly

The AI HAT+ 2 connects to the Raspberry Pi 5 via the PCIe M.2 HAT slot:

1. Power off the Pi 5
2. Attach the AI HAT+ 2 to the 40-pin GPIO header and secure with standoffs
3. Connect the FPC ribbon cable from the HAT to the Pi 5 PCIe connector
4. Power on — the Hailo device appears at `/dev/hailo0`

## Installation

### 1. Install Raspberry Pi OS

Flash [Raspberry Pi OS Lite (64-bit)](https://www.raspberrypi.com/software/) using Raspberry Pi Imager.

### 2. Enable PCIe Gen 3 (Optional)

For maximum Hailo bandwidth, enable PCIe Gen 3 in `/boot/firmware/config.txt`:

```ini
# /boot/firmware/config.txt
dtparam=pciex1_gen=3
```

### 3. Install HailoRT

```bash
# Add Hailo APT repository
curl -s https://hailo.ai/linux/hailo-public.key | sudo apt-key add -
echo "deb https://hailo.ai/linux bookworm main" | sudo tee /etc/apt/sources.list.d/hailo.list
sudo apt update
sudo apt install -y hailort hailo-all
```

Verify the Hailo device is detected:

```bash
hailortcli fw-control identify
```

### 4. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
sudo systemctl enable --now docker
```

### 5. Deploy BMT AI OS

```bash
git clone https://github.com/bemindlabs/bmt-ai-os.git
cd bmt-ai-os

# Pass the Hailo device to the container
docker compose -f docker-compose.dev.yml up -d
```

To pass the Hailo device into the Ollama container, add to `docker-compose.dev.yml`:

```yaml
ollama:
  devices:
    - /dev/hailo0:/dev/hailo0
```

### 6. Pull a Model

```bash
# 1.5B — recommended for Hailo acceleration
docker exec bmt-ollama ollama pull qwen2.5-coder:1.5b

# 7B — CPU fallback
docker exec bmt-ollama ollama pull qwen2.5-coder:7b
```

## HailoRT Configuration

HailoRT requires compiled HEF (Hailo Executable Format) model files. Standard GGUF models do not run on Hailo directly. BMT AI OS includes pre-compiled HEF files for the recommended Qwen models.

!!! warning "Model conversion"
    Running a model on Hailo requires converting it to HEF format using the Hailo Model Zoo or Dataflow Compiler. This is handled automatically for pre-approved models in the BMT AI OS model registry. Custom models require manual conversion.

## Performance Tips

- Use the `lite` model preset (`qwen3.5-1.5b` or similar) to get full Hailo acceleration
- For 7B models, CPU inference at 2–4 tok/s is still usable for coding assistance
- Enable PCIe Gen 3 for ~10% throughput improvement on Hailo
- Cooling is important — the Pi 5 throttles under sustained load; use an active cooler

## Without AI HAT+

The Pi 5 works without the AI HAT+ 2 in CPU-only mode:

| Mode | Models | Performance |
|------|--------|-------------|
| CPU only | 1–3B | 3–7 tok/s |
| With Hailo | 1.5B (Hailo) + 7B (CPU) | 9.5 tok/s / 2–4 tok/s |

## Known Issues

- HailoRT driver is not mainlined in upstream Linux kernel
- PCIe Gen 3 mode requires a good-quality power supply (5A USB-C)
- Some Hailo model conversions require x86 host (Dataflow Compiler is x86-only)
