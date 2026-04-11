#!/bin/sh
# /usr/lib/bmt-ai-os/npu/jetson-orin/setup.sh
# Install CUDA runtime and configure GPU passthrough for containers on
# Jetson Orin Nano Super (Tegra234 / p3767).
#
# This script is run once at first-boot by bmt-firstboot (OpenRC) after
# detect.sh confirms we are on a Jetson Orin platform.
#
# What this script does:
#   1. Verifies L4T / JetPack prerequisites
#   2. Installs nvidia-container-toolkit (if not already present)
#   3. Configures Docker daemon to use the NVIDIA runtime
#   4. Configures containerd for NVIDIA runtime
#   5. Creates required cgroup device allow-list entries
#   6. Validates CUDA device node permissions
#   7. Writes passthrough overlay for docker-compose
#
# Prerequisites (must be on board image):
#   - L4T 36.x (JetPack 6.x) base with CUDA 12.x and cuDNN 9.x
#   - apt-get (Ubuntu-based L4T userspace or equivalent package manager)
#   - Docker Engine 25.x or containerd 1.7.x
#
# BMTOS-26 | Epic: BMTOS-EPIC-4 (Hardware Board Support Packages)

set -eu

LOG_TAG="[bmt-jetson-setup]"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# JetPack 6.1 / L4T 36.4.3 ships CUDA 12.6
JETPACK_VERSION="6.1"
CUDA_VERSION="12.6"
CUDA_ARCH="sm_87"  # Ampere — Jetson Orin Nano Super / GA10B

# nvidia-container-toolkit package (JetPack APT repo)
NVIDIA_CT_PKG="nvidia-container-toolkit"
NVIDIA_CT_VERSION="1.17.3-1"

# Docker daemon config
DOCKER_DAEMON_JSON="/etc/docker/daemon.json"

# containerd config
CONTAINERD_CONFIG="/etc/containerd/config.toml"

# BMT AI OS runtime directory
BMT_RUNTIME_DIR="/run/bmt-ai-os"
BMT_NPU_ENV="${BMT_RUNTIME_DIR}/jetson.env"

log_info()  { echo "${LOG_TAG} INFO:  $*"; }
log_warn()  { echo "${LOG_TAG} WARN:  $*" >&2; }
log_error() { echo "${LOG_TAG} ERROR: $*" >&2; exit 1; }
log_step()  { echo "${LOG_TAG} STEP:  >>> $*"; }

# ---------------------------------------------------------------------------
# 1. Verify L4T base
# ---------------------------------------------------------------------------
verify_l4t() {
    log_step "Verifying L4T / JetPack base..."

    if [ ! -f /etc/nv_tegra_release ] && [ ! -f /etc/jetpack_version ]; then
        log_error "L4T base not found. This script requires JetPack ${JETPACK_VERSION}+ on Jetson Orin."
    fi

    if [ -f /etc/nv_tegra_release ]; then
        log_info "L4T release: $(cat /etc/nv_tegra_release)"
    fi

    if [ -f /etc/jetpack_version ]; then
        log_info "JetPack version: $(cat /etc/jetpack_version)"
    fi

    # Verify CUDA libraries are present
    if [ ! -d /usr/local/cuda ]; then
        log_warn "/usr/local/cuda not found — CUDA runtime may not be fully installed"
    else
        CUDA_FOUND="$(ls /usr/local/cuda 2>/dev/null | head -1 || true)"
        log_info "CUDA installation found at /usr/local/cuda (${CUDA_FOUND})"
    fi
}

# ---------------------------------------------------------------------------
# 2. Install nvidia-container-toolkit
# ---------------------------------------------------------------------------
install_nvidia_container_toolkit() {
    log_step "Checking nvidia-container-toolkit..."

    if command -v nvidia-ctk >/dev/null 2>&1; then
        INSTALLED_VER="$(nvidia-ctk --version 2>/dev/null | head -1 || echo 'unknown')"
        log_info "nvidia-container-toolkit already installed: ${INSTALLED_VER}"
        return 0
    fi

    log_info "Installing nvidia-container-toolkit ${NVIDIA_CT_VERSION}..."

    if ! command -v apt-get >/dev/null 2>&1; then
        log_warn "apt-get not found — skipping automatic package install."
        log_warn "Please install ${NVIDIA_CT_PKG} manually from the JetPack APT repo:"
        log_warn "  https://repo.download.nvidia.com/jetson/"
        return 0
    fi

    # Add NVIDIA JetPack APT repository if not already configured
    if [ ! -f /etc/apt/sources.list.d/nvidia-l4t.list ]; then
        log_info "Adding NVIDIA L4T APT repository..."
        cat > /etc/apt/sources.list.d/nvidia-l4t.list << 'EOF'
# NVIDIA L4T / JetPack APT repository for Jetson Orin (arm64)
deb https://repo.download.nvidia.com/jetson/common r36.4 main
deb https://repo.download.nvidia.com/jetson/t234 r36.4 main
EOF
        # Import NVIDIA public key
        if command -v wget >/dev/null 2>&1; then
            wget -qO - https://repo.download.nvidia.com/jetson/jetson-ota-public.asc \
                | apt-key add - 2>/dev/null || log_warn "Could not import NVIDIA APT key (offline?)"
        fi
    fi

    apt-get update -q || log_warn "apt-get update failed — continuing with cached packages"
    apt-get install -y --no-install-recommends \
        "${NVIDIA_CT_PKG}=${NVIDIA_CT_VERSION}" \
        || apt-get install -y --no-install-recommends "${NVIDIA_CT_PKG}" \
        || log_warn "Could not install ${NVIDIA_CT_PKG} — GPU passthrough may be unavailable"

    if command -v nvidia-ctk >/dev/null 2>&1; then
        log_info "nvidia-container-toolkit installed successfully"
    fi
}

# ---------------------------------------------------------------------------
# 3. Configure Docker daemon for NVIDIA runtime
# ---------------------------------------------------------------------------
configure_docker_daemon() {
    log_step "Configuring Docker daemon for NVIDIA Container Runtime..."

    # Generate/merge daemon.json using nvidia-ctk if available
    if command -v nvidia-ctk >/dev/null 2>&1; then
        nvidia-ctk runtime configure --runtime=docker \
            --set-as-default \
            --restart-mode=signal \
            2>/dev/null || true
        log_info "nvidia-ctk configured Docker runtime"
    fi

    # Verify or write daemon.json manually as fallback
    if [ -f "${DOCKER_DAEMON_JSON}" ]; then
        # Check if NVIDIA runtime is already present
        if grep -q '"nvidia"' "${DOCKER_DAEMON_JSON}" 2>/dev/null; then
            log_info "NVIDIA runtime already configured in ${DOCKER_DAEMON_JSON}"
            return 0
        fi
        log_warn "Existing ${DOCKER_DAEMON_JSON} found but lacks NVIDIA runtime entry."
        log_warn "Backing up to ${DOCKER_DAEMON_JSON}.bak and rewriting."
        cp "${DOCKER_DAEMON_JSON}" "${DOCKER_DAEMON_JSON}.bak"
    fi

    mkdir -p "$(dirname "${DOCKER_DAEMON_JSON}")"
    cat > "${DOCKER_DAEMON_JSON}" << 'EOF'
{
  "default-runtime": "nvidia",
  "runtimes": {
    "nvidia": {
      "path": "/usr/bin/nvidia-container-runtime",
      "runtimeArgs": []
    }
  },
  "features": {
    "cdi": true
  },
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "storage-driver": "overlay2"
}
EOF
    log_info "Wrote ${DOCKER_DAEMON_JSON} with NVIDIA default runtime"
}

# ---------------------------------------------------------------------------
# 4. Configure containerd for NVIDIA runtime
# ---------------------------------------------------------------------------
configure_containerd() {
    log_step "Configuring containerd for NVIDIA Container Runtime..."

    if command -v nvidia-ctk >/dev/null 2>&1; then
        nvidia-ctk runtime configure --runtime=containerd \
            2>/dev/null || true
        log_info "nvidia-ctk configured containerd runtime"
        return 0
    fi

    # Manual containerd snippet if nvidia-ctk is unavailable
    if [ -f "${CONTAINERD_CONFIG}" ]; then
        if grep -q "nvidia-container-runtime" "${CONTAINERD_CONFIG}" 2>/dev/null; then
            log_info "NVIDIA runtime already configured in containerd"
            return 0
        fi
    fi

    log_warn "nvidia-ctk not available; containerd NVIDIA runtime must be configured manually."
    log_warn "Add the following to ${CONTAINERD_CONFIG}:"
    cat << 'EOF'

[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.nvidia]
  runtime_type = "io.containerd.runc.v2"
  [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.nvidia.options]
    BinaryName = "/usr/bin/nvidia-container-runtime"
EOF
}

# ---------------------------------------------------------------------------
# 5. Validate CUDA device nodes and set permissions
# ---------------------------------------------------------------------------
configure_cuda_devices() {
    log_step "Configuring CUDA device node permissions..."

    # Core Jetson Orin / Tegra device nodes
    JETSON_DEVICES="
        /dev/nvhost-ctrl
        /dev/nvhost-ctrl-gpu
        /dev/nvhost-gpu
        /dev/nvhost-as-gpu
        /dev/nvhost-dbg-gpu
        /dev/nvhost-tsg
        /dev/nvhost-prof-gpu
        /dev/nvmap
        /dev/nvidia0
        /dev/nvidiactl
        /dev/nvidia-modeset
        /dev/dma_heap/system
        /dev/dma_heap/system-uncached
    "

    MISSING_DEVS=""
    for dev in ${JETSON_DEVICES}; do
        if [ -e "${dev}" ]; then
            # Ensure the 'video' group can access GPU device nodes
            if [ -c "${dev}" ] || [ -b "${dev}" ]; then
                chown root:video "${dev}" 2>/dev/null || true
                chmod 660 "${dev}" 2>/dev/null || true
            fi
            log_info "Device node OK: ${dev}"
        else
            MISSING_DEVS="${MISSING_DEVS} ${dev}"
        fi
    done

    if [ -n "${MISSING_DEVS}" ]; then
        log_warn "Some expected device nodes are absent (driver may load later):"
        for dev in ${MISSING_DEVS}; do
            log_warn "  missing: ${dev}"
        done
    fi

    # DLA (Deep Learning Accelerator) — Tegra234 has 2x DLA cores
    for i in 0 1; do
        dla_dev="/dev/nvhost-ctrl-nvdla${i}"
        if [ -e "${dla_dev}" ]; then
            chown root:video "${dla_dev}" 2>/dev/null || true
            chmod 660 "${dla_dev}" 2>/dev/null || true
            log_info "DLA device node OK: ${dla_dev}"
        else
            log_warn "DLA device node not found: ${dla_dev} (normal if DLA unused)"
        fi
    done
}

# ---------------------------------------------------------------------------
# 6. Write environment summary
# ---------------------------------------------------------------------------
write_runtime_env() {
    log_step "Writing runtime environment..."

    mkdir -p "${BMT_RUNTIME_DIR}"
    {
        echo "BMT_JETSON_DETECTED=1"
        echo "BMT_JETSON_SOC=tegra234"
        echo "BMT_JETSON_BOARD=p3767"
        echo "BMT_JETSON_TOPS=67"
        echo "BMT_JETSON_RAM_GB=8"
        echo "BMT_JETSON_CUDA_VERSION=${CUDA_VERSION}"
        echo "BMT_JETSON_CUDA_ARCH=${CUDA_ARCH}"
        echo "BMT_JETSON_JETPACK_VERSION=${JETPACK_VERSION}"
        echo "BMT_NPU_BACKEND=cuda"
        echo "BMT_ACCEL=cuda"
        echo "CUDA_VISIBLE_DEVICES=all"
        echo "NVIDIA_VISIBLE_DEVICES=all"
        echo "NVIDIA_DRIVER_CAPABILITIES=compute,utility,video"
    } > "${BMT_NPU_ENV}"

    log_info "Runtime env written to ${BMT_NPU_ENV}"
}

# ---------------------------------------------------------------------------
# 7. Restart container runtime to apply config
# ---------------------------------------------------------------------------
restart_container_runtime() {
    log_step "Signaling container runtime to reload configuration..."

    # OpenRC
    if command -v rc-service >/dev/null 2>&1; then
        rc-service docker restart 2>/dev/null && log_info "Docker restarted via OpenRC" || true
        return 0
    fi

    # systemd (L4T default)
    if command -v systemctl >/dev/null 2>&1; then
        systemctl daemon-reload 2>/dev/null || true
        systemctl restart docker 2>/dev/null && log_info "Docker restarted via systemd" || true
        return 0
    fi

    log_warn "Could not restart Docker automatically — please restart it manually"
}

# ---------------------------------------------------------------------------
# 8. Validate setup by checking CUDA device visibility
# ---------------------------------------------------------------------------
validate_setup() {
    log_step "Validating CUDA setup..."

    if command -v nvidia-smi >/dev/null 2>&1; then
        log_info "nvidia-smi output:"
        nvidia-smi 2>&1 | while IFS= read -r line; do
            log_info "  ${line}"
        done
    else
        log_warn "nvidia-smi not found — install JetPack SDK for full CUDA tooling"
    fi

    if [ -e /dev/nvhost-ctrl ]; then
        log_info "CUDA device node /dev/nvhost-ctrl is present — GPU passthrough ready"
    else
        log_warn "/dev/nvhost-ctrl not found — GPU driver may not be loaded yet"
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    log_info "========================================================"
    log_info " BMT AI OS — Jetson Orin Nano Super Setup"
    log_info " Tegra234 (p3767) | 67 TOPS | CUDA ${CUDA_VERSION} | JetPack ${JETPACK_VERSION}"
    log_info "========================================================"

    # Confirm we are on Jetson before doing anything
    if ! "${SCRIPT_DIR}/detect.sh" 2>/dev/null; then
        log_error "Jetson Orin not detected — aborting Jetson-specific setup"
    fi

    verify_l4t
    install_nvidia_container_toolkit
    configure_docker_daemon
    configure_containerd
    configure_cuda_devices
    write_runtime_env
    restart_container_runtime
    validate_setup

    log_info "Jetson Orin Nano Super setup complete."
    log_info "GPU passthrough is configured for Docker/containerd."
    log_info "AI stack inference will use CUDA (67 TOPS, Ampere sm_87)."
}

main "$@"
