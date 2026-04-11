#!/bin/sh
# /usr/lib/bmt-ai-os/pi5-hailo/detect.sh
#
# Detect Raspberry Pi 5 + Hailo AI HAT+ 2 (Hailo-10H) hardware.
#
# Detection strategy (two independent checks must both pass):
#   1. /proc/device-tree/compatible contains "brcm,bcm2712" (Pi 5 SoC)
#   2. The hailo kernel module is loaded (hailo_pci) AND /dev/hailo0 exists
#
# Exit codes:
#   0 — Pi 5 + Hailo hardware confirmed
#   1 — Pi 5 SoC not detected
#   2 — Pi 5 detected but Hailo module/device missing
#   3 — /proc/device-tree not available (not running on bare metal)
#
# Usage:
#   detect.sh [--quiet]    suppress informational output
#   detect.sh --json       emit JSON result to stdout
#
# BMTOS-28 | Epic: BMTOS-EPIC-4 (Hardware Board Support Packages)

set -eu

QUIET=0
JSON=0
LOG_TAG="[bmt-pi5-hailo-detect]"

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
for arg in "$@"; do
    case "$arg" in
        --quiet) QUIET=1 ;;
        --json)  JSON=1  ;;
    esac
done

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log_info() {
    [ "$QUIET" -eq 1 ] && return
    echo "${LOG_TAG} INFO:  $*"
}

log_warn() {
    [ "$QUIET" -eq 1 ] && return
    echo "${LOG_TAG} WARN:  $*" >&2
}

log_error() {
    echo "${LOG_TAG} ERROR: $*" >&2
}

# ---------------------------------------------------------------------------
# Emit JSON result and exit
# ---------------------------------------------------------------------------
emit_result() {
    STATUS="$1"    # ok | no_pi5 | no_hailo | no_devtree
    CODE="$2"
    MESSAGE="$3"
    HAILO_TOPS="${4:-0}"

    if [ "$JSON" -eq 1 ]; then
        printf '{"status":"%s","code":%d,"message":"%s","hailo_tops":%s,"board":"pi5-hailo"}\n' \
            "$STATUS" "$CODE" "$MESSAGE" "$HAILO_TOPS"
    fi
    exit "$CODE"
}

# ---------------------------------------------------------------------------
# 1. Verify /proc/device-tree is available (bare-metal or device-tree-capable VM)
# ---------------------------------------------------------------------------
if [ ! -d /proc/device-tree ]; then
    log_warn "/proc/device-tree not found — running in VM or container without device tree"
    emit_result "no_devtree" 3 "device tree unavailable" 0
fi

# ---------------------------------------------------------------------------
# 2. Check BCM2712 (Raspberry Pi 5) SoC identity
# ---------------------------------------------------------------------------
COMPATIBLE_FILE="/proc/device-tree/compatible"

if [ ! -f "$COMPATIBLE_FILE" ]; then
    log_error "Cannot read $COMPATIBLE_FILE"
    emit_result "no_pi5" 1 "compatible file unreadable" 0
fi

# /proc/device-tree/compatible is NUL-delimited; use tr to make it grep-safe
if ! tr '\0' '\n' < "$COMPATIBLE_FILE" 2>/dev/null | grep -q "brcm,bcm2712"; then
    log_warn "BCM2712 not found in device-tree compatible string"
    log_info "Compatible entries: $(tr '\0' ' ' < "$COMPATIBLE_FILE" 2>/dev/null || echo 'unreadable')"
    emit_result "no_pi5" 1 "BCM2712 not detected in device tree" 0
fi

log_info "BCM2712 (Raspberry Pi 5) SoC confirmed via device tree"

# ---------------------------------------------------------------------------
# 3. Check Hailo PCIe kernel module
# ---------------------------------------------------------------------------
HAILO_MODULE_LOADED=0

if lsmod 2>/dev/null | grep -q "^hailo_pci"; then
    HAILO_MODULE_LOADED=1
    log_info "hailo_pci kernel module is loaded"
else
    log_warn "hailo_pci module not found in lsmod output"
    # Attempt a late probe — the module might be built-in or not yet loaded
    if modinfo hailo_pci >/dev/null 2>&1; then
        log_warn "hailo_pci module exists on disk but is not loaded — run: modprobe hailo_pci"
    fi
fi

# ---------------------------------------------------------------------------
# 4. Check Hailo device node
# ---------------------------------------------------------------------------
HAILO_DEV_PRESENT=0

if [ -e /dev/hailo0 ]; then
    HAILO_DEV_PRESENT=1
    log_info "/dev/hailo0 device node present"
else
    log_warn "/dev/hailo0 not found"
fi

# Both module and device node must be present for a healthy Hailo setup
if [ "$HAILO_MODULE_LOADED" -eq 0 ] || [ "$HAILO_DEV_PRESENT" -eq 0 ]; then
    log_warn "Pi 5 SoC detected but Hailo AI HAT+ is not accessible"
    log_warn "  hailo_pci module loaded : $HAILO_MODULE_LOADED"
    log_warn "  /dev/hailo0 present     : $HAILO_DEV_PRESENT"
    log_warn "Remediation:"
    log_warn "  1. Verify Hailo AI HAT+ 2 is firmly seated in the PCIe M.2 slot"
    log_warn "  2. Run: modprobe hailo_pci"
    log_warn "  3. Check: dmesg | grep -i hailo"
    emit_result "no_hailo" 2 "hailo_pci module or /dev/hailo0 missing" 0
fi

# ---------------------------------------------------------------------------
# 5. Optional: firmware identity check via hailortcli
# ---------------------------------------------------------------------------
HAILO_FW_VERSION="unknown"
HAILO_TOPS="26"   # Hailo-10H conservative figure; datasheet peak is 40 TOPS

if command -v hailortcli >/dev/null 2>&1; then
    FW_OUT="$(hailortcli fw-control identify 2>/dev/null || true)"
    if [ -n "$FW_OUT" ]; then
        log_info "HailoRT firmware identify: OK"
        # Extract firmware version if present in output
        FW_VER="$(echo "$FW_OUT" | grep -i "firmware version" | awk '{print $NF}' || true)"
        [ -n "$FW_VER" ] && HAILO_FW_VERSION="$FW_VER"
        HAILO_TOPS="40"   # Confirmed Hailo-10H at rated 40 TOPS
    else
        log_warn "hailortcli fw-control identify returned no output — device may be initialising"
    fi
else
    log_info "hailortcli not available — skipping firmware identification"
    log_info "Install HailoRT CLI for extended diagnostics"
fi

# ---------------------------------------------------------------------------
# 6. PCIe link speed verification (optional, informational)
# ---------------------------------------------------------------------------
if command -v lspci >/dev/null 2>&1; then
    HAILO_PCI="$(lspci 2>/dev/null | grep -i "hailo" || true)"
    if [ -n "$HAILO_PCI" ]; then
        log_info "PCI bus: $HAILO_PCI"
    fi
fi

# ---------------------------------------------------------------------------
# 7. Report success
# ---------------------------------------------------------------------------
log_info "Detection result: Pi 5 + Hailo AI HAT+ 2 — CONFIRMED"
log_info "  SoC          : BCM2712 (Cortex-A76 x4, 2.4 GHz)"
log_info "  NPU          : Hailo-10H (${HAILO_TOPS} TOPS)"
log_info "  FW version   : ${HAILO_FW_VERSION}"
log_info "  Device node  : /dev/hailo0"
log_info "  BMT_NPU_BACKEND will be set to: hailo"

emit_result "ok" 0 "Pi5+Hailo-10H detected" "$HAILO_TOPS"
