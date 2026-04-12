#!/usr/bin/env bash
# scripts/build.sh — BMT AI OS ARM64 image build pipeline
# BMTOS-16: Build bootable ARM64 image pipeline
#
# Usage:
#   ./scripts/build.sh [OPTIONS]
#
# Options:
#   --target <target>   Build target: qemu|jetson|rk3588|pi5|apple-silicon (default: qemu)
#   --clean             Remove Buildroot build directory before building
#   --menuconfig        Open Buildroot menuconfig instead of building
#   --help              Show this help message

set -euo pipefail

# ─── Constants ────────────────────────────────────────────────────────────────

BUILDROOT_VERSION="${BUILDROOT_VERSION:-2024.02.9}"
BUILDROOT_URL="https://buildroot.org/downloads/buildroot-${BUILDROOT_VERSION}.tar.gz"
BUILDROOT_SHA256_URL="https://buildroot.org/downloads/buildroot-${BUILDROOT_VERSION}.tar.gz.sha256"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

BUILDROOT_DIR="${PROJECT_ROOT}/buildroot-${BUILDROOT_VERSION}"
BUILDROOT_ARCHIVE="${PROJECT_ROOT}/buildroot-${BUILDROOT_VERSION}.tar.gz"

DEFCONFIG_SRC="${PROJECT_ROOT}/bmt_ai_os/kernel/defconfig"
KERNEL_CONFIG_FRAGMENT="${PROJECT_ROOT}/bmt_ai_os/kernel/linux.config"
EXTERNAL_TREE="${PROJECT_ROOT}/bmt_ai_os-build/buildroot-external"

OUTPUT_DIR="${PROJECT_ROOT}/output"
OUTPUT_IMAGES_DIR="${OUTPUT_DIR}/images"
OUTPUT_IMAGE="${OUTPUT_IMAGES_DIR}/bmt_ai_os-arm64.img"
BR2_OUTPUT_DIR="${OUTPUT_DIR}/buildroot"

# ─── Defaults ─────────────────────────────────────────────────────────────────

TARGET="${TARGET:-qemu}"
DO_CLEAN=false
DO_MENUCONFIG=false
PROFILE_PATH=""

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
${BOLD}BMT AI OS — ARM64 Image Build Pipeline${RESET}

Usage:
  $(basename "$0") [OPTIONS]

Options:
  --target <target>   Build target (default: qemu)
                        qemu           QEMU virt board (for testing)
                        jetson         NVIDIA Jetson Orin Nano Super
                        rk3588         Rockchip RK3588 boards
                        pi5            Raspberry Pi 5 + Hailo AI HAT+
                        apple-silicon  Apple Silicon via Asahi Linux (CPU-only)
  --clean             Remove Buildroot output directory before building
  --menuconfig        Open Buildroot menuconfig (do not build)
  --profile <path>    DLC build profile manifest JSON (overrides --target with profile target)
  --help              Show this help message

Environment Variables:
  TARGET              Same as --target
  BUILDROOT_VERSION   Buildroot version to use (default: ${BUILDROOT_VERSION})

Output:
  ${OUTPUT_IMAGE}

Examples:
  $(basename "$0") --target qemu
  $(basename "$0") --target jetson --clean
  $(basename "$0") --menuconfig
EOF
}

# ─── Argument Parsing ─────────────────────────────────────────────────────────

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)
            TARGET="${2:?--target requires an argument}"
            shift 2
            ;;
        --clean)
            DO_CLEAN=true
            shift
            ;;
        --menuconfig)
            DO_MENUCONFIG=true
            shift
            ;;
        --profile)
            PROFILE_PATH="${2:?--profile requires a path argument}"
            shift 2
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

# Validate target
case "${TARGET}" in
    qemu|jetson|rk3588|pi5|apple-silicon) ;;
    *)
        log_error "Invalid target '${TARGET}'. Must be one of: qemu, jetson, rk3588, pi5, apple-silicon"
        exit 1
        ;;
esac

# ─── Dependency Check ─────────────────────────────────────────────────────────

check_deps() {
    log_section "Checking build dependencies"
    local missing=()
    local deps=(make gcc g++ wget tar file bc cpio unzip rsync)

    for dep in "${deps[@]}"; do
        if ! command -v "${dep}" &>/dev/null; then
            missing+=("${dep}")
        fi
    done

    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error "Missing required tools: ${missing[*]}"
        log_error "On Debian/Ubuntu: sudo apt-get install build-essential wget cpio unzip rsync bc"
        log_error "On macOS (cross-compile not supported natively — use Docker or Linux host)"
        exit 1
    fi

    log_ok "All required tools present"
}

# ─── Download Buildroot ────────────────────────────────────────────────────────

download_buildroot() {
    log_section "Buildroot ${BUILDROOT_VERSION}"

    if [[ -d "${BUILDROOT_DIR}" ]]; then
        log_ok "Buildroot source already present at ${BUILDROOT_DIR}"
        return 0
    fi

    if [[ ! -f "${BUILDROOT_ARCHIVE}" ]]; then
        log_info "Downloading Buildroot ${BUILDROOT_VERSION}..."
        wget --progress=bar:force:noscroll -O "${BUILDROOT_ARCHIVE}" "${BUILDROOT_URL}"
    else
        log_info "Archive already downloaded: ${BUILDROOT_ARCHIVE}"
    fi

    # Verify checksum if sha256 file is available
    local sha256_file="${BUILDROOT_ARCHIVE}.sha256"
    if [[ ! -f "${sha256_file}" ]]; then
        log_info "Downloading checksum file..."
        wget -q -O "${sha256_file}" "${BUILDROOT_SHA256_URL}" || log_warn "Could not download checksum file — skipping verification"
    fi

    if [[ -f "${sha256_file}" ]]; then
        log_info "Verifying checksum..."
        if command -v sha256sum &>/dev/null; then
            if (cd "$(dirname "${BUILDROOT_ARCHIVE}")" && sha256sum --check --status "${sha256_file##*/}" 2>/dev/null); then
                log_ok "Checksum verified"
            else
                log_warn "Checksum verification failed or file format mismatch — proceeding"
            fi
        fi
    fi

    log_info "Extracting Buildroot..."
    tar -xzf "${BUILDROOT_ARCHIVE}" -C "${PROJECT_ROOT}"
    log_ok "Buildroot extracted to ${BUILDROOT_DIR}"
}

# ─── Target-specific Config Fragment ──────────────────────────────────────────

# Returns the path to a target-specific config fragment (may not exist)
target_config_fragment() {
    echo "${PROJECT_ROOT}/bmt_ai_os/kernel/targets/${TARGET}.config"
}

# Writes target-specific Buildroot config overrides to a temp fragment
generate_target_br2_fragment() {
    local frag_file="$1"
    case "${TARGET}" in
        qemu)
            cat >"${frag_file}" <<'FRAG'
# QEMU virt board — ARM64
BR2_arm_cortex_a57=y
BR2_TARGET_GENERIC_GETTY_PORT="ttyAMA0"
BR2_LINUX_KERNEL=y
BR2_LINUX_KERNEL_DEFCONFIG="virt"
BR2_TARGET_ROOTFS_EXT2=y
BR2_TARGET_ROOTFS_EXT2_4=y
BR2_TARGET_ROOTFS_EXT2_SIZE="512M"
FRAG
            ;;
        jetson)
            cat >"${frag_file}" <<'FRAG'
# NVIDIA Jetson Orin Nano Super
BR2_aarch64=y
BR2_TARGET_GENERIC_GETTY_PORT="ttyTCU0"
BR2_LINUX_KERNEL=y
BR2_LINUX_KERNEL_CUSTOM_VERSION=y
BR2_LINUX_KERNEL_CUSTOM_VERSION_VALUE="5.15"
BR2_TARGET_ROOTFS_EXT2=y
BR2_TARGET_ROOTFS_EXT2_4=y
BR2_TARGET_ROOTFS_EXT2_SIZE="4096M"
# Enable CUDA/TensorRT stubs (BSP must supply actual blobs)
# BR2_PACKAGE_CUDA=y
# BR2_PACKAGE_TENSORRT_LLM=y
FRAG
            ;;
        rk3588)
            cat >"${frag_file}" <<'FRAG'
# Rockchip RK3588
BR2_aarch64=y
BR2_TARGET_GENERIC_GETTY_PORT="ttyS2"
BR2_LINUX_KERNEL=y
BR2_LINUX_KERNEL_CUSTOM_VERSION=y
BR2_LINUX_KERNEL_CUSTOM_VERSION_VALUE="6.1"
BR2_TARGET_ROOTFS_EXT2=y
BR2_TARGET_ROOTFS_EXT2_4=y
BR2_TARGET_ROOTFS_EXT2_SIZE="4096M"
# Enable RKNN runtime stubs (BSP must supply actual blobs)
# BR2_PACKAGE_RKNN_RUNTIME=y
# BR2_PACKAGE_RKLLM=y
FRAG
            ;;
        pi5)
            cat >"${frag_file}" <<FRAG
# Raspberry Pi 5 + Hailo AI HAT+ 2
BR2_aarch64=y
BR2_TARGET_GENERIC_GETTY_PORT="ttyAMA10"
BR2_LINUX_KERNEL=y
BR2_LINUX_KERNEL_CUSTOM_VERSION=y
BR2_LINUX_KERNEL_CUSTOM_VERSION_VALUE="6.6"
BR2_TARGET_ROOTFS_EXT2=y
BR2_TARGET_ROOTFS_EXT2_4=y
BR2_TARGET_ROOTFS_EXT2_SIZE="4096M"

# Genimage for partitioned SD card image
BR2_ROOTFS_POST_IMAGE_SCRIPT="${EXTERNAL_TREE}/board/pi5/post-image.sh"
BR2_PACKAGE_HOST_GENIMAGE=y
BR2_PACKAGE_HOST_DOSFSTOOLS=y
BR2_PACKAGE_HOST_MTOOLS=y

# Pi 5 kernel config fragment
BR2_LINUX_KERNEL_CONFIG_FRAGMENT_FILES="${PROJECT_ROOT}/bmt_ai_os/kernel/pi5-hailo.config"

# Pi 5 + Hailo BSP package
BR2_PACKAGE_PI5_HAILO_BSP=y
BR2_PACKAGE_PI5_HAILO_BSP_HAILORT_VERSION="4.20.0"
BR2_PACKAGE_PI5_HAILO_BSP_INSTALL_DKMS=y
BR2_PACKAGE_PI5_HAILO_BSP_INSTALL_PYTHON_BINDINGS=y
BR2_PACKAGE_PI5_HAILO_BSP_POWER_MODE="performance"
# Image size optimization: strip binaries, remove static libs
BR2_STRIP_strip=y
BR2_ENABLE_LOCALE_PURGE=y
BR2_ENABLE_LOCALE_WHITELIST="C en_US"
BR2_PACKAGE_HOST_ZSTD=y

# Enable HailoRT stubs (BSP must supply actual blobs)
# BR2_PACKAGE_HAILO_RUNTIME=y
FRAG
            ;;
        apple-silicon)
            cat >"${frag_file}" <<'FRAG'
# Apple Silicon via Asahi Linux (CPU-only, no Metal/GPU on Linux)
BR2_aarch64=y
BR2_TARGET_GENERIC_GETTY_PORT="tty1"
BR2_LINUX_KERNEL=y
BR2_LINUX_KERNEL_CUSTOM_VERSION=y
BR2_LINUX_KERNEL_CUSTOM_VERSION_VALUE="6.9"
BR2_TARGET_ROOTFS_EXT2=y
BR2_TARGET_ROOTFS_EXT2_4=y
BR2_TARGET_ROOTFS_EXT2_SIZE="4096M"
FRAG
            ;;
    esac
}

# ─── DLC Profile Handling ────────────────────────────────────────────────────

apply_dlc_profile() {
    local profile_json="$1"
    local br2_defconfig="$2"

    if [[ ! -f "${profile_json}" ]]; then
        log_error "Profile manifest not found: ${profile_json}"
        exit 1
    fi

    log_section "Applying DLC build profile"
    log_info "Profile: ${profile_json}"

    # Requires jq for JSON parsing
    if ! command -v jq &>/dev/null; then
        log_error "jq is required for --profile support. Install: apt-get install jq"
        exit 1
    fi

    # Extract target from profile (overrides --target)
    local profile_target
    profile_target="$(jq -r '.target // empty' "${profile_json}")"
    if [[ -n "${profile_target}" ]]; then
        TARGET="${profile_target}"
        log_info "Target overridden by profile: ${TARGET}"
    fi

    # Extract profile metadata
    local profile_name profile_tier est_size
    profile_name="$(jq -r '.profile_name // "custom"' "${profile_json}")"
    profile_tier="$(jq -r '.tier // "standard"' "${profile_json}")"
    est_size="$(jq -r '.estimated_size_mb // 0' "${profile_json}")"
    log_info "Profile: ${profile_name} | Tier: ${profile_tier} | Est. size: ${est_size}MB"

    # Extract and append Buildroot packages
    local br2_packages
    br2_packages="$(jq -r '.buildroot_packages[]? // empty' "${profile_json}")"
    if [[ -n "${br2_packages}" ]]; then
        log_info "Adding Buildroot packages from profile:"
        local frag_file
        frag_file="$(mktemp /tmp/bmt-dlc-XXXXXX.config)"
        echo "# DLC profile packages — ${profile_name}" > "${frag_file}"
        while IFS= read -r pkg; do
            local pkg_upper
            pkg_upper="$(echo "${pkg}" | tr '[:lower:]-' '[:upper:]_')"
            echo "BR2_PACKAGE_${pkg_upper}=y" >> "${frag_file}"
            log_info "  + ${pkg}"
        done <<< "${br2_packages}"
        cat "${frag_file}" >> "${br2_defconfig}"
        rm -f "${frag_file}"
        log_ok "Buildroot packages appended"
    fi

    # Extract container images to pre-pull list
    local container_images
    container_images="$(jq -r '.container_images[]? // empty' "${profile_json}")"
    if [[ -n "${container_images}" ]]; then
        local pull_list="${OUTPUT_DIR}/container-pull-list.txt"
        mkdir -p "${OUTPUT_DIR}"
        echo "${container_images}" > "${pull_list}"
        log_info "Container images to pre-pull saved to: ${pull_list}"
    fi

    # Extract install commands to first-boot script
    local install_commands
    install_commands="$(jq -r '.install_commands[]? // empty' "${profile_json}")"
    if [[ -n "${install_commands}" ]]; then
        local firstboot_dir="${PROJECT_ROOT}/bmt_ai_os/runtime/init.d"
        local firstboot_script="${firstboot_dir}/S90firstboot"
        mkdir -p "${firstboot_dir}"

        cat > "${firstboot_script}" <<'HEADER'
#!/bin/sh
# Auto-generated by build.sh --profile: DLC first-boot tool installation
# This script runs once on first boot to install selected DLC packages.

MARKER="/data/.dlc-installed"
if [ -f "$MARKER" ]; then
    exit 0
fi

echo "[DLC] Installing selected tool packages..."
HEADER
        while IFS= read -r cmd; do
            echo "${cmd}" >> "${firstboot_script}"
        done <<< "${install_commands}"

        cat >> "${firstboot_script}" <<'FOOTER'

touch "$MARKER"
echo "[DLC] Tool installation complete."
FOOTER
        chmod +x "${firstboot_script}"
        log_ok "First-boot install script generated: ${firstboot_script}"
    fi

    # Extract ports for firewall config
    local ports
    ports="$(jq -r '.ports[]? // empty' "${profile_json}")"
    if [[ -n "${ports}" ]]; then
        local fw_file="${OUTPUT_DIR}/dlc-ports.txt"
        echo "${ports}" > "${fw_file}"
        log_info "DLC ports saved to: ${fw_file}"
    fi
}

# ─── Apply Configuration ───────────────────────────────────────────────────────

apply_config() {
    log_section "Applying BMT AI OS defconfig for target: ${TARGET}"

    mkdir -p "${BR2_OUTPUT_DIR}"

    # Copy BMT defconfig into Buildroot's configs/ directory
    local br2_defconfig="${BUILDROOT_DIR}/configs/bmt_ai_os_defconfig"
    cp "${DEFCONFIG_SRC}" "${br2_defconfig}"
    log_info "Copied defconfig -> ${br2_defconfig}"

    # Generate and append target-specific fragment into defconfig
    local target_frag
    target_frag="$(mktemp /tmp/bmt-target-XXXXXX.config)"
    generate_target_br2_fragment "${target_frag}"
    cat "${target_frag}" >> "${br2_defconfig}"
    rm -f "${target_frag}"
    log_info "Appended target fragment for '${TARGET}'"

    # Apply the defconfig
    make -C "${BUILDROOT_DIR}" \
        O="${BR2_OUTPUT_DIR}" \
        BR2_EXTERNAL="${EXTERNAL_TREE}" \
        bmt_ai_os_defconfig
    log_ok "Buildroot defconfig applied"

    # Apply DLC profile if specified
    if [[ -n "${PROFILE_PATH}" ]]; then
        apply_dlc_profile "${PROFILE_PATH}" "${br2_defconfig}"
    fi

    # Apply kernel config fragment if it exists
    if [[ -f "${KERNEL_CONFIG_FRAGMENT}" ]]; then
        log_info "Applying kernel config fragment: ${KERNEL_CONFIG_FRAGMENT}"
        local br2_kconfig="${BR2_OUTPUT_DIR}/.config"
        if [[ -f "${br2_kconfig}" ]]; then
            # Merge fragment using Buildroot's support/kconfig/merge_config.sh if available
            local merge_script="${BUILDROOT_DIR}/support/kconfig/merge_config.sh"
            if [[ -f "${merge_script}" ]]; then
                "${merge_script}" -m "${br2_kconfig}" "${KERNEL_CONFIG_FRAGMENT}"
                log_ok "Kernel config fragment merged"
            else
                cat "${KERNEL_CONFIG_FRAGMENT}" >> "${br2_kconfig}"
                log_warn "merge_config.sh not found — appended fragment directly (duplicates may exist)"
            fi
        fi
    fi

    # Apply per-target kernel config fragment if present
    local tgt_kfrag
    tgt_kfrag="$(target_config_fragment)"
    if [[ -f "${tgt_kfrag}" ]]; then
        log_info "Applying target kernel config fragment: ${tgt_kfrag}"
        cat "${tgt_kfrag}" >> "${BR2_OUTPUT_DIR}/.config"
        log_ok "Target kernel config fragment applied"
    fi
}

# ─── Clean ────────────────────────────────────────────────────────────────────

do_clean() {
    log_section "Cleaning build output"
    if [[ -d "${BR2_OUTPUT_DIR}" ]]; then
        rm -rf "${BR2_OUTPUT_DIR}"
        log_ok "Removed ${BR2_OUTPUT_DIR}"
    else
        log_info "Nothing to clean"
    fi
}

# ─── Menuconfig ───────────────────────────────────────────────────────────────

do_menuconfig() {
    log_section "Opening Buildroot menuconfig"
    apply_config
    make -C "${BUILDROOT_DIR}" \
        O="${BR2_OUTPUT_DIR}" \
        BR2_EXTERNAL="${EXTERNAL_TREE}" \
        menuconfig
}

# ─── Build ────────────────────────────────────────────────────────────────────

do_build() {
    local build_start
    build_start="$(date +%s)"

    log_section "Building BMT AI OS ARM64 image (target: ${TARGET})"

    # Determine parallelism
    local nproc=1
    if command -v nproc &>/dev/null; then
        nproc="$(nproc)"
    elif command -v sysctl &>/dev/null; then
        nproc="$(sysctl -n hw.ncpu 2>/dev/null || echo 1)"
    fi
    log_info "Using ${nproc} parallel jobs"

    make -C "${BUILDROOT_DIR}" \
        O="${BR2_OUTPUT_DIR}" \
        BR2_EXTERNAL="${EXTERNAL_TREE}" \
        -j"${nproc}"

    local build_end
    build_end="$(date +%s)"
    local build_seconds=$(( build_end - build_start ))
    local build_time
    build_time="$(printf '%02dh %02dm %02ds' \
        $(( build_seconds / 3600 )) \
        $(( (build_seconds % 3600) / 60 )) \
        $(( build_seconds % 60 )))"

    # Locate and stage the output image
    stage_image "${build_time}"
}

stage_image() {
    local build_time="$1"

    log_section "Staging output image"
    mkdir -p "${OUTPUT_IMAGES_DIR}"

    # Buildroot places images in O/images/
    local br2_images="${BR2_OUTPUT_DIR}/images"
    local source_img=""

    # Prefer target-specific image, then ext4, then sdcard, then any .img
    for candidate in \
        "${br2_images}/bmt-ai-os-pi5.img" \
        "${br2_images}/rootfs.ext4" \
        "${br2_images}/rootfs.ext2" \
        "${br2_images}/sdcard.img" \
        "${br2_images}"/*.img
    do
        if [[ -f "${candidate}" ]]; then
            source_img="${candidate}"
            break
        fi
    done

    if [[ -z "${source_img}" ]]; then
        log_warn "No image file found in ${br2_images} — listing contents:"
        ls -lh "${br2_images}" 2>/dev/null || true
        log_error "Build may have failed or produced an unexpected image format"
        exit 1
    fi

    cp "${source_img}" "${OUTPUT_IMAGE}"
    log_ok "Image staged: ${OUTPUT_IMAGE}"

    # ─── Build Summary ────────────────────────────────────────────────────────

    local img_size
    img_size="$(du -sh "${OUTPUT_IMAGE}" | cut -f1)"

    echo ""
    echo -e "${BOLD}╔══════════════════════════════════════════════╗${RESET}"
    echo -e "${BOLD}║         BMT AI OS — Build Summary            ║${RESET}"
    echo -e "${BOLD}╠══════════════════════════════════════════════╣${RESET}"
    printf  "${BOLD}║${RESET}  %-18s  %-23s ${BOLD}║${RESET}\n" "Target:"      "${TARGET}"
    printf  "${BOLD}║${RESET}  %-18s  %-23s ${BOLD}║${RESET}\n" "Buildroot:"   "${BUILDROOT_VERSION}"
    if [[ -n "${PROFILE_PATH}" ]]; then
    printf  "${BOLD}║${RESET}  %-18s  %-23s ${BOLD}║${RESET}\n" "DLC Profile:" "$(basename "${PROFILE_PATH}")"
    fi
    printf  "${BOLD}║${RESET}  %-18s  %-23s ${BOLD}║${RESET}\n" "Image size:"  "${img_size}"
    printf  "${BOLD}║${RESET}  %-18s  %-23s ${BOLD}║${RESET}\n" "Build time:"  "${build_time}"
    printf  "${BOLD}║${RESET}  %-18s  %-23s ${BOLD}║${RESET}\n" "Output:"      "output/images/"
    echo -e "${BOLD}╚══════════════════════════════════════════════╝${RESET}"
    echo ""
    log_ok "Image ready: ${OUTPUT_IMAGE}"
}

# ─── Main ─────────────────────────────────────────────────────────────────────

main() {
    echo -e "${BOLD}BMT AI OS — ARM64 Image Build Pipeline${RESET}"
    echo -e "Buildroot ${BUILDROOT_VERSION} | Target: ${TARGET}"
    echo ""

    if [[ "${DO_CLEAN}" == "true" ]]; then
        do_clean
    fi

    if [[ "${DO_MENUCONFIG}" == "true" ]]; then
        check_deps
        download_buildroot
        do_menuconfig
        exit 0
    fi

    check_deps
    download_buildroot
    apply_config
    do_build
}

main "$@"
