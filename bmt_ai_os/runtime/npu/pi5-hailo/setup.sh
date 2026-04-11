#!/bin/sh
# /usr/lib/bmt-ai-os/pi5-hailo/setup.sh
#
# Install HailoRT runtime and configure Hailo-10H device passthrough for
# Raspberry Pi 5 + Hailo AI HAT+ 2 on BMT AI OS.
#
# Responsibilities:
#   1. Verify running on Pi 5 (BCM2712) with Hailo hardware detected
#   2. Install HailoRT shared libraries and CLI tools
#   3. Load hailo_pci kernel module and persist via /etc/modules
#   4. Create /dev/hailo0 udev rule with correct permissions
#   5. Configure /etc/hailort/hailort.conf for BMT AI OS defaults
#   6. Add container runtime user to 'hailo' group
#   7. Write passthrough manifest for the controller to consume
#
# Prerequisites:
#   - HailoRT .deb or .tar.gz placed in /var/cache/bmt-ai-os/hailo/ OR
#     network access to download (online setup mode)
#   - Must be run as root
#
# Environment variables:
#   HAILORT_VERSION    HailoRT version to install (default: 4.20.0)
#   HAILO_SKIP_INSTALL Skip package install if HailoRT already present
#   HAILO_OFFLINE_PKG  Path to offline .tar.gz package
#   BMT_AI_OS_HOME     BMT AI OS home directory (default: /opt/bmt-ai-os)
#
# Exit codes:
#   0 — setup complete
#   1 — not running as root
#   2 — hardware detection failed
#   3 — HailoRT installation failed
#   4 — module load failed
#
# BMTOS-28 | Epic: BMTOS-EPIC-4 (Hardware Board Support Packages)

set -eu

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
HAILORT_VERSION="${HAILORT_VERSION:-4.20.0}"
BMT_AI_OS_HOME="${BMT_AI_OS_HOME:-/opt/bmt-ai-os}"
HAILO_CACHE_DIR="/var/cache/bmt-ai-os/hailo"
HAILO_CONF_DIR="/etc/hailort"
HAILO_LIB_DIR="/usr/lib"
HAILO_GROUP="hailo"
LOG_TAG="[bmt-pi5-hailo-setup]"

# HailoRT download base URL — replace with internal mirror if operating offline
HAILORT_BASE_URL="https://hailo-hailort.s3.amazonaws.com/Hailo10/${HAILORT_VERSION}"
HAILORT_TARBALL="hailort-${HAILORT_VERSION}-linux-aarch64.tar.gz"
HAILORT_TARBALL_SHA256_URL="${HAILORT_BASE_URL}/${HAILORT_TARBALL}.sha256"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DETECT_SCRIPT="${SCRIPT_DIR}/detect.sh"

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
log_info()  { echo "${LOG_TAG} INFO:  $*"; }
log_warn()  { echo "${LOG_TAG} WARN:  $*" >&2; }
log_error() { echo "${LOG_TAG} ERROR: $*" >&2; }
log_step()  { echo ""; echo "${LOG_TAG} STEP:  === $* ==="; }

# ---------------------------------------------------------------------------
# Guard: must be root
# ---------------------------------------------------------------------------
if [ "$(id -u)" -ne 0 ]; then
    log_error "This script must be run as root (sudo)"
    exit 1
fi

log_info "HailoRT runtime setup for Pi 5 + Hailo AI HAT+ 2"
log_info "HailoRT target version: ${HAILORT_VERSION}"

# ---------------------------------------------------------------------------
# Step 1: Hardware detection
# ---------------------------------------------------------------------------
log_step "Hardware Detection"

if [ -x "$DETECT_SCRIPT" ]; then
    if ! "$DETECT_SCRIPT" --quiet; then
        DETECT_RC=$?
        log_error "Hardware detection failed (exit code ${DETECT_RC})"
        log_error "Cannot configure HailoRT on non-Pi5/Hailo hardware"
        exit 2
    fi
    log_info "Hardware detection passed — Pi 5 + Hailo AI HAT+ 2 confirmed"
else
    log_warn "detect.sh not found at ${DETECT_SCRIPT} — skipping hardware check"
fi

# ---------------------------------------------------------------------------
# Step 2: Create system group for Hailo device access
# ---------------------------------------------------------------------------
log_step "System Group"

if ! getent group "$HAILO_GROUP" >/dev/null 2>&1; then
    groupadd --system "$HAILO_GROUP"
    log_info "Created system group: ${HAILO_GROUP}"
else
    log_info "Group '${HAILO_GROUP}' already exists"
fi

# Add container-runtime user (e.g. the user that runs Docker/containerd)
for user in bmt-ai-os bmt ollama root; do
    if id "$user" >/dev/null 2>&1; then
        usermod -aG "$HAILO_GROUP" "$user" 2>/dev/null || true
        log_info "Added user '${user}' to group '${HAILO_GROUP}'"
    fi
done

# ---------------------------------------------------------------------------
# Step 3: Install HailoRT shared libraries
# ---------------------------------------------------------------------------
log_step "HailoRT Library Installation"

install_hailort() {
    PKG_PATH="$1"
    log_info "Extracting HailoRT from: ${PKG_PATH}"

    EXTRACT_TMP="$(mktemp -d /tmp/hailort-install.XXXXXX)"
    # shellcheck disable=SC2064
    trap "rm -rf '${EXTRACT_TMP}'" EXIT INT TERM

    tar -xzf "$PKG_PATH" -C "$EXTRACT_TMP"

    # Install shared libraries
    if [ -f "${EXTRACT_TMP}/lib/libhailort.so.${HAILORT_VERSION}" ]; then
        install -D -m 0755 \
            "${EXTRACT_TMP}/lib/libhailort.so.${HAILORT_VERSION}" \
            "${HAILO_LIB_DIR}/libhailort.so.${HAILORT_VERSION}"

        # Create versioned and unversioned symlinks
        MAJOR="$(echo "$HAILORT_VERSION" | cut -d. -f1)"
        ln -sf "libhailort.so.${HAILORT_VERSION}" "${HAILO_LIB_DIR}/libhailort.so.${MAJOR}"
        ln -sf "libhailort.so.${HAILORT_VERSION}" "${HAILO_LIB_DIR}/libhailort.so"
        log_info "Installed libhailort.so.${HAILORT_VERSION}"
    else
        log_warn "libhailort.so not found in package — manual install may be required"
    fi

    # Install hailortcli
    if [ -f "${EXTRACT_TMP}/bin/hailortcli" ]; then
        install -D -m 0755 "${EXTRACT_TMP}/bin/hailortcli" /usr/bin/hailortcli
        log_info "Installed hailortcli to /usr/bin/hailortcli"
    fi

    # Install Python bindings if present
    if [ -d "${EXTRACT_TMP}/python" ]; then
        SITE_PACKAGES="$(python3 -c 'import site; print(site.getsitepackages()[0])' 2>/dev/null || echo /usr/lib/python3/dist-packages)"
        cp -r "${EXTRACT_TMP}/python/." "$SITE_PACKAGES/"
        log_info "Installed HailoRT Python bindings to ${SITE_PACKAGES}"
    fi

    # Install headers if present (for downstream compilation)
    if [ -d "${EXTRACT_TMP}/include/hailo" ]; then
        cp -r "${EXTRACT_TMP}/include/hailo" /usr/include/
        log_info "Installed HailoRT headers to /usr/include/hailo"
    fi

    # Refresh dynamic linker cache
    ldconfig
    rm -rf "$EXTRACT_TMP"
    trap - EXIT INT TERM
}

# Determine package source: offline path > cache dir > download
if [ -n "${HAILO_OFFLINE_PKG:-}" ] && [ -f "$HAILO_OFFLINE_PKG" ]; then
    log_info "Using offline package: ${HAILO_OFFLINE_PKG}"
    install_hailort "$HAILO_OFFLINE_PKG"

elif [ -n "${HAILO_SKIP_INSTALL:-}" ]; then
    log_info "HAILO_SKIP_INSTALL set — skipping library installation"

elif [ -f "${HAILO_CACHE_DIR}/${HAILORT_TARBALL}" ]; then
    log_info "Found cached package: ${HAILO_CACHE_DIR}/${HAILORT_TARBALL}"
    install_hailort "${HAILO_CACHE_DIR}/${HAILORT_TARBALL}"

elif command -v wget >/dev/null 2>&1 || command -v curl >/dev/null 2>&1; then
    log_info "Downloading HailoRT ${HAILORT_VERSION} from Hailo S3 bucket..."
    mkdir -p "$HAILO_CACHE_DIR"
    PKG_URL="${HAILORT_BASE_URL}/${HAILORT_TARBALL}"

    if command -v wget >/dev/null 2>&1; then
        wget -q --show-progress -O "${HAILO_CACHE_DIR}/${HAILORT_TARBALL}" "$PKG_URL" || {
            log_error "Download failed: ${PKG_URL}"
            exit 3
        }
    else
        curl -fsSL -o "${HAILO_CACHE_DIR}/${HAILORT_TARBALL}" "$PKG_URL" || {
            log_error "Download failed: ${PKG_URL}"
            exit 3
        }
    fi

    install_hailort "${HAILO_CACHE_DIR}/${HAILORT_TARBALL}"

else
    log_warn "No network tools (wget/curl) available and no cached package found"
    log_warn "Place HailoRT tarball at: ${HAILO_CACHE_DIR}/${HAILORT_TARBALL}"
    log_warn "Or set HAILO_OFFLINE_PKG=<path> and re-run this script"
    log_warn "Continuing with module load and udev configuration..."
fi

# ---------------------------------------------------------------------------
# Step 4: Load hailo_pci kernel module
# ---------------------------------------------------------------------------
log_step "Kernel Module"

MODULES_FILE="/etc/modules"
MODULES_LOAD_DIR="/etc/modules-load.d"

# Load module if not already loaded
if ! lsmod 2>/dev/null | grep -q "^hailo_pci"; then
    if modprobe hailo_pci 2>/dev/null; then
        log_info "hailo_pci module loaded successfully"
    else
        log_warn "modprobe hailo_pci failed — driver may not be installed"
        log_warn "The hailo_pci kernel module is provided by the HailoRT DKMS package."
        log_warn "After HailoRT installation completes, run: modprobe hailo_pci"
    fi
else
    log_info "hailo_pci module already loaded"
fi

# Persist module load across reboots
if [ -d "$MODULES_LOAD_DIR" ]; then
    echo "hailo_pci" > "${MODULES_LOAD_DIR}/hailo.conf"
    log_info "Persisted hailo_pci to ${MODULES_LOAD_DIR}/hailo.conf"
elif [ -f "$MODULES_FILE" ]; then
    if ! grep -q "^hailo_pci$" "$MODULES_FILE"; then
        echo "hailo_pci" >> "$MODULES_FILE"
        log_info "Appended hailo_pci to ${MODULES_FILE}"
    fi
fi

# ---------------------------------------------------------------------------
# Step 5: udev rules for /dev/hailo0 permissions
# ---------------------------------------------------------------------------
log_step "udev Rules"

UDEV_RULES_DIR="/etc/udev/rules.d"
UDEV_RULES_FILE="${UDEV_RULES_DIR}/80-hailo.rules"

mkdir -p "$UDEV_RULES_DIR"

cat > "$UDEV_RULES_FILE" << 'UDEV_EOF'
# BMT AI OS — Hailo PCIe accelerator device permissions
# Hailo-10H on Raspberry Pi 5 (BCM2712) via PCIe Gen3
# Grants read/write access to members of the 'hailo' group.
SUBSYSTEM=="hailo_pci", KERNEL=="hailo*", GROUP="hailo", MODE="0660", TAG+="uaccess"
SUBSYSTEM=="misc",      KERNEL=="hailo*", GROUP="hailo", MODE="0660", TAG+="uaccess"
# Allow udev to fire a settle event after the device appears
ACTION=="add",          KERNEL=="hailo*", RUN+="/sbin/modprobe -b hailo_pci"
UDEV_EOF

log_info "Installed udev rules to ${UDEV_RULES_FILE}"

# Reload udev rules if udevadm is available
if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules 2>/dev/null || true
    udevadm trigger --subsystem-match=hailo_pci 2>/dev/null || true
    log_info "udev rules reloaded"
fi

# ---------------------------------------------------------------------------
# Step 6: HailoRT configuration file
# ---------------------------------------------------------------------------
log_step "HailoRT Configuration"

mkdir -p "$HAILO_CONF_DIR"

cat > "${HAILO_CONF_DIR}/hailort.conf" << 'CONF_EOF'
# HailoRT runtime configuration — BMT AI OS Pi 5 target
# Documentation: https://hailo.ai/developer-zone/documentation/

[device]
# Device scheduling algorithm: round_robin | none
scheduling_algorithm = round_robin

# Batch size for inference requests
# Increase for higher throughput at the cost of latency
batch_size = 1

# Power mode: performance | ultra_performance | low_power
power_mode = performance

[logging]
# Logging level: trace | debug | info | warning | error | critical
level = warning
# Log file path (leave empty to log to stderr only)
log_file =

[scheduler]
# Scheduler timeout in milliseconds (0 = disabled)
scheduler_timeout_ms = 0
# Scheduler threshold for switching between models
scheduler_threshold = 0

[multi_process]
# Enable multi-process service (recommended for container environments)
multi_process_service = true
CONF_EOF

log_info "Wrote HailoRT config to ${HAILO_CONF_DIR}/hailort.conf"

# ---------------------------------------------------------------------------
# Step 7: Write BMT AI OS passthrough manifest
# ---------------------------------------------------------------------------
log_step "Passthrough Manifest"

MANIFEST_DIR="${BMT_AI_OS_HOME}/runtime"
mkdir -p "$MANIFEST_DIR"

cat > "${MANIFEST_DIR}/pi5-hailo-passthrough.env" << MANIFEST_EOF
# BMT AI OS — Pi 5 + Hailo AI HAT+ 2 passthrough manifest
# Generated by setup.sh on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
BMT_ACCEL=hailo
BMT_NPU_BACKEND=hailo
BMT_BOARD=pi5-hailo
BMT_SOC=bcm2712
BMT_NPU=hailo-10h
HAILORT_VERSION=${HAILORT_VERSION}
HAILO_DEVICE=/dev/hailo0
HAILO_TOPS=40
MANIFEST_EOF

log_info "Wrote passthrough manifest to ${MANIFEST_DIR}/pi5-hailo-passthrough.env"

# Also write to the runtime env dir used by the controller
mkdir -p /run/bmt-ai-os 2>/dev/null || true
cat > /run/bmt-ai-os/npu.env << 'RUN_EOF'
BMT_NPU_BACKEND=hailo
BMT_ACCEL=hailo
RUN_EOF
log_info "Updated /run/bmt-ai-os/npu.env"

# ---------------------------------------------------------------------------
# Step 8: Verify final device state
# ---------------------------------------------------------------------------
log_step "Final Verification"

PASS=1

if [ -e /dev/hailo0 ]; then
    log_info "/dev/hailo0 — PRESENT"
else
    log_warn "/dev/hailo0 — NOT PRESENT (reboot may be required if module was just loaded)"
    PASS=0
fi

if lsmod 2>/dev/null | grep -q "^hailo_pci"; then
    log_info "hailo_pci module — LOADED"
else
    log_warn "hailo_pci module — NOT LOADED"
    PASS=0
fi

if [ -f "${HAILO_LIB_DIR}/libhailort.so" ]; then
    log_info "libhailort.so — INSTALLED"
else
    log_warn "libhailort.so — NOT FOUND (install step may have been skipped)"
fi

if command -v hailortcli >/dev/null 2>&1; then
    log_info "hailortcli — AVAILABLE ($(hailortcli --version 2>/dev/null | head -1 || echo 'version unknown'))"
else
    log_info "hailortcli — NOT INSTALLED (optional diagnostics tool)"
fi

echo ""
if [ "$PASS" -eq 1 ]; then
    log_info "Pi 5 + Hailo AI HAT+ 2 setup COMPLETE"
    log_info "Start the AI stack with:"
    log_info "  docker compose -f bmt_ai_os/ai-stack/docker-compose.yml \\"
    log_info "    -f bmt_ai_os/runtime/npu/pi5-hailo/docker-compose.override.pi5-hailo.yml \\"
    log_info "    up -d"
else
    log_warn "Setup completed with warnings — a system reboot may be required"
    log_warn "After reboot, re-run this script to verify."
fi
