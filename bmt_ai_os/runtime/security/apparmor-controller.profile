# BMT AI OS — AppArmor Profile for Controller Container (ARM64)
#
# BMTOS-50 | Epic: BMTOS-EPIC-3 (OS Foundation & Infrastructure)
#
# The controller is a Python/FastAPI service that:
#   - Exposes an OpenAI-compatible REST API on port 8080
#   - Manages AI-stack containers via the Docker socket
#   - Reads config from /app (or /etc/bmt_ai_os) and writes to /var/log
#   - Performs health checks over HTTP (no ML inference workloads)
#
# Access to the Docker socket is intentional and required: the controller
# uses docker-py to start, stop, and inspect bmt-ollama and bmt-chromadb.
# It must NOT access the host filesystem beyond its config and log paths.
#
# Install:
#   sudo cp apparmor-controller.profile /etc/apparmor.d/bmt-controller
#   sudo apparmor_parser -r /etc/apparmor.d/bmt-controller
#
# Reference in docker-compose security_opt:
#   security_opt:
#     - apparmor=bmt-controller

#include <tunables/global>

profile bmt-controller flags=(attach_disconnected,mediate_deleted) {
  #include <abstractions/base>
  #include <abstractions/nameservice>
  #include <abstractions/python>

  # ---------------------------------------------------------------------------
  # Network access
  # ---------------------------------------------------------------------------

  # Allow TCP: OpenAI-compat API (8080) + outbound health checks to ai-stack
  network inet  tcp,
  network inet6 tcp,

  # Allow UDP for DNS resolution
  network inet  udp,
  network inet6 udp,

  # Deny raw and packet sockets
  deny network raw,
  deny network packet,
  deny network netlink,

  # ---------------------------------------------------------------------------
  # Application paths — controller source, config, and logs
  # ---------------------------------------------------------------------------

  # Controller application code (read-only; mounted from image)
  /app/                       r,
  /app/**                     r,

  # Runtime config directory
  /etc/bmt_ai_os/             r,
  /etc/bmt_ai_os/**           r,

  # Log output
  /var/log/bmt-controller.log rw,
  /var/log/bmt/               rw,
  /var/log/bmt/**             rw,

  # ---------------------------------------------------------------------------
  # Secrets (read-only bind-mount from host)
  # ---------------------------------------------------------------------------

  /run/secrets/               r,
  /run/secrets/**             r,

  # ---------------------------------------------------------------------------
  # Docker socket — required for container management via docker-py
  # ---------------------------------------------------------------------------

  /var/run/docker.sock        rw,
  /run/docker.sock            rw,

  # ---------------------------------------------------------------------------
  # Temporary storage (tmpfs)
  # ---------------------------------------------------------------------------

  /tmp/                       rw,
  /tmp/**                     rwk,

  # ---------------------------------------------------------------------------
  # Standard Python / runtime paths
  # ---------------------------------------------------------------------------

  /proc/                      r,
  /proc/self/**               r,
  /proc/sys/net/**            r,
  /sys/devices/system/cpu/**  r,
  /sys/fs/cgroup/**           r,

  # Shared libraries
  /lib/**                     mr,
  /lib64/**                   mr,
  /usr/lib/**                 mr,
  /usr/lib64/**               mr,
  /usr/local/lib/**           mr,

  # Python executables
  /usr/bin/python3*           mrix,
  /usr/local/bin/python3*     mrix,
  /usr/local/bin/uvicorn      mrix,
  /bin/**                     mrix,
  /usr/bin/**                 mrix,

  # Python bytecode cache
  /usr/local/lib/python*/**   mr,
  /usr/local/lib/python*/__pycache__/** rwk,

  # ---------------------------------------------------------------------------
  # Device access
  # ---------------------------------------------------------------------------

  /dev/null                   rw,
  /dev/zero                   r,
  /dev/urandom                r,
  /dev/random                 r,
  /dev/shm/**                 rw,

  # ---------------------------------------------------------------------------
  # Deny sensitive system paths
  # ---------------------------------------------------------------------------

  deny /etc/shadow            r,
  deny /etc/passwd            w,
  deny /etc/group             w,
  deny /etc/gshadow           r,
  deny /etc/sudoers           r,
  deny /etc/sudoers.d/**      r,
  deny /root/.ssh/**          rwx,
  deny /root/.gnupg/**        rwx,
  deny /root/.bash_history    r,

  # Deny host filesystem escape
  deny /host/**               rwx,
  deny /mnt/**                rwx,
  deny /media/**              rwx,

  # Deny kernel/module access
  deny /boot/**               rwx,
  deny /lib/modules/**        rwx,
  deny /usr/src/**            rwx,

  # Deny direct access to AI service data stores
  # (controller reaches these only via their REST APIs)
  deny /root/.ollama/**       rwx,
  deny /chroma/**             rwx,

  # ---------------------------------------------------------------------------
  # Capabilities
  # ---------------------------------------------------------------------------

  capability net_bind_service,

  # Deny all dangerous capabilities
  deny capability sys_admin,
  deny capability sys_module,
  deny capability sys_rawio,
  deny capability sys_ptrace,
  deny capability sys_boot,
  deny capability net_admin,
  deny capability net_raw,
  deny capability dac_override,
  deny capability dac_read_search,
  deny capability setuid,
  deny capability setgid,
  deny capability chown,
}
