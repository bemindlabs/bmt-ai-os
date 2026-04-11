#!/bin/bash
# BMT AI OS — iptables/nftables Firewall Rules
# Secures the AI stack: localhost and LAN access only by default.
# Enforces container-to-container network policies (restrict to required paths).
# SPDX-License-Identifier: MIT

set -eu

# ---------------------------------------------------------------------------
# Configuration (override via environment)
# ---------------------------------------------------------------------------
BMT_NETWORK_NAME="${BMT_NETWORK_NAME:-bmt-ai-net}"
BMT_SUBNET="${BMT_SUBNET:-172.30.0.0/16}"
BMT_LAN_IFACE="${BMT_LAN_IFACE:-eth0}"
BMT_IPTABLES_PERSIST="${BMT_IPTABLES_PERSIST:-/etc/iptables/rules-bmt.v4}"
BMT_TLS_PORT="${BMT_TLS_PORT:-8443}"
BMT_NFTABLES_CONF="${BMT_NFTABLES_CONF:-/etc/nftables.d/bmt-ai.nft}"

# Ports exposed to localhost (all services)
LOCALHOST_PORTS="6006 8000 8080 8443 8888 9090 11434"

# Ports exposed to LAN (Dashboard, API, HTTPS only)
LAN_PORTS="8080 8443 9090"

# Controller API port (http fallback)
CONTROLLER_PORT=8080
# ChromaDB internal port — no external access
CHROMADB_PORT=8000
# Ollama internal port — no external access
OLLAMA_PORT=11434

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

has_nftables() {
    command -v nft >/dev/null 2>&1
}

# ---------------------------------------------------------------------------
# BMT chain management
# ---------------------------------------------------------------------------
BMT_CHAIN="BMT-AI-STACK"
BMT_POLICY_CHAIN="BMT-NET-POLICY"

flush_bmt_rules() {
    log_info "Flushing existing BMT firewall rules..."
    iptables -D FORWARD -j "${BMT_CHAIN}" 2>/dev/null || true
    iptables -F "${BMT_CHAIN}" 2>/dev/null || true
    iptables -X "${BMT_CHAIN}" 2>/dev/null || true

    iptables -D FORWARD -j "${BMT_POLICY_CHAIN}" 2>/dev/null || true
    iptables -F "${BMT_POLICY_CHAIN}" 2>/dev/null || true
    iptables -X "${BMT_POLICY_CHAIN}" 2>/dev/null || true
}

create_bmt_chain() {
    log_info "Creating ${BMT_CHAIN} chain"
    iptables -N "${BMT_CHAIN}"
    iptables -N "${BMT_POLICY_CHAIN}"
    iptables -I FORWARD 1 -j "${BMT_POLICY_CHAIN}"
    iptables -I FORWARD 2 -j "${BMT_CHAIN}"
}

# ---------------------------------------------------------------------------
# Rule sets
# ---------------------------------------------------------------------------

# Allow established and related connections (stateful inspection)
allow_established() {
    iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
    iptables -A "${BMT_CHAIN}" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
}

# Allow loopback
allow_loopback() {
    iptables -A INPUT -i lo -j ACCEPT
    iptables -A OUTPUT -o lo -j ACCEPT
}

# Network policy: restrict container-to-container traffic to required paths.
#
# Allowed flows within bmt-ai-net (172.30.0.0/16):
#   controller  → chromadb  :8000  (RAG vector queries)
#   controller  → ollama    :11434 (LLM inference)
#   dashboard   → controller:8080  (API proxy)
#
# All other intra-subnet forwards are denied by default.
apply_network_policy() {
    log_info "Applying container-to-container network policies"

    # Controller → ChromaDB (RAG queries)
    iptables -A "${BMT_POLICY_CHAIN}" \
        -s "${BMT_SUBNET}" -d "${BMT_SUBNET}" \
        -p tcp --dport "${CHROMADB_PORT}" \
        -m comment --comment "bmt: controller→chromadb" \
        -j ACCEPT

    # Controller → Ollama (inference)
    iptables -A "${BMT_POLICY_CHAIN}" \
        -s "${BMT_SUBNET}" -d "${BMT_SUBNET}" \
        -p tcp --dport "${OLLAMA_PORT}" \
        -m comment --comment "bmt: controller→ollama" \
        -j ACCEPT

    # Dashboard → Controller API (HTTP)
    iptables -A "${BMT_POLICY_CHAIN}" \
        -s "${BMT_SUBNET}" -d "${BMT_SUBNET}" \
        -p tcp --dport "${CONTROLLER_PORT}" \
        -m comment --comment "bmt: dashboard→controller-http" \
        -j ACCEPT

    # Dashboard → Controller API (HTTPS/TLS)
    iptables -A "${BMT_POLICY_CHAIN}" \
        -s "${BMT_SUBNET}" -d "${BMT_SUBNET}" \
        -p tcp --dport "${BMT_TLS_PORT}" \
        -m comment --comment "bmt: dashboard→controller-https" \
        -j ACCEPT

    # Block all other intra-subnet container-to-container traffic
    iptables -A "${BMT_POLICY_CHAIN}" \
        -s "${BMT_SUBNET}" -d "${BMT_SUBNET}" \
        -m comment --comment "bmt: default deny intra-subnet" \
        -j DROP
}

# Allow inter-container traffic within the AI stack subnet (legacy fallback,
# used when network policy is NOT applied — keeps backward compatibility)
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

# Allow LAN access to Dashboard, API, and HTTPS only
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
        is_lan="false"
        for lp in ${LAN_PORTS}; do
            if [ "${port}" = "${lp}" ]; then
                is_lan="true"
                break
            fi
        done
        if [ "${is_lan}" = "false" ]; then
            iptables -A INPUT -i "${BMT_LAN_IFACE}" -p tcp --dport "${port}" \
                -m comment --comment "bmt: block external port ${port}" \
                -j DROP
        fi
    done
}

# Drop invalid packets
block_invalid() {
    log_info "Dropping INVALID state packets"
    iptables -A INPUT -m conntrack --ctstate INVALID -j DROP
    iptables -A FORWARD -m conntrack --ctstate INVALID -j DROP
}

# Rate-limit new connections to API port (simple SYN flood mitigation)
rate_limit_api() {
    log_info "Rate-limiting new connections to API port ${CONTROLLER_PORT}"
    iptables -A INPUT -i "${BMT_LAN_IFACE}" -p tcp --dport "${CONTROLLER_PORT}" \
        --syn -m limit --limit 30/min --limit-burst 60 \
        -m comment --comment "bmt: api rate-limit" \
        -j ACCEPT
    iptables -A INPUT -i "${BMT_LAN_IFACE}" -p tcp --dport "${CONTROLLER_PORT}" \
        --syn \
        -m comment --comment "bmt: api rate-limit drop excess" \
        -j DROP

    log_info "Rate-limiting new connections to TLS port ${BMT_TLS_PORT}"
    iptables -A INPUT -i "${BMT_LAN_IFACE}" -p tcp --dport "${BMT_TLS_PORT}" \
        --syn -m limit --limit 30/min --limit-burst 60 \
        -m comment --comment "bmt: tls rate-limit" \
        -j ACCEPT
    iptables -A INPUT -i "${BMT_LAN_IFACE}" -p tcp --dport "${BMT_TLS_PORT}" \
        --syn \
        -m comment --comment "bmt: tls rate-limit drop excess" \
        -j DROP
}

# ---------------------------------------------------------------------------
# nftables companion ruleset (written to file, loaded on boot)
# ---------------------------------------------------------------------------
write_nftables_conf() {
    if ! has_nftables; then
        log_warn "nft not found — skipping nftables configuration"
        return 0
    fi

    local conf_dir
    conf_dir=$(dirname "${BMT_NFTABLES_CONF}")
    mkdir -p "${conf_dir}" 2>/dev/null || true

    log_info "Writing nftables companion config to ${BMT_NFTABLES_CONF}"
    cat > "${BMT_NFTABLES_CONF}" <<'NFTCONF'
# BMT AI OS — nftables network policy
# Loaded by: nft -f /etc/nftables.d/bmt-ai.nft
# SPDX-License-Identifier: MIT

table inet bmt_ai_filter {

    # Track connection state
    chain input {
        type filter hook input priority 0; policy drop;

        ct state established,related accept comment "stateful"
        ct state invalid drop comment "drop invalid"
        iif lo accept comment "loopback"

        # ICMP (ping) — accept for diagnostics
        ip protocol icmp accept
        ip6 nexthdr icmpv6 accept

        # SSH (management access)
        tcp dport 22 accept

        # Localhost ports
        iif lo tcp dport { 6006, 8000, 8080, 8443, 8888, 9090, 11434 } accept

        # LAN-accessible ports (dashboard + API)
        tcp dport { 8080, 8443, 9090 } accept

        # Rate-limit API + TLS ports (SYN flood mitigation)
        tcp dport { 8080, 8443 } ct state new limit rate 30/minute burst 60 packets accept
        tcp dport { 8080, 8443 } ct state new drop

        # DNS-over-TLS outbound (port 853) — handled in forward chain
    }

    chain forward {
        type filter hook forward priority 0; policy drop;

        ct state established,related accept
        ct state invalid drop

        # Container-to-container network policy (172.30.0.0/16)
        # controller → chromadb :8000
        ip saddr 172.30.0.0/16 ip daddr 172.30.0.0/16 tcp dport 8000 accept \
            comment "bmt: controller→chromadb"

        # controller → ollama :11434
        ip saddr 172.30.0.0/16 ip daddr 172.30.0.0/16 tcp dport 11434 accept \
            comment "bmt: controller→ollama"

        # dashboard → controller :8080/:8443
        ip saddr 172.30.0.0/16 ip daddr 172.30.0.0/16 tcp dport { 8080, 8443 } accept \
            comment "bmt: dashboard→controller"

        # Default deny all other intra-subnet forwards
        ip saddr 172.30.0.0/16 ip daddr 172.30.0.0/16 drop \
            comment "bmt: default deny intra-subnet"
    }

    chain output {
        type filter hook output priority 0; policy accept;

        # Allow DNS-over-TLS (port 853) for outbound queries
        tcp dport 853 accept comment "DNS-over-TLS"
        udp dport 853 accept comment "DNS-over-TLS"
    }
}
NFTCONF

    log_info "nftables configuration written"
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
    local with_policy="${1:-true}"

    log_info "BMT AI OS firewall setup starting"
    check_iptables
    flush_bmt_rules
    create_bmt_chain
    allow_established
    allow_loopback
    block_invalid

    if [ "${with_policy}" = "policy" ] || [ "${BMT_NETWORK_POLICY:-true}" = "true" ]; then
        apply_network_policy
    else
        allow_inter_container
    fi

    allow_localhost
    rate_limit_api
    allow_lan
    block_external
    persist_rules
    write_nftables_conf
    log_info "Firewall setup complete"
}

# Allow sourcing for open_port/close_port helpers
case "${1:-}" in
    open)       shift; open_port "$@" ;;
    close)      shift; close_port "$@" ;;
    policy)     main "policy" ;;
    no-policy)  main "false" ;;
    *)          main ;;
esac
