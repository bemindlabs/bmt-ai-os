# BMT AI OS — AppArmor Profile for Ollama Container (ARM64)
#
# BMTOS-21 | Epic: BMTOS-EPIC-3 (OS Foundation & Infrastructure)
#
# Install:
#   sudo cp apparmor-ollama.profile /etc/apparmor.d/bmt-ollama
#   sudo apparmor_parser -r /etc/apparmor.d/bmt-ollama
#
# Then reference in docker-compose security overlay:
#   security_opt:
#     - apparmor=bmt-ollama

#include <tunables/global>

profile bmt-ollama flags=(attach_disconnected,mediate_deleted) {
  #include <abstractions/base>
  #include <abstractions/nameservice>

  # ---------------------------------------------------------------------------
  # Network access
  # ---------------------------------------------------------------------------

  # Allow TCP listen on Ollama API port
  network inet  tcp,
  network inet6 tcp,

  # Allow UDP for DNS resolution
  network inet  udp,
  network inet6 udp,

  # Deny raw sockets
  deny network raw,
  deny network packet,

  # ---------------------------------------------------------------------------
  # File access — model directory and runtime
  # ---------------------------------------------------------------------------

  # Ollama model storage (Docker volume mount)
  /root/.ollama/ r,
  /root/.ollama/** rwk,

  # Secrets (read-only mount from host)
  /run/secrets/ r,
  /run/secrets/** r,

  # Temp directory (tmpfs)
  /tmp/ rw,
  /tmp/** rwk,

  # Standard runtime paths
  /proc/ r,
  /proc/self/** r,
  /proc/sys/net/** r,
  /sys/devices/system/cpu/** r,
  /sys/fs/cgroup/** r,

  # Shared libraries
  /lib/** mr,
  /lib64/** mr,
  /usr/lib/** mr,
  /usr/lib64/** mr,
  /usr/local/lib/** mr,

  # Ollama binary
  /usr/local/bin/ollama mrix,
  /bin/** mrix,
  /usr/bin/** mrix,

  # Device access for inference
  /dev/null rw,
  /dev/zero r,
  /dev/urandom r,
  /dev/random r,
  /dev/shm/** rw,

  # ---------------------------------------------------------------------------
  # Deny sensitive paths
  # ---------------------------------------------------------------------------

  deny /etc/shadow r,
  deny /etc/passwd w,
  deny /etc/group w,
  deny /etc/gshadow r,
  deny /etc/sudoers r,
  deny /etc/sudoers.d/** r,
  deny /root/.ssh/** rwx,
  deny /root/.gnupg/** rwx,
  deny /root/.bash_history r,

  # Deny host filesystem escape
  deny /host/** rwx,
  deny /mnt/** rwx,
  deny /media/** rwx,

  # Deny kernel/module access
  deny /boot/** rwx,
  deny /lib/modules/** rwx,
  deny /usr/src/** rwx,

  # Deny Docker socket access
  deny /var/run/docker.sock rw,
  deny /run/docker.sock rw,

  # ---------------------------------------------------------------------------
  # Capabilities
  # ---------------------------------------------------------------------------

  capability net_bind_service,
  capability sys_resource,

  # Deny dangerous capabilities
  deny capability sys_admin,
  deny capability sys_module,
  deny capability sys_rawio,
  deny capability sys_ptrace,
  deny capability dac_override,
  deny capability dac_read_search,
  deny capability sys_boot,
  deny capability net_admin,
  deny capability net_raw,
}
