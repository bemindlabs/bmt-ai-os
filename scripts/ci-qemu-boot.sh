#!/usr/bin/env bash
# scripts/ci-qemu-boot.sh — CI-specific QEMU ARM64 boot wrapper
# BMTOS-18: Set up QEMU testing and CI pipeline
#
# Starts qemu-system-aarch64 in headless mode with port forwarding for
# SSH and all AI stack services. Designed for use in GitHub Actions and
# other CI environments.
#
# Usage:
#   ./scripts/ci-qemu-boot.sh [OPTIONS]
#
# Options:
#   --image <path>       Path to the disk image (default: output/images/bmt-ai-os-arm64.img)
#   --timeout <sec>      Boot timeout in seconds (default: 120)
#   --serial-log <path>  Path for serial console log (default: /tmp/bmt-qemu-ci-serial.log)
#   --background         Daemonize after confirming boot (for CI test steps)
#   --help               Show this help message
#
# Exit codes:
#   0 — QEMU booted and SSH is reachable
#   1 — Boot failed, timed out, or missing dependencies
#   2 — Image not found
#
# Port forwarding (host -> guest):
#   2222  -> 22    (SSH)
#   11434 -> 11434 (Ollama)
#   8000  -> 8000  (ChromaDB)
#   9090  -> 9090  (Dashboard)
#   8080  -> 8080  (OpenAI-compatible proxy)
#   8888  -> 8888  (Jupyter Lab)

set -euo pipefail

# ─── Constants ────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DEFAULT_IMAGE="${PROJECT_ROOT}/output/images/bmt-ai-os-arm64.img"
QEMU_PID_FILE="/tmp/bmt-qemu-ci.pid"

# ─── Defaults ─────────────────────────────────────────────────────────────────

IMAGE="${QEMU_IMAGE:-${DEFAULT_IMAGE}}"
BOOT_TIMEOUT="${BOOT_TIMEOUT:-120}"
SERIAL_LOG="${QEMU_SERIAL_LOG:-/tmp/bmt-qemu-ci-serial.log}"
BACKGROUND=false

# ─── Colors (disabled in non-interactive / CI) ──────────────────────────────

if [[ -t 1 ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    CYAN='\033[0;36m'
    BOLD='\033[1m'
    RESET='\033[0m'
else
    RED='' GREEN='' YELLOW='' CYAN='' BOLD='' RESET=''
fi

log_info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
log_ok()      { echo -e "${GREEN}[OK]${RESET}    $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
log_error()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; }
log_section() { echo -e "\n${BOLD}==> $*${RESET}"; }

# ─── Usage ────────────────────────────────────────────────────────────────────

usage() {
    cat <<EOF
${BOLD}BMT AI OS — CI QEMU Boot Wrapper${RESET}

Usage:
  $(basename "$0") [OPTIONS]

Options:
  --image <path>       Path to disk image (default: output/images/bmt-ai-os-arm64.img)
  --timeout <sec>      Boot timeout in seconds (default: 120)
  --serial-log <path>  Serial console log path (default: /tmp/bmt-qemu-ci-serial.log)
  --background         Run QEMU in background after boot confirmation
  --help               Show this help message

Environment Variables:
  QEMU_IMAGE           Same as --image
  BOOT_TIMEOUT         Same as --timeout
  QEMU_SERIAL_LOG      Same as --serial-log

Exit Codes:
  0  Boot succeeded, SSH reachable
  1  Boot failed or timed out
  2  Image file not found

Port Forwarding (host -> guest):
  2222  -> 22     SSH
  11434 -> 11434  Ollama
  8000  -> 8000   ChromaDB
  9090  -> 9090   Dashboard
  8080  -> 8080   OpenAI-compatible API
  8888  -> 8888   Jupyter Lab
EOF
}

# ─── Argument Parsing ─────────────────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
    case "$1" in
        --image)
            IMAGE="${2:?--image requires a path}"
            shift 2
            ;;
        --timeout)
            BOOT_TIMEOUT="${2:?--timeout requires a number}"
            shift 2
            ;;
        --serial-log)
            SERIAL_LOG="${2:?--serial-log requires a path}"
            shift 2
            ;;
        --background)
            BACKGROUND=true
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

# ─── Dependency Check ─────────────────────────────────────────────────────────

check_deps() {
    log_section "Checking dependencies"

    if ! command -v qemu-system-aarch64 &>/dev/null; then
        log_error "qemu-system-aarch64 not found"
        log_error "Install with: sudo apt-get install qemu-system-arm qemu-efi-aarch64"
        exit 1
    fi

    local qemu_ver
    qemu_ver="$(qemu-system-aarch64 --version | head -1)"
    log_ok "QEMU: ${qemu_ver}"
}

# ─── Locate EFI Firmware ─────────────────────────────────────────────────────

find_efi_firmware() {
    local candidates=(
        "/usr/share/qemu-efi-aarch64/QEMU_EFI.fd"
        "/usr/share/AAVMF/AAVMF_CODE.fd"
        "/usr/share/edk2/aarch64/QEMU_EFI.fd"
        "/opt/homebrew/share/qemu/edk2-aarch64-code.fd"
        "/opt/homebrew/opt/qemu/share/qemu/edk2-aarch64-code.fd"
    )

    for f in "${candidates[@]}"; do
        if [[ -f "$f" ]]; then
            echo "$f"
            return 0
        fi
    done
    echo ""
}

# ─── Cleanup ──────────────────────────────────────────────────────────────────

QEMU_PID=""

cleanup() {
    if [[ -n "${QEMU_PID}" ]] && kill -0 "${QEMU_PID}" 2>/dev/null; then
        log_info "Terminating QEMU (PID ${QEMU_PID})..."
        kill "${QEMU_PID}" 2>/dev/null || true
        wait "${QEMU_PID}" 2>/dev/null || true
    fi
    rm -f "${QEMU_PID_FILE}"
}

# Only trap for cleanup when NOT in background mode. In background mode,
# cleanup is deferred to the caller (CI step or test teardown).
if [[ "${BACKGROUND}" == "false" ]]; then
    trap cleanup EXIT INT TERM
fi

# ─── Start QEMU ──────────────────────────────────────────────────────────────

start_qemu() {
    log_section "Starting QEMU ARM64 (headless)"

    if [[ ! -f "${IMAGE}" ]]; then
        log_error "Image not found: ${IMAGE}"
        log_error "Run './scripts/build.sh --target qemu' first"
        exit 2
    fi

    log_info "Image:   ${IMAGE} ($(du -sh "${IMAGE}" | cut -f1))"
    log_info "Timeout: ${BOOT_TIMEOUT}s"
    log_info "Serial:  ${SERIAL_LOG}"

    local bios
    bios="$(find_efi_firmware)"

    local bios_args=()
    if [[ -n "${bios}" ]]; then
        log_info "EFI firmware: ${bios}"
        bios_args=(-bios "${bios}")
    else
        log_warn "No EFI firmware found — booting without BIOS"
    fi

    # Build the QEMU command for headless CI use
    local qemu_cmd=(
        qemu-system-aarch64
        -machine virt
        -cpu cortex-a57
        -m 2G
        -smp 2
        "${bios_args[@]+"${bios_args[@]}"}"
        -drive "file=${IMAGE},format=raw,if=virtio"
        # Port forwarding: host ports -> guest ports
        -netdev "user,id=net0,hostfwd=tcp::2222-:22,hostfwd=tcp::11434-:11434,hostfwd=tcp::8000-:8000,hostfwd=tcp::9090-:9090,hostfwd=tcp::8080-:8080,hostfwd=tcp::8888-:8888"
        -device virtio-net-device,netdev=net0
        -serial "file:${SERIAL_LOG}"
        -display none
        -no-reboot
        -daemonize
    )

    # Launch QEMU as a daemon
    "${qemu_cmd[@]}"

    # Find the QEMU PID (most recent qemu-system-aarch64 process)
    sleep 1
    QEMU_PID="$(pgrep -f "qemu-system-aarch64.*${IMAGE}" | tail -1 || true)"

    if [[ -z "${QEMU_PID}" ]]; then
        log_error "Failed to find QEMU process after launch"
        if [[ -f "${SERIAL_LOG}" ]]; then
            log_error "Serial log contents:"
            cat "${SERIAL_LOG}" >&2
        fi
        exit 1
    fi

    # Save PID for later cleanup by CI
    echo "${QEMU_PID}" > "${QEMU_PID_FILE}"
    log_ok "QEMU started (PID ${QEMU_PID})"
}

# ─── Wait for Boot ────────────────────────────────────────────────────────────

wait_for_boot() {
    log_section "Waiting for boot (timeout: ${BOOT_TIMEOUT}s)"

    local elapsed=0
    local interval=3
    local ssh_port=2222

    while [[ ${elapsed} -lt ${BOOT_TIMEOUT} ]]; do
        # Check if QEMU is still running
        if [[ -n "${QEMU_PID}" ]] && ! kill -0 "${QEMU_PID}" 2>/dev/null; then
            log_error "QEMU process exited unexpectedly"
            if [[ -f "${SERIAL_LOG}" ]]; then
                log_error "Last 30 lines of serial log:"
                tail -30 "${SERIAL_LOG}" | sed 's/^/  /' >&2
            fi
            return 1
        fi

        # Check for kernel panic in serial log
        if [[ -f "${SERIAL_LOG}" ]] && grep -qF "Kernel panic" "${SERIAL_LOG}" 2>/dev/null; then
            log_error "Kernel panic detected"
            tail -30 "${SERIAL_LOG}" | sed 's/^/  /' >&2
            return 1
        fi

        # Try SSH connection (indicates full boot)
        if nc -z 127.0.0.1 "${ssh_port}" 2>/dev/null; then
            log_ok "SSH port ${ssh_port} is reachable (boot took ~${elapsed}s)"
            return 0
        fi

        # Fall back to checking serial log for login prompt
        if [[ -f "${SERIAL_LOG}" ]]; then
            if grep -qE "(login:|Welcome to|BMT AI OS)" "${SERIAL_LOG}" 2>/dev/null; then
                log_ok "Login prompt detected in serial log (~${elapsed}s)"
                return 0
            fi
        fi

        sleep "${interval}"
        elapsed=$(( elapsed + interval ))
        # Progress indicator for CI logs
        echo "  ... ${elapsed}s / ${BOOT_TIMEOUT}s"
    done

    log_error "Boot timed out after ${BOOT_TIMEOUT}s"
    if [[ -f "${SERIAL_LOG}" ]]; then
        log_error "Last 50 lines of serial log:"
        tail -50 "${SERIAL_LOG}" | sed 's/^/  /' >&2
    fi
    return 1
}

# ─── Main ─────────────────────────────────────────────────────────────────────

main() {
    echo -e "${BOLD}BMT AI OS — CI QEMU Boot${RESET}"
    echo ""

    check_deps
    start_qemu

    local boot_result=0
    wait_for_boot || boot_result=$?

    if [[ ${boot_result} -ne 0 ]]; then
        log_error "Boot FAILED"
        exit 1
    fi

    if [[ "${BACKGROUND}" == "true" ]]; then
        log_ok "QEMU running in background (PID ${QEMU_PID})"
        log_info "PID file: ${QEMU_PID_FILE}"
        log_info "Serial log: ${SERIAL_LOG}"
        log_info "To stop: kill \$(cat ${QEMU_PID_FILE})"
        # Disable the EXIT trap so QEMU keeps running
        trap - EXIT INT TERM
    else
        log_info "Stopping QEMU..."
    fi

    echo ""
    log_ok "Boot test PASSED"
    exit 0
}

main "$@"
