#!/bin/sh
# BMT AI OS — iptables Firewall Rules
# Secures the AI stack: localhost and LAN access only by default.
# SPDX-License-Identifier: MIT

set -eu

# ---------------------------------------------------------------------------
# Configuration (override via environment)
# ---------------------------------------------------------------------------
BMT_NETWORK_NAME="${BMT_NETWORK_NAME:-bmt-ai-net}"
BMT_SUBNET="${BMT_SUBNET:-172.20.0.0/16}"
BMT_LAN_IFACE="${BMT_LAN_IFACE:-eth0}"
BMT_IPTABLES_PERSIST="${BMT_IPTABLES_PERSIST:-/etc/iptables/rules-bmt.v4}"

# Ports exposed to localhost (all services)
LOCALHOST_PORTS="6006 8000 8080 8888 9090 11434"

# Ports exposed to LAN (Dashboard + API only)
LAN_PORTS="8080 9090"

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
log_info()  { echo "[bmt-fw]  INFO: $*"; }
log_warn()  { echo "[bmt-fw]  WARN: $*" >&2; }
log_error() { echo "[bmt-fw] ERROR: $*" >&2; }

# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------
check_iptables() {
    if ! command -v iptables >/dev/null 2>&1; then
        log_error "iptables not found — firewall rules cannot be applied"
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# BMT chain management
# ---------------------------------------------------------------------------
BMT_CHAIN="BMT-AI-STACK"

flush_bmt_rules() {
    log_info "Flushing existing BMT firewall rules..."
    iptables -D FORWARD -j "${BMT_CHAIN}" 2>/dev/null || true
    iptables -F "${BMT_CHAIN}" 2>/dev/null || true
    iptables -X "${BMT_CHAIN}" 2>/dev/null || true
}

create_bmt_chain() {
    log_info "Creating ${BMT_CHAIN} chain"
    iptables -N "${BMT_CHAIN}"
    iptables -I FORWARD -j "${BMT_CHAIN}"
}

# ---------------------------------------------------------------------------
# Rule sets
# ---------------------------------------------------------------------------

# Allow inter-container traffic within the AI stack subnet
allow_inter_container() {
    log_info "Allowing inter-container traffic on ${BMT_SUBNET}"
    iptables -A "${BMT_CHAIN}" -s "${BMT_SUBNET}" -d "${BMT_SUBNET}" -j ACCEPT
}

# Allow localhost to reach all service ports
allow_localhost() {
    log_info "Allowing localhost access to service ports"
    for port in ${LOCALHOST_PORTS}; do
        iptables -A INPUT -i lo -p tcp --dport "${port}" -j ACCEPT
    done
}

# Allow LAN access to Dashboard and API only
allow_lan() {
    log_info "Allowing LAN access to ports: ${LAN_PORTS}"
    for port in ${LAN_PORTS}; do
        iptables -A INPUT -i "${BMT_LAN_IFACE}" -p tcp --dport "${port}" -j ACCEPT
    done
}

# Block external access to internal-only ports
block_external() {
    log_info "Blocking external access to internal service ports"
    for port in ${LOCALHOST_PORTS}; do
        # Skip ports that are already allowed for LAN
        is_lan="false"
        for lp in ${LAN_PORTS}; do
            if [ "${port}" = "${lp}" ]; then
                is_lan="true"
                break
            fi
        done
        if [ "${is_lan}" = "false" ]; then
            iptables -A INPUT -i "${BMT_LAN_IFACE}" -p tcp --dport "${port}" -j DROP
        fi
    done
}

# Allow established and related connections
allow_established() {
    iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
    iptables -A "${BMT_CHAIN}" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
}

# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
persist_rules() {
    local persist_dir
    persist_dir=$(dirname "${BMT_IPTABLES_PERSIST}")
    mkdir -p "${persist_dir}" 2>/dev/null || true

    log_info "Persisting iptables rules to ${BMT_IPTABLES_PERSIST}"
    iptables-save > "${BMT_IPTABLES_PERSIST}" 2>/dev/null || {
        log_warn "Could not persist iptables rules (iptables-save failed)"
    }
}

# ---------------------------------------------------------------------------
# Port management helpers (for runtime use)
# ---------------------------------------------------------------------------
open_port() {
    local port="${1:?Usage: open_port <port>}"
    log_info "Opening port ${port} to LAN"
    iptables -I INPUT -i "${BMT_LAN_IFACE}" -p tcp --dport "${port}" -j ACCEPT
    persist_rules
}

close_port() {
    local port="${1:?Usage: close_port <port>}"
    log_info "Closing port ${port} from LAN"
    iptables -D INPUT -i "${BMT_LAN_IFACE}" -p tcp --dport "${port}" -j ACCEPT 2>/dev/null || true
    persist_rules
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    log_info "BMT AI OS firewall setup starting"
    check_iptables
    flush_bmt_rules
    create_bmt_chain
    allow_established
    allow_inter_container
    allow_localhost
    allow_lan
    block_external
    persist_rules
    log_info "Firewall setup complete"
}

# Allow sourcing for open_port/close_port helpers
case "${1:-}" in
    open)   shift; open_port "$@" ;;
    close)  shift; close_port "$@" ;;
    *)      main "$@" ;;
esac
