#!/bin/bash
# BMT AI OS — Network Initialization Script
# Creates the Docker bridge network for the AI stack and configures DNS.
# SPDX-License-Identifier: MIT

set -eu

# ---------------------------------------------------------------------------
# Configuration (override via environment)
# ---------------------------------------------------------------------------
BMT_NETWORK_NAME="${BMT_NETWORK_NAME:-bmt-ai-net}"
BMT_SUBNET="${BMT_SUBNET:-172.30.0.0/16}"
BMT_GATEWAY="${BMT_GATEWAY:-172.30.0.1}"
BMT_DNS_CONFIG="${BMT_DNS_CONFIG:-/etc/bmt_ai_os/dns-config.json}"
BMT_EXTERNAL_DNS="${BMT_EXTERNAL_DNS:-1.1.1.1,8.8.8.8}"
BMT_ENABLE_IPV6="${BMT_ENABLE_IPV6:-false}"

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
log_info()  { echo "[bmt-net]  INFO: $*"; }
log_warn()  { echo "[bmt-net]  WARN: $*" >&2; }
log_error() { echo "[bmt-net] ERROR: $*" >&2; }

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------
check_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        log_error "docker CLI not found in PATH"
        exit 1
    fi
    if ! docker info >/dev/null 2>&1; then
        log_error "Docker daemon is not running"
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Cleanup stale networks
# ---------------------------------------------------------------------------
cleanup_stale_networks() {
    log_info "Pruning unused Docker networks..."
    docker network prune -f >/dev/null 2>&1 || true
}

# ---------------------------------------------------------------------------
# Create or verify the bridge network
# ---------------------------------------------------------------------------
ensure_network() {
    if docker network inspect "${BMT_NETWORK_NAME}" >/dev/null 2>&1; then
        log_info "Network '${BMT_NETWORK_NAME}' already exists — verifying config"
        existing_subnet=$(docker network inspect "${BMT_NETWORK_NAME}" \
            --format '{{range .IPAM.Config}}{{.Subnet}}{{end}}')
        if [ "${existing_subnet}" != "${BMT_SUBNET}" ]; then
            log_warn "Subnet mismatch (have ${existing_subnet}, want ${BMT_SUBNET}). Recreating."
            docker network rm "${BMT_NETWORK_NAME}" >/dev/null 2>&1 || true
        else
            return 0
        fi
    fi

    log_info "Creating bridge network '${BMT_NETWORK_NAME}' (${BMT_SUBNET})"

    ipv6_flag=""
    if [ "${BMT_ENABLE_IPV6}" = "true" ]; then
        ipv6_flag="--ipv6"
    fi

    # Build auxiliary DNS args: Docker embedded DNS (127.0.0.11) is automatic;
    # we pass external fallback servers so containers can resolve public names.
    dns_args=""
    IFS=','
    for server in ${BMT_EXTERNAL_DNS}; do
        dns_args="${dns_args} --opt com.docker.network.bridge.host_binding_ipv4=0.0.0.0"
    done
    unset IFS

    docker network create \
        --driver bridge \
        --subnet "${BMT_SUBNET}" \
        --gateway "${BMT_GATEWAY}" \
        --opt com.docker.network.bridge.enable_icc=true \
        --opt com.docker.network.bridge.enable_ip_masquerade=true \
        --opt com.docker.network.bridge.name="${BMT_NETWORK_NAME}" \
        --label "ai.bemind.component=networking" \
        --label "ai.bemind.story=BMTOS-20" \
        ${ipv6_flag} \
        "${BMT_NETWORK_NAME}"

    log_info "Network '${BMT_NETWORK_NAME}' created successfully"
}

# ---------------------------------------------------------------------------
# Write resolv.conf snippet for containers that need explicit config
# ---------------------------------------------------------------------------
write_dns_resolv() {
    local resolv_dir="/etc/bmt_ai_os"
    mkdir -p "${resolv_dir}" 2>/dev/null || true

    # Docker embedded DNS is always 127.0.0.11 inside containers.
    # This file is for reference / manual overrides only.
    cat > "${resolv_dir}/resolv.conf" <<RESOLV
# BMT AI OS — Container DNS configuration
# Docker embedded DNS is used by default (127.0.0.11).
# External fallback servers are listed below.
nameserver 127.0.0.11
RESOLV

    IFS=','
    for server in ${BMT_EXTERNAL_DNS}; do
        echo "nameserver ${server}" >> "${resolv_dir}/resolv.conf"
    done
    unset IFS

    log_info "DNS resolv.conf written to ${resolv_dir}/resolv.conf"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    log_info "BMT AI OS network setup starting"
    check_docker
    cleanup_stale_networks
    ensure_network
    write_dns_resolv
    log_info "Network setup complete"
}

main "$@"
