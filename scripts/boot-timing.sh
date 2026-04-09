#!/bin/sh
# BMT AI OS — Boot Timing Measurement
# Measures wall-clock time from kernel start to each service milestone.
# Outputs results to stdout and saves JSON to /var/log/bmt-ai-os/boot-timing.json.
#
# Usage: boot-timing.sh [--json-only]
#
# BMTOS-17 | Epic: BMTOS-EPIC-3 (OS Foundation & Infrastructure)

set -eu

JSON_OUT="/var/log/bmt-ai-os/boot-timing.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Read nanosecond timestamp from a file, return milliseconds since boot.
_ts_ms() {
    local file="$1"
    if [ -f "${file}" ]; then
        local ns
        ns=$(cat "${file}" 2>/dev/null)
        echo $(( ns / 1000000 ))
    else
        echo ""
    fi
}

# Get kernel boot timestamp (seconds since epoch when kernel started).
# We derive this from /proc/uptime and the current epoch time.
_kernel_epoch_ms() {
    local now_s now_us uptime_s uptime_cs
    now_s=$(date +%s)
    uptime_s=$(cut -d. -f1 /proc/uptime)
    echo $(( (now_s - uptime_s) * 1000 ))
}

# Read OpenRC timing from dmesg/rc.log if available
_openrc_start_ms() {
    # OpenRC logs its start in /run/openrc/started — use the earliest file
    local earliest=""
    for f in /run/openrc/started/*; do
        if [ -f "${f}" ]; then
            earliest="${f}"
            break
        fi
    done
    if [ -n "${earliest}" ]; then
        local mtime
        mtime=$(stat -c %Y "${earliest}" 2>/dev/null || stat -f %m "${earliest}" 2>/dev/null)
        if [ -n "${mtime}" ]; then
            echo $(( mtime * 1000 ))
        fi
    fi
}

# ---------------------------------------------------------------------------
# Collect timestamps
# ---------------------------------------------------------------------------

kernel_ms=$(_kernel_epoch_ms)

# Service timestamps recorded by init scripts (nanoseconds since epoch)
containerd_start=$(_ts_ms /run/bmt-containerd-start.ts)
docker_start=$(_ts_ms /run/bmt-docker-start.ts)
ai_stack_start=$(_ts_ms /run/bmt-ai-stack-start.ts)
ai_stack_ready=$(_ts_ms /run/bmt-ai-stack-ready.ts)
controller_start=$(_ts_ms /run/bmt-controller-start.ts)
controller_ready=$(_ts_ms /run/bmt-controller-ready.ts)

# ---------------------------------------------------------------------------
# Compute deltas (all in milliseconds)
# ---------------------------------------------------------------------------

_delta() {
    local from="$1" to="$2"
    if [ -n "${from}" ] && [ -n "${to}" ]; then
        echo $(( to - from ))
    else
        echo "null"
    fi
}

d_kernel_to_containerd=$(_delta "${kernel_ms}" "${containerd_start}")
d_containerd_to_docker=$(_delta "${containerd_start}" "${docker_start}")
d_docker_to_aistack=$(_delta "${docker_start}" "${ai_stack_start}")
d_aistack_start_to_ready=$(_delta "${ai_stack_start}" "${ai_stack_ready}")
d_aistack_to_controller=$(_delta "${ai_stack_ready}" "${controller_start}")
d_total=$(_delta "${kernel_ms}" "${controller_ready}")

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

if [ "${1:-}" != "--json-only" ]; then
    echo "=== BMT AI OS Boot Timing ==="
    echo ""
    printf "  %-30s %s ms\n" "Kernel -> Containerd:" "${d_kernel_to_containerd}"
    printf "  %-30s %s ms\n" "Containerd -> Docker:" "${d_containerd_to_docker}"
    printf "  %-30s %s ms\n" "Docker -> AI Stack start:" "${d_docker_to_aistack}"
    printf "  %-30s %s ms\n" "AI Stack start -> ready:" "${d_aistack_start_to_ready}"
    printf "  %-30s %s ms\n" "AI Stack -> Controller:" "${d_aistack_to_controller}"
    echo ""
    printf "  %-30s %s ms\n" "TOTAL (kernel -> ready):" "${d_total}"
    echo ""
fi

# Save JSON
mkdir -p "$(dirname "${JSON_OUT}")"
cat > "${JSON_OUT}" <<EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "unit": "milliseconds",
  "stages": {
    "kernel_to_containerd": ${d_kernel_to_containerd},
    "containerd_to_docker": ${d_containerd_to_docker},
    "docker_to_ai_stack_start": ${d_docker_to_aistack},
    "ai_stack_start_to_ready": ${d_aistack_start_to_ready},
    "ai_stack_ready_to_controller": ${d_aistack_to_controller}
  },
  "total_boot_to_ready_ms": ${d_total},
  "timestamps_ms": {
    "kernel": ${kernel_ms:-null},
    "containerd_start": ${containerd_start:-null},
    "docker_start": ${docker_start:-null},
    "ai_stack_start": ${ai_stack_start:-null},
    "ai_stack_ready": ${ai_stack_ready:-null},
    "controller_start": ${controller_start:-null},
    "controller_ready": ${controller_ready:-null}
  }
}
EOF

echo "Saved: ${JSON_OUT}"
