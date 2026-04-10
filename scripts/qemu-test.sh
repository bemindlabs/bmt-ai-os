#!/usr/bin/env bash
# scripts/qemu-test.sh — BMT AI OS QEMU boot test
# BMTOS-16: Build bootable ARM64 image pipeline
#
# Boots the ARM64 image in qemu-system-aarch64, waits for a login prompt,
# optionally runs smoke tests against expected service ports, then exits.
#
# Usage:
#   ./scripts/qemu-test.sh [OPTIONS]
#
# Options:
#   --image <path>      Path to the disk image (default: output/images/bmt_ai_os-arm64.img)
#   --timeout <sec>     Seconds to wait for login prompt (default: 60)
#   --interactive       Keep QEMU open after tests (do not auto-quit)
#   --smoke-tests       Run port-level smoke tests after boot
#   --help              Show this help message
#
# Exit codes:
#   0 — boot succeeded (login prompt detected)
#   1 — boot failed or timed out

set -euo pipefail

# ─── Constants ────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DEFAULT_IMAGE="${PROJECT_ROOT}/output/images/bmt_ai_os-arm64.img"
QEMU_BIOS_DIR="/usr/share/qemu-efi-aarch64"   # Debian/Ubuntu path
QEMU_BIOS_BREW="/opt/homebrew/share/qemu"      # macOS Homebrew path
QEMU_MONITOR_SOCK="/tmp/bmt-qemu-monitor-$$.sock"
QEMU_SERIAL_LOG="/tmp/bmt-qemu-serial-$$.log"

# ─── Defaults ─────────────────────────────────────────────────────────────────

IMAGE="${DEFAULT_IMAGE}"
BOOT_TIMEOUT=60
INTERACTIVE=false
RUN_SMOKE_TESTS=false

# ─── Colors ───────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

log_info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
log_ok()      { echo -e "${GREEN}[OK]${RESET}    $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
log_error()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; }
log_section() { echo -e "\n${BOLD}==> $*${RESET}"; }

# ─── Usage ────────────────────────────────────────────────────────────────────

usage() {
    cat <<EOF
${BOLD}BMT AI OS — QEMU Boot Test${RESET}

Usage:
  $(basename "$0") [OPTIONS]

Options:
  --image <path>      Path to disk image (default: output/images/bmt_ai_os-arm64.img)
  --timeout <sec>     Seconds to wait for login prompt (default: 60)
  --interactive       Keep QEMU open after boot/tests (attach to serial console)
  --smoke-tests       Run service port smoke tests after successful boot
  --help              Show this help message

Smoke test ports checked (${BOLD}require --smoke-tests${RESET}):
  11434  Ollama inference API
   8000  ChromaDB vector store
   9090  Next.js dashboard
   8080  OpenAI-compatible proxy
   8888  Jupyter Lab

Exit Codes:
  0  Boot successful (login prompt detected)
  1  Boot failed or timed out

Examples:
  $(basename "$0")
  $(basename "$0") --timeout 120 --smoke-tests
  $(basename "$0") --interactive
  $(basename "$0") --image /path/to/custom.img --timeout 90
EOF
}

# ─── Argument Parsing ─────────────────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
    case "$1" in
        --image)
            IMAGE="${2:?--image requires a path argument}"
            shift 2
            ;;
        --timeout)
            BOOT_TIMEOUT="${2:?--timeout requires a number}"
            shift 2
            ;;
        --interactive)
            INTERACTIVE=true
            shift
            ;;
        --smoke-tests)
            RUN_SMOKE_TESTS=true
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
    log_section "Checking QEMU dependencies"

    if ! command -v qemu-system-aarch64 &>/dev/null; then
        log_error "qemu-system-aarch64 not found"
        log_error "  Debian/Ubuntu: sudo apt-get install qemu-system-arm"
        log_error "  macOS:         brew install qemu"
        exit 1
    fi

    local qemu_ver
    qemu_ver="$(qemu-system-aarch64 --version | head -1)"
    log_ok "Found: ${qemu_ver}"
}

# ─── Locate BIOS/EFI Firmware ─────────────────────────────────────────────────

find_bios() {
    # UEFI firmware for aarch64 (OVMF / edk2)
    local candidates=(
        "${QEMU_BIOS_DIR}/QEMU_EFI.fd"
        "${QEMU_BIOS_BREW}/edk2-aarch64-code.fd"
        "/usr/share/AAVMF/AAVMF_CODE.fd"
        "/usr/share/edk2/aarch64/QEMU_EFI.fd"
        "/opt/homebrew/opt/qemu/share/qemu/edk2-aarch64-code.fd"
    )

    for f in "${candidates[@]}"; do
        if [[ -f "$f" ]]; then
            echo "$f"
            return 0
        fi
    done

    # Return empty string — caller will fall back to -bios none
    echo ""
}

# ─── Cleanup Handler ──────────────────────────────────────────────────────────

QEMU_PID=""

cleanup() {
    if [[ -n "${QEMU_PID}" ]] && kill -0 "${QEMU_PID}" 2>/dev/null; then
        log_info "Terminating QEMU (PID ${QEMU_PID})..."
        kill "${QEMU_PID}" 2>/dev/null || true
        wait "${QEMU_PID}" 2>/dev/null || true
    fi
    rm -f "${QEMU_MONITOR_SOCK}" "${QEMU_SERIAL_LOG}"
}

trap cleanup EXIT INT TERM

# ─── Boot QEMU ────────────────────────────────────────────────────────────────

boot_qemu() {
    log_section "Booting ARM64 image in QEMU"

    if [[ ! -f "${IMAGE}" ]]; then
        log_error "Image not found: ${IMAGE}"
        log_error "Run './scripts/build.sh --target qemu' first"
        exit 1
    fi

    log_info "Image: ${IMAGE} ($(du -sh "${IMAGE}" | cut -f1))"
    log_info "Boot timeout: ${BOOT_TIMEOUT}s"

    local bios
    bios="$(find_bios)"

    local bios_args=()
    if [[ -n "${bios}" ]]; then
        log_info "Using UEFI firmware: ${bios}"
        bios_args=(-bios "${bios}")
    else
        log_warn "No UEFI firmware found — booting without BIOS (may fail on some images)"
    fi

    # Build QEMU command
    local qemu_cmd=(
        qemu-system-aarch64
        -machine virt
        -cpu cortex-a57
        -m 2G
        -smp 2
        "${bios_args[@]+"${bios_args[@]}"}"
        -drive "file=${IMAGE},format=raw,if=virtio"
        -netdev user,id=net0,hostfwd=tcp::2222-:22,hostfwd=tcp::11434-:11434,hostfwd=tcp::8000-:8000,hostfwd=tcp::9090-:9090,hostfwd=tcp::8080-:8080,hostfwd=tcp::8888-:8888
        -device virtio-net-device,netdev=net0
        -serial "file:${QEMU_SERIAL_LOG}"
        -monitor "unix:${QEMU_MONITOR_SOCK},server,nowait"
        -no-reboot
    )

    if [[ "${INTERACTIVE}" == "true" ]]; then
        # Replace serial file logging with stdio for interactive sessions
        qemu_cmd=("${qemu_cmd[@]/-serial "file:${QEMU_SERIAL_LOG}"/-serial stdio}")
        log_info "Interactive mode — QEMU attached to stdio"
        exec "${qemu_cmd[@]}"
        # exec replaces the shell, cleanup trap still fires via EXIT
    else
        qemu_cmd+=(-display none)
        log_info "Non-interactive mode — serial output logged to ${QEMU_SERIAL_LOG}"
    fi

    # Launch QEMU in background and capture PID
    "${qemu_cmd[@]}" &
    QEMU_PID=$!
    log_info "QEMU started (PID ${QEMU_PID})"
}

# ─── Wait for Login Prompt ────────────────────────────────────────────────────

wait_for_login() {
    log_section "Waiting for login prompt (timeout: ${BOOT_TIMEOUT}s)"

    local elapsed=0
    local check_interval=2
    local boot_success=false

    # Patterns that indicate a successful boot
    local success_patterns=(
        "login:"
        "Welcome to"
        "BMT AI OS"
        "buildroot login"
    )

    # Patterns that indicate a clear failure
    local failure_patterns=(
        "Kernel panic"
        "end Kernel panic"
        "No working init found"
        "Failed to execute"
    )

    while [[ ${elapsed} -lt ${BOOT_TIMEOUT} ]]; do
        # Check if QEMU process is still alive
        if ! kill -0 "${QEMU_PID}" 2>/dev/null; then
            log_error "QEMU process exited unexpectedly (PID ${QEMU_PID})"
            if [[ -f "${QEMU_SERIAL_LOG}" ]]; then
                log_error "Last 20 lines of serial output:"
                tail -20 "${QEMU_SERIAL_LOG}" | sed 's/^/  /' >&2
            fi
            return 1
        fi

        # Check serial log for success or failure patterns
        if [[ -f "${QEMU_SERIAL_LOG}" ]]; then
            for pattern in "${success_patterns[@]}"; do
                if grep -qF "${pattern}" "${QEMU_SERIAL_LOG}" 2>/dev/null; then
                    log_ok "Login prompt detected: '${pattern}' (${elapsed}s)"
                    boot_success=true
                    break 2
                fi
            done

            for pattern in "${failure_patterns[@]}"; do
                if grep -qF "${pattern}" "${QEMU_SERIAL_LOG}" 2>/dev/null; then
                    log_error "Boot failure detected: '${pattern}'"
                    log_error "Serial log tail:"
                    tail -30 "${QEMU_SERIAL_LOG}" | sed 's/^/  /' >&2
                    return 1
                fi
            done
        fi

        sleep "${check_interval}"
        elapsed=$(( elapsed + check_interval ))
        printf "\r${CYAN}[INFO]${RESET}  Elapsed: %3ds / %ds" "${elapsed}" "${BOOT_TIMEOUT}"
    done

    echo ""

    if [[ "${boot_success}" == "false" ]]; then
        log_error "Timed out after ${BOOT_TIMEOUT}s waiting for login prompt"
        if [[ -f "${QEMU_SERIAL_LOG}" ]]; then
            log_error "Last 30 lines of serial output:"
            tail -30 "${QEMU_SERIAL_LOG}" | sed 's/^/  /' >&2
        fi
        return 1
    fi

    return 0
}

# ─── Smoke Tests ──────────────────────────────────────────────────────────────

# Port smoke tests: after QEMU starts with port forwarding, check that
# the guest services are reachable on localhost forwarded ports.
# These tests indicate the service PORTS are listening; the services
# themselves only start after the AI stack is launched by the controller.
run_smoke_tests() {
    log_section "Running service port smoke tests"

    local -A services=(
        [11434]="Ollama"
        [8000]="ChromaDB"
        [9090]="Dashboard"
        [8080]="OpenAI-compat proxy"
        [8888]="Jupyter Lab"
    )

    local pass=0
    local fail=0

    # Give services a moment to start after login prompt
    log_info "Waiting 10s for services to initialize..."
    sleep 10

    for port in "${!services[@]}"; do
        local name="${services[$port]}"
        # Use nc (netcat) or bash TCP test
        if command -v nc &>/dev/null; then
            if nc -z -w3 127.0.0.1 "${port}" 2>/dev/null; then
                log_ok "  [PASS] Port ${port} (${name}) is reachable"
                (( pass++ ))
            else
                log_warn "  [FAIL] Port ${port} (${name}) not reachable"
                (( fail++ ))
            fi
        else
            # Bash built-in TCP check (no nc required)
            if (echo >/dev/tcp/127.0.0.1/"${port}") 2>/dev/null; then
                log_ok "  [PASS] Port ${port} (${name}) is reachable"
                (( pass++ ))
            else
                log_warn "  [FAIL] Port ${port} (${name}) not reachable"
                (( fail++ ))
            fi
        fi
    done

    echo ""
    log_info "Smoke test results: ${pass} passed, ${fail} failed"

    # Smoke test failures are warnings, not hard errors — the image booted
    if [[ ${fail} -gt 0 ]]; then
        log_warn "Some services are not yet listening. This is expected if the AI stack"
        log_warn "requires manual model download on first boot."
    fi

    return 0
}

# ─── Send QEMU Monitor Quit ────────────────────────────────────────────────────

quit_qemu() {
    if [[ -S "${QEMU_MONITOR_SOCK}" ]]; then
        log_info "Sending quit command to QEMU monitor..."
        echo "quit" | socat - "UNIX-CONNECT:${QEMU_MONITOR_SOCK}" 2>/dev/null || true
        sleep 1
    fi
    if kill -0 "${QEMU_PID}" 2>/dev/null; then
        kill "${QEMU_PID}" 2>/dev/null || true
    fi
}

# ─── Main ─────────────────────────────────────────────────────────────────────

main() {
    echo -e "${BOLD}BMT AI OS — QEMU Boot Test${RESET}"
    echo ""

    check_deps
    boot_qemu

    # In interactive mode, exec replaces the shell — we never reach here
    local boot_result=0
    wait_for_login || boot_result=$?

    if [[ ${boot_result} -ne 0 ]]; then
        log_error "Boot test FAILED"
        exit 1
    fi

    if [[ "${RUN_SMOKE_TESTS}" == "true" ]]; then
        run_smoke_tests
    fi

    if [[ "${INTERACTIVE}" == "false" ]]; then
        quit_qemu
    fi

    echo ""
    log_ok "Boot test PASSED"
    echo ""
    exit 0
}

main "$@"
