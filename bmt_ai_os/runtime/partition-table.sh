#!/usr/bin/env bash
# partition-table.sh — Partition and format a block device for BMT AI OS
#
# Usage:
#   partition-table.sh [OPTIONS] <device>
#
# Options:
#   --dry-run      Print the operations that would be performed; do not write.
#   --data-size N  Size of the data partition in GiB (default: all remaining space).
#   --yes          Skip the interactive confirmation prompt (for automated installs).
#   -h, --help     Show this help message.
#
# Partition layout created:
#   p1  256 MiB   FAT32   BMT_BOOT       /boot
#   p2    4 GiB   ext4    BMT_ROOTFS_A   / (slot A)
#   p3    4 GiB   ext4    BMT_ROOTFS_B   / (slot B, standby for OTA)
#   p4  remaining ext4    BMT_DATA       /data (models, vectors, training)
#
# Minimum recommended device size: 32 GiB
#
# BMTOS-19 | Epic: BMTOS-EPIC-3 (OS Foundation & Infrastructure)

set -euo pipefail

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
readonly BOOT_SIZE_MIB=256
readonly ROOTFS_SIZE_GIB=4
readonly MIN_DEVICE_GIB=16   # Warn if device is smaller than this

readonly BOOT_LABEL="BMT_BOOT"
readonly ROOTFS_A_LABEL="BMT_ROOTFS_A"
readonly ROOTFS_B_LABEL="BMT_ROOTFS_B"
readonly DATA_LABEL="BMT_DATA"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()  { printf '\033[1;34m[INFO]\033[0m  %s\n' "$*"; }
warn()  { printf '\033[1;33m[WARN]\033[0m  %s\n' "$*" >&2; }
error() { printf '\033[1;31m[ERROR]\033[0m %s\n' "$*" >&2; }
die()   { error "$*"; exit 1; }

usage() {
    sed -n '/^# Usage:/,/^# BMTOS/p' "$0" | sed 's/^# \?//'
    exit 0
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

# Return device size in GiB (integer floor).
device_size_gib() {
    local dev="$1"
    local bytes
    bytes=$(blockdev --getsize64 "$dev" 2>/dev/null) || \
        bytes=$(cat /sys/class/block/"$(basename "$dev")"/size 2>/dev/null | awk '{print $1 * 512}') || \
        die "Cannot determine size of $dev"
    echo $(( bytes / 1024 / 1024 / 1024 ))
}

# Resolve partition device name from base device and partition number.
# Handles both /dev/sdX (→ /dev/sdX1) and /dev/mmcblkX (→ /dev/mmcblkXp1).
part_name() {
    local dev="$1"
    local num="$2"
    case "$dev" in
        *mmcblk*|*nvme*) echo "${dev}p${num}" ;;
        *)               echo "${dev}${num}"  ;;
    esac
}

# Run or echo a command depending on DRY_RUN.
run() {
    if [[ "$DRY_RUN" == "true" ]]; then
        printf '\033[0;90m[dry-run]\033[0m %s\n' "$*"
    else
        "$@"
    fi
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
DRY_RUN=false
AUTO_YES=false
DATA_SIZE_ARG=""
DEVICE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)             DRY_RUN=true;        shift ;;
        --yes|-y)              AUTO_YES=true;       shift ;;
        --data-size)           DATA_SIZE_ARG="$2";  shift 2 ;;
        --data-size=*)         DATA_SIZE_ARG="${1#*=}"; shift ;;
        -h|--help)             usage ;;
        -*)                    die "Unknown option: $1" ;;
        *)
            [[ -z "$DEVICE" ]] || die "Unexpected argument: $1"
            DEVICE="$1"
            shift
            ;;
    esac
done

[[ -n "$DEVICE" ]] || die "No block device specified. Run with --help for usage."

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
if [[ "$DRY_RUN" == "false" ]]; then
    [[ "$(id -u)" -eq 0 ]] || die "This script must be run as root."
fi

require_cmd parted
require_cmd mkfs.vfat
require_cmd mkfs.ext4
require_cmd blockdev

# Verify the device exists.
if [[ "$DRY_RUN" == "false" ]]; then
    [[ -b "$DEVICE" ]] || die "Not a block device: $DEVICE"
fi

# Check device size.
if [[ "$DRY_RUN" == "false" ]]; then
    DEVICE_GIB=$(device_size_gib "$DEVICE")
    info "Device: $DEVICE (${DEVICE_GIB} GiB)"

    if (( DEVICE_GIB < MIN_DEVICE_GIB )); then
        die "Device is ${DEVICE_GIB} GiB — minimum required is ${MIN_DEVICE_GIB} GiB."
    fi

    REQUIRED_GIB=$(( 1 + ROOTFS_SIZE_GIB * 2 + 4 ))   # boot + A + B + minimum data
    if (( DEVICE_GIB < REQUIRED_GIB )); then
        die "Device is too small. Need at least ${REQUIRED_GIB} GiB, got ${DEVICE_GIB} GiB."
    fi
else
    DEVICE_GIB=128
    info "[dry-run] Assuming device size: ${DEVICE_GIB} GiB"
fi

# ---------------------------------------------------------------------------
# Confirm before writing
# ---------------------------------------------------------------------------
info "Partition layout that will be written to $DEVICE:"
printf '  p1  %4d MiB  FAT32   %-16s  /boot\n' "$BOOT_SIZE_MIB"    "$BOOT_LABEL"
printf '  p2  %4d GiB  ext4    %-16s  / (rootfs slot A)\n' "$ROOTFS_SIZE_GIB" "$ROOTFS_A_LABEL"
printf '  p3  %4d GiB  ext4    %-16s  / (rootfs slot B, OTA standby)\n' "$ROOTFS_SIZE_GIB" "$ROOTFS_B_LABEL"

if [[ -n "$DATA_SIZE_ARG" ]]; then
    printf '  p4  %4d GiB  ext4    %-16s  /data\n' "$DATA_SIZE_ARG" "$DATA_LABEL"
else
    printf '  p4  remaining    ext4    %-16s  /data\n' "$DATA_LABEL"
fi

if [[ "$DRY_RUN" == "true" ]]; then
    warn "Dry-run mode — no changes will be made to disk."
elif [[ "$AUTO_YES" == "false" ]]; then
    warn "THIS WILL ERASE ALL DATA ON $DEVICE"
    printf '\nType YES (uppercase) to continue, anything else to abort: '
    read -r CONFIRM
    [[ "$CONFIRM" == "YES" ]] || { info "Aborted."; exit 0; }
else
    warn "Auto-confirm enabled (--yes). Proceeding without prompt."
fi

# ---------------------------------------------------------------------------
# Partition the device
# ---------------------------------------------------------------------------
info "Writing GPT partition table to $DEVICE ..."

# Boot partition end in MiB.
BOOT_END_MIB=$(( BOOT_SIZE_MIB ))

# Rootfs-A: starts at BOOT_END_MIB MiB.
ROOTFS_A_START_MIB=$(( BOOT_END_MIB ))
ROOTFS_A_END_MIB=$(( ROOTFS_A_START_MIB + ROOTFS_SIZE_GIB * 1024 ))

# Rootfs-B follows rootfs-A.
ROOTFS_B_START_MIB=$(( ROOTFS_A_END_MIB ))
ROOTFS_B_END_MIB=$(( ROOTFS_B_START_MIB + ROOTFS_SIZE_GIB * 1024 ))

# Data partition fills the rest.
DATA_START_MIB=$(( ROOTFS_B_END_MIB ))
if [[ -n "$DATA_SIZE_ARG" ]]; then
    DATA_END="${DATA_SIZE_ARG}GiB"
else
    DATA_END="100%"
fi

run parted -s "$DEVICE" -- \
    mklabel gpt \
    mkpart primary fat32  1MiB          "${BOOT_END_MIB}MiB" \
    mkpart primary ext4   "${ROOTFS_A_START_MIB}MiB" "${ROOTFS_A_END_MIB}MiB" \
    mkpart primary ext4   "${ROOTFS_B_START_MIB}MiB" "${ROOTFS_B_END_MIB}MiB" \
    mkpart primary ext4   "${DATA_START_MIB}MiB"      "$DATA_END" \
    set 1 boot on

info "Partition table written."

# ---------------------------------------------------------------------------
# Resolve partition device paths
# ---------------------------------------------------------------------------
PART_BOOT=$(part_name "$DEVICE" 1)
PART_ROOTFS_A=$(part_name "$DEVICE" 2)
PART_ROOTFS_B=$(part_name "$DEVICE" 3)
PART_DATA=$(part_name "$DEVICE" 4)

# Give the kernel a moment to re-read the partition table if not dry-run.
if [[ "$DRY_RUN" == "false" ]]; then
    run partprobe "$DEVICE" 2>/dev/null || true
    sleep 1
fi

# ---------------------------------------------------------------------------
# Format partitions
# ---------------------------------------------------------------------------
info "Formatting p1 ($PART_BOOT) as FAT32 with label $BOOT_LABEL ..."
run mkfs.vfat -F 32 -n "$BOOT_LABEL" "$PART_BOOT"

info "Formatting p2 ($PART_ROOTFS_A) as ext4 with label $ROOTFS_A_LABEL ..."
run mkfs.ext4 -q -L "$ROOTFS_A_LABEL" -m 1 "$PART_ROOTFS_A"

info "Formatting p3 ($PART_ROOTFS_B) as ext4 with label $ROOTFS_B_LABEL ..."
run mkfs.ext4 -q -L "$ROOTFS_B_LABEL" -m 1 "$PART_ROOTFS_B"

info "Formatting p4 ($PART_DATA) as ext4 with label $DATA_LABEL ..."
# Use a larger inode ratio for the data partition — AI model blobs are large files.
run mkfs.ext4 -q -L "$DATA_LABEL" -m 1 -T largefile4 "$PART_DATA"

# ---------------------------------------------------------------------------
# Create /data directory structure
# ---------------------------------------------------------------------------
if [[ "$DRY_RUN" == "false" ]]; then
    info "Mounting $PART_DATA to initialise directory structure ..."
    TMPDIR_MOUNT=$(mktemp -d)
    mount "$PART_DATA" "$TMPDIR_MOUNT"

    # Core subdirectories. The controller/first-boot script sets ownership later.
    mkdir -p \
        "$TMPDIR_MOUNT/ollama/models/blobs" \
        "$TMPDIR_MOUNT/ollama/models/manifests" \
        "$TMPDIR_MOUNT/chromadb" \
        "$TMPDIR_MOUNT/training/datasets" \
        "$TMPDIR_MOUNT/training/runs" \
        "$TMPDIR_MOUNT/training/adapters" \
        "$TMPDIR_MOUNT/notebooks/examples" \
        "$TMPDIR_MOUNT/notebooks/workspace" \
        "$TMPDIR_MOUNT/docker/volumes/ollama_models" \
        "$TMPDIR_MOUNT/docker/volumes/chromadb_data" \
        "$TMPDIR_MOUNT/bmt_ai_os/db" \
        "$TMPDIR_MOUNT/bmt_ai_os/rag/ingest-queue" \
        "$TMPDIR_MOUNT/bmt_ai_os/cache" \
        "$TMPDIR_MOUNT/secrets/tls" \
        "$TMPDIR_MOUNT/logs/bmt_ai_os"

    # Secrets directory must be root-only.
    chmod 700 "$TMPDIR_MOUNT/secrets"

    umount "$TMPDIR_MOUNT"
    rmdir  "$TMPDIR_MOUNT"
    info "Directory structure initialised on $PART_DATA."
else
    run mkdir -p /data/ollama/models/blobs
    run mkdir -p /data/ollama/models/manifests
    run mkdir -p /data/chromadb
    run mkdir -p /data/training/datasets
    run mkdir -p /data/training/runs
    run mkdir -p /data/training/adapters
    run mkdir -p /data/notebooks/examples
    run mkdir -p /data/notebooks/workspace
    run mkdir -p /data/docker/volumes/ollama_models
    run mkdir -p /data/docker/volumes/chromadb_data
    run mkdir -p /data/bmt_ai_os/db
    run mkdir -p /data/bmt_ai_os/rag/ingest-queue
    run mkdir -p /data/bmt_ai_os/cache
    run mkdir -p /data/secrets/tls
    run mkdir -p /data/logs/bmt_ai_os
    run chmod 700 /data/secrets
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
info "Done. Partition summary:"
printf '  %-20s  FAT32   label=%-16s  /boot\n'       "$PART_BOOT"     "$BOOT_LABEL"
printf '  %-20s  ext4    label=%-16s  / (slot A)\n'  "$PART_ROOTFS_A" "$ROOTFS_A_LABEL"
printf '  %-20s  ext4    label=%-16s  / (slot B)\n'  "$PART_ROOTFS_B" "$ROOTFS_B_LABEL"
printf '  %-20s  ext4    label=%-16s  /data\n'       "$PART_DATA"     "$DATA_LABEL"

if [[ "$DRY_RUN" == "false" ]]; then
    info "Install the rootfs image to $PART_ROOTFS_A and update U-Boot env:"
    printf '    fw_setenv active_slot a\n'
    printf '    fw_setenv bootcount 0\n'
fi
