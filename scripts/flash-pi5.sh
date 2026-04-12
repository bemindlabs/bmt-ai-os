#!/usr/bin/env bash
# scripts/flash-pi5.sh — Flash BMT AI OS image to SD card for Raspberry Pi 5
#
# Usage:
#   ./scripts/flash-pi5.sh /dev/sdX                  # Flash to SD card
#   ./scripts/flash-pi5.sh /dev/sdX --image path.img  # Custom image path
#   ./scripts/flash-pi5.sh --list                      # List available devices
#
# BMTOS-163 | Epic: BMTOS-EPIC-22

set -euo pipefail

# ─── Constants ───────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_IMAGE="${PROJECT_ROOT}/output/images/bmt_ai_os-arm64.img"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

# ─── Usage ───────────────────────────────────────────────────────────────────

usage() {
    cat <<EOF
${BOLD}BMT AI OS — Pi 5 SD Card Flash Tool${RESET}

Usage:
  $(basename "$0") <device> [OPTIONS]

Arguments:
  <device>              Target block device (e.g., /dev/sdb, /dev/mmcblk0)

Options:
  --image <path>        Path to .img file (default: output/images/bmt_ai_os-arm64.img)
  --verify              Verify write after flashing (slower but safer)
  --list                List available removable block devices
  --help                Show this help message

Safety:
  - Refuses to write to devices larger than 256 GB (likely not an SD card)
  - Refuses to write to mounted devices
  - Requires confirmation before writing
  - Uses sync to ensure data is flushed

Examples:
  $(basename "$0") /dev/sdb
  $(basename "$0") /dev/mmcblk0 --image bmt-ai-os-pi5.img --verify
  $(basename "$0") --list
EOF
}

# ─── List Devices ────────────────────────────────────────────────────────────

list_devices() {
    echo -e "${BOLD}Available removable block devices:${RESET}"
    echo ""

    if command -v lsblk &>/dev/null; then
        lsblk -d -o NAME,SIZE,TYPE,TRAN,MODEL,RM | grep -E "disk.*(usb|sd|mmc)" || true
        echo ""
        lsblk -d -o NAME,SIZE,TYPE,TRAN,MODEL | grep -E "mmcblk" || true
    elif [[ "$(uname)" == "Darwin" ]]; then
        diskutil list external physical 2>/dev/null || diskutil list
    else
        echo "  Could not detect devices. Check /dev/sd* or /dev/mmcblk*"
    fi
    echo ""
    echo -e "${YELLOW}WARNING: Double-check the device before flashing!${RESET}"
}

# ─── Validate Device ────────────────────────────────────────────────────────

validate_device() {
    local device="$1"

    # Must be a block device
    if [[ ! -b "${device}" ]]; then
        echo -e "${RED}ERROR: ${device} is not a block device${RESET}"
        exit 1
    fi

    # Refuse if mounted
    if mount | grep -q "^${device}"; then
        echo -e "${RED}ERROR: ${device} (or a partition) is mounted. Unmount first:${RESET}"
        mount | grep "^${device}"
        exit 1
    fi

    # Refuse if too large (safety: >256 GB is probably not an SD card)
    local size_bytes
    if [[ "$(uname)" == "Linux" ]]; then
        size_bytes=$(blockdev --getsize64 "${device}" 2>/dev/null || echo 0)
    elif [[ "$(uname)" == "Darwin" ]]; then
        size_bytes=$(diskutil info "${device}" | grep "Disk Size" | awk '{print $5}' | tr -d '(' || echo 0)
    else
        size_bytes=0
    fi

    local max_bytes=$((256 * 1024 * 1024 * 1024))  # 256 GB
    if [[ ${size_bytes} -gt ${max_bytes} ]]; then
        echo -e "${RED}ERROR: ${device} is larger than 256 GB — probably not an SD card${RESET}"
        echo "  Size: $((size_bytes / 1024 / 1024 / 1024)) GB"
        exit 1
    fi
}

# ─── Flash ───────────────────────────────────────────────────────────────────

flash_image() {
    local device="$1"
    local image="$2"
    local verify="${3:-false}"

    # Confirm
    local img_size
    img_size="$(du -sh "${image}" | cut -f1)"
    echo ""
    echo -e "${BOLD}╔═══════════════════════════════════════════╗${RESET}"
    echo -e "${BOLD}║      BMT AI OS — Flash to SD Card         ║${RESET}"
    echo -e "${BOLD}╠═══════════════════════════════════════════╣${RESET}"
    printf  "${BOLD}║${RESET}  %-14s %-26s ${BOLD}║${RESET}\n" "Image:" "$(basename "${image}")"
    printf  "${BOLD}║${RESET}  %-14s %-26s ${BOLD}║${RESET}\n" "Size:" "${img_size}"
    printf  "${BOLD}║${RESET}  %-14s %-26s ${BOLD}║${RESET}\n" "Target:" "${device}"
    echo -e "${BOLD}╚═══════════════════════════════════════════╝${RESET}"
    echo ""
    echo -e "${YELLOW}WARNING: ALL DATA on ${device} WILL BE DESTROYED${RESET}"
    echo ""
    read -rp "Type 'yes' to confirm: " confirm
    if [[ "${confirm}" != "yes" ]]; then
        echo "Aborted."
        exit 0
    fi

    echo ""
    echo -e "${CYAN}[INFO]${RESET}  Flashing ${image} → ${device}..."

    # Use dd with progress
    if command -v pv &>/dev/null; then
        pv "${image}" | dd of="${device}" bs=4M conv=fsync status=none
    else
        dd if="${image}" of="${device}" bs=4M conv=fsync status=progress
    fi

    sync
    echo -e "${GREEN}[OK]${RESET}    Flash complete"

    # Verify if requested
    if [[ "${verify}" == "true" ]]; then
        echo -e "${CYAN}[INFO]${RESET}  Verifying write..."
        local img_hash dev_hash
        img_hash=$(dd if="${image}" bs=4M status=none | sha256sum | awk '{print $1}')
        local img_bytes
        img_bytes=$(stat -c%s "${image}" 2>/dev/null || stat -f%z "${image}")
        dev_hash=$(dd if="${device}" bs=4M count=$(( (img_bytes + 4194303) / 4194304 )) status=none | head -c "${img_bytes}" | sha256sum | awk '{print $1}')

        if [[ "${img_hash}" == "${dev_hash}" ]]; then
            echo -e "${GREEN}[OK]${RESET}    Verification passed (SHA-256 match)"
        else
            echo -e "${RED}[FAIL]${RESET}  Verification FAILED — checksums differ"
            echo "  Image:  ${img_hash}"
            echo "  Device: ${dev_hash}"
            exit 1
        fi
    fi

    echo ""
    echo -e "${GREEN}${BOLD}Done!${RESET} Remove the SD card and insert into your Pi 5."
    echo ""
    echo "First boot:"
    echo "  1. Insert SD card into Pi 5"
    echo "  2. Connect Ethernet (or configure WiFi via serial console)"
    echo "  3. Power on — first boot takes ~2 minutes (rootfs resize + BSP setup)"
    echo "  4. Access dashboard at http://<pi-ip>:9090"
    echo "  5. Default login: admin / admin"
}

# ─── Main ────────────────────────────────────────────────────────────────────

main() {
    local device=""
    local image="${DEFAULT_IMAGE}"
    local verify=false

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --image)
                image="${2:?--image requires a path}"
                shift 2
                ;;
            --verify)
                verify=true
                shift
                ;;
            --list)
                list_devices
                exit 0
                ;;
            --help|-h)
                usage
                exit 0
                ;;
            -*)
                echo -e "${RED}Unknown option: $1${RESET}"
                usage
                exit 1
                ;;
            *)
                device="$1"
                shift
                ;;
        esac
    done

    if [[ -z "${device}" ]]; then
        echo -e "${RED}ERROR: No target device specified${RESET}"
        echo ""
        usage
        exit 1
    fi

    # Check image exists
    if [[ ! -f "${image}" ]]; then
        echo -e "${RED}ERROR: Image not found: ${image}${RESET}"
        echo "  Build first: ./scripts/build.sh --target pi5"
        exit 1
    fi

    # Must be root
    if [[ $EUID -ne 0 ]]; then
        echo -e "${YELLOW}This script requires root privileges for raw disk access.${RESET}"
        echo "  Re-run with: sudo $(basename "$0") $*"
        exit 1
    fi

    validate_device "${device}"
    flash_image "${device}" "${image}" "${verify}"
}

main "$@"
