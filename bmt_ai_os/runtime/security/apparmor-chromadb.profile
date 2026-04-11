# BMT AI OS — AppArmor Profile for ChromaDB Container (ARM64)
#
# BMTOS-50 | Epic: BMTOS-EPIC-3 (OS Foundation & Infrastructure)
#
# ChromaDB stores HNSW vector indices and SQLite metadata under /chroma.
# It exposes a REST API on port 8000 and accepts intra-stack connections
# only (Docker bridge network 172.30.0.0/16).
#
# Install:
#   sudo cp apparmor-chromadb.profile /etc/apparmor.d/bmt-chromadb
#   sudo apparmor_parser -r /etc/apparmor.d/bmt-chromadb
#
# Reference in docker-compose security_opt:
#   security_opt:
#     - apparmor=bmt-chromadb

#include <tunables/global>

profile bmt-chromadb flags=(attach_disconnected,mediate_deleted) {
  #include <abstractions/base>
  #include <abstractions/nameservice>
  #include <abstractions/python>

  # ---------------------------------------------------------------------------
  # Network access
  # ---------------------------------------------------------------------------

  # Allow TCP: REST API (8000) and inbound connections from bmt-ai-net
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
  # ChromaDB data directory — HNSW index, SQLite WAL, segment files
  # ---------------------------------------------------------------------------

  /chroma/                    r,
  /chroma/**                  rwk,

  # ---------------------------------------------------------------------------
  # Secrets (read-only bind-mount from host)
  # ---------------------------------------------------------------------------

  /run/secrets/               r,
  /run/secrets/**             r,

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

  # Python executable and site-packages
  /usr/bin/python3*           mrix,
  /usr/local/bin/python3*     mrix,
  /usr/local/bin/chroma*      mrix,
  /usr/local/bin/uvicorn      mrix,
  /bin/**                     mrix,
  /usr/bin/**                 mrix,

  # Python bytecode cache (inside the image)
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

  # Deny Docker socket (ChromaDB must not control other containers)
  deny /var/run/docker.sock   rw,
  deny /run/docker.sock       rw,

  # Deny Ollama model store (no cross-service data access)
  deny /root/.ollama/**       rwx,

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
