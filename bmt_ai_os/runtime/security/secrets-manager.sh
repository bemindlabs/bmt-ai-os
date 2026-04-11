#!/bin/sh
# BMT AI OS — Secrets Manager (ARM64)
#
# BMTOS-21 | Epic: BMTOS-EPIC-3 (OS Foundation & Infrastructure)
#
# Manages API keys and credentials for the AI stack.
# Secrets are stored as individual files under /etc/bmt_ai_os/secrets/
# with strict filesystem permissions (0600 root:root).
#
# Usage:
#   secrets-manager.sh init                  — create secrets directory tree
#   secrets-manager.sh set KEY VALUE         — store a secret
#   secrets-manager.sh get KEY               — retrieve a secret value
#   secrets-manager.sh list                  — list stored secret keys
#   secrets-manager.sh rotate KEY            — rotate a secret (archive old value)
#   secrets-manager.sh inject SERVICE        — copy service secrets to mount dir
#
# Supported secret keys:
#   OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY,
#   MISTRAL_API_KEY, GROQ_API_KEY, CHROMA_AUTH_CREDENTIALS

set -eu

SECRETS_BASE="/etc/bmt_ai_os/secrets"
ARCHIVE_DIR="${SECRETS_BASE}/.archive"
SERVICES="ollama chromadb controller"

# Supported secret keys
VALID_KEYS="OPENAI_API_KEY ANTHROPIC_API_KEY GOOGLE_API_KEY MISTRAL_API_KEY GROQ_API_KEY CHROMA_AUTH_CREDENTIALS"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

die() {
    printf "ERROR: %s\n" "$1" >&2
    exit 1
}

require_root() {
    [ "$(id -u)" -eq 0 ] || die "This script must be run as root."
}

validate_key() {
    key="$1"
    for valid in $VALID_KEYS; do
        [ "$key" = "$valid" ] && return 0
    done
    die "Unknown secret key: ${key}. Valid keys: ${VALID_KEYS}"
}

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

cmd_init() {
    require_root
    printf "Initializing secrets directory tree...\n"

    # Create base directory with restricted permissions
    mkdir -p "$SECRETS_BASE"
    chmod 0700 "$SECRETS_BASE"
    chown root:root "$SECRETS_BASE"

    # Create archive directory for rotated secrets
    mkdir -p "$ARCHIVE_DIR"
    chmod 0700 "$ARCHIVE_DIR"
    chown root:root "$ARCHIVE_DIR"

    # Create per-service mount directories
    for svc in $SERVICES; do
        svc_dir="${SECRETS_BASE}/${svc}"
        mkdir -p "$svc_dir"
        chmod 0700 "$svc_dir"
        chown root:root "$svc_dir"
    done

    printf "Secrets directory initialized at %s\n" "$SECRETS_BASE"
}

cmd_set() {
    require_root
    [ $# -ge 2 ] || die "Usage: secrets-manager.sh set KEY VALUE"

    key="$1"
    value="$2"
    validate_key "$key"

    # Ensure base directory exists
    [ -d "$SECRETS_BASE" ] || die "Secrets directory not initialized. Run: secrets-manager.sh init"

    secret_file="${SECRETS_BASE}/${key}"

    # Write secret atomically via temp file
    tmp_file=$(mktemp "${SECRETS_BASE}/.tmp.XXXXXX")
    printf "%s" "$value" > "$tmp_file"
    chmod 0600 "$tmp_file"
    chown root:root "$tmp_file"
    mv "$tmp_file" "$secret_file"

    printf "Secret '%s' stored.\n" "$key"
}

cmd_get() {
    require_root
    [ $# -ge 1 ] || die "Usage: secrets-manager.sh get KEY"

    key="$1"
    validate_key "$key"

    secret_file="${SECRETS_BASE}/${key}"
    [ -f "$secret_file" ] || die "Secret '${key}' not found."

    cat "$secret_file"
}

cmd_list() {
    require_root
    [ -d "$SECRETS_BASE" ] || die "Secrets directory not initialized."

    printf "Stored secrets:\n"
    for key in $VALID_KEYS; do
        if [ -f "${SECRETS_BASE}/${key}" ]; then
            printf "  [*] %s\n" "$key"
        else
            printf "  [ ] %s\n" "$key"
        fi
    done
}

cmd_rotate() {
    require_root
    [ $# -ge 1 ] || die "Usage: secrets-manager.sh rotate KEY"

    key="$1"
    validate_key "$key"

    secret_file="${SECRETS_BASE}/${key}"
    [ -f "$secret_file" ] || die "Secret '${key}' not found. Set it first."

    # Archive the old value with timestamp
    timestamp=$(date +%Y%m%d%H%M%S)
    archive_file="${ARCHIVE_DIR}/${key}.${timestamp}"
    cp "$secret_file" "$archive_file"
    chmod 0600 "$archive_file"
    chown root:root "$archive_file"

    printf "Old value archived to %s\n" "$archive_file"
    printf "Now set the new value with: secrets-manager.sh set %s NEW_VALUE\n" "$key"
}

cmd_inject() {
    require_root
    [ $# -ge 1 ] || die "Usage: secrets-manager.sh inject SERVICE"

    service="$1"
    svc_dir="${SECRETS_BASE}/${service}"
    [ -d "$svc_dir" ] || die "No secrets directory for service '${service}'."

    # Map secrets to services
    case "$service" in
        ollama)
            keys="OPENAI_API_KEY ANTHROPIC_API_KEY GOOGLE_API_KEY MISTRAL_API_KEY GROQ_API_KEY"
            ;;
        chromadb)
            keys="CHROMA_AUTH_CREDENTIALS"
            ;;
        controller)
            keys="OPENAI_API_KEY ANTHROPIC_API_KEY GOOGLE_API_KEY MISTRAL_API_KEY GROQ_API_KEY"
            ;;
        *)
            die "Unknown service: ${service}"
            ;;
    esac

    injected=0
    for key in $keys; do
        src="${SECRETS_BASE}/${key}"
        if [ -f "$src" ]; then
            cp "$src" "${svc_dir}/${key}"
            chmod 0600 "${svc_dir}/${key}"
            chown root:root "${svc_dir}/${key}"
            injected=$((injected + 1))
        fi
    done

    printf "Injected %d secret(s) into %s\n" "$injected" "$svc_dir"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

usage() {
    printf "Usage: %s {init|set|get|list|rotate|inject} [args...]\n" "$(basename "$0")"
    exit 1
}

[ $# -ge 1 ] || usage

command="$1"
shift

case "$command" in
    init)    cmd_init ;;
    set)     cmd_set "$@" ;;
    get)     cmd_get "$@" ;;
    list)    cmd_list ;;
    rotate)  cmd_rotate "$@" ;;
    inject)  cmd_inject "$@" ;;
    *)       usage ;;
esac
