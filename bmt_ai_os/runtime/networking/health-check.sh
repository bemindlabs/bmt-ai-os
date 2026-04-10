#!/bin/bash
# BMT AI OS — Network Health Verification
# Checks DNS resolution, port connectivity, and network state.
# Outputs a JSON report to stdout.
# SPDX-License-Identifier: MIT

set -eu

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BMT_NETWORK_NAME="${BMT_NETWORK_NAME:-bmt-ai-net}"
DNS_CONFIG="${DNS_CONFIG:-/etc/bmt_ai_os/dns-config.json}"
CHECK_EXTERNAL="${CHECK_EXTERNAL:-true}"
CONNECT_TIMEOUT="${CONNECT_TIMEOUT:-3}"

# Service definitions: name:container:port
SERVICES="ollama:bmt-ollama:11434 chromadb:bmt-chromadb:8000"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
json_bool() {
    if [ "$1" = "0" ]; then echo "true"; else echo "false"; fi
}

timestamp() {
    date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date +"%Y-%m-%dT%H:%M:%SZ"
}

# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

# Check whether the Docker network exists
check_network_exists() {
    docker network inspect "${BMT_NETWORK_NAME}" >/dev/null 2>&1
    return $?
}

# Check DNS resolution between containers (from inside a running container)
check_container_dns() {
    local service_name="$1"
    local container_name="$2"

    # Try to resolve the service_name from inside another running container
    # We pick the first *other* container on the network.
    local probe_container
    probe_container=$(docker network inspect "${BMT_NETWORK_NAME}" \
        --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null \
        | tr ' ' '\n' | grep -v "^${container_name}$" | head -1)

    if [ -z "${probe_container}" ]; then
        # Only one container — resolve from itself
        probe_container="${container_name}"
    fi

    # Use getent or nslookup inside the container
    docker exec "${probe_container}" \
        sh -c "getent hosts ${service_name} 2>/dev/null || nslookup ${service_name} 2>/dev/null" \
        >/dev/null 2>&1
    return $?
}

# Check host-to-container port connectivity
check_host_port() {
    local port="$1"
    # Use /dev/tcp or curl to check localhost connectivity
    if command -v curl >/dev/null 2>&1; then
        curl -sf --connect-timeout "${CONNECT_TIMEOUT}" "http://localhost:${port}/" >/dev/null 2>&1
        return $?
    elif command -v nc >/dev/null 2>&1; then
        nc -z -w "${CONNECT_TIMEOUT}" localhost "${port}" >/dev/null 2>&1
        return $?
    else
        # Fallback: try wget
        wget -q --timeout="${CONNECT_TIMEOUT}" -O /dev/null "http://localhost:${port}/" 2>/dev/null
        return $?
    fi
}

# Check external DNS resolution (internet connectivity)
check_external_dns() {
    if command -v nslookup >/dev/null 2>&1; then
        nslookup cloudflare.com >/dev/null 2>&1
        return $?
    elif command -v getent >/dev/null 2>&1; then
        getent hosts cloudflare.com >/dev/null 2>&1
        return $?
    elif command -v host >/dev/null 2>&1; then
        host cloudflare.com >/dev/null 2>&1
        return $?
    fi
    return 1
}

# ---------------------------------------------------------------------------
# Main — produce JSON report
# ---------------------------------------------------------------------------
main() {
    local ts
    ts=$(timestamp)
    local overall="pass"

    # Network exists?
    check_network_exists
    local net_ok=$?
    if [ "${net_ok}" -ne 0 ]; then overall="fail"; fi

    # Per-service checks
    local svc_results=""
    for entry in ${SERVICES}; do
        name=$(echo "${entry}" | cut -d: -f1)
        container=$(echo "${entry}" | cut -d: -f2)
        port=$(echo "${entry}" | cut -d: -f3)

        # DNS check
        dns_ok=1
        if [ "${net_ok}" -eq 0 ]; then
            check_container_dns "${name}" "${container}" && dns_ok=0 || dns_ok=1
        fi

        # Port check
        port_ok=1
        check_host_port "${port}" && port_ok=0 || port_ok=1

        if [ "${dns_ok}" -ne 0 ] || [ "${port_ok}" -ne 0 ]; then
            overall="fail"
        fi

        svc_results="${svc_results}
    {
      \"service\": \"${name}\",
      \"container\": \"${container}\",
      \"dns_resolution\": $(json_bool ${dns_ok}),
      \"host_port_reachable\": $(json_bool ${port_ok}),
      \"port\": ${port}
    },"
    done

    # Remove trailing comma
    svc_results=$(echo "${svc_results}" | sed '$ s/,$//')

    # External DNS
    ext_ok=1
    if [ "${CHECK_EXTERNAL}" = "true" ]; then
        check_external_dns && ext_ok=0 || ext_ok=1
    fi

    # Connected containers count
    container_count=0
    if [ "${net_ok}" -eq 0 ]; then
        container_count=$(docker network inspect "${BMT_NETWORK_NAME}" \
            --format '{{len .Containers}}' 2>/dev/null || echo 0)
    fi

    # Output JSON report
    cat <<JSON
{
  "timestamp": "${ts}",
  "network": "${BMT_NETWORK_NAME}",
  "network_exists": $(json_bool ${net_ok}),
  "connected_containers": ${container_count},
  "external_dns": $(json_bool ${ext_ok}),
  "overall": "${overall}",
  "services": [${svc_results}
  ]
}
JSON
}

main "$@"
