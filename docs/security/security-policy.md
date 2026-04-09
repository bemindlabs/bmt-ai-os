# BMT AI OS — Security Policy

BMTOS-21 | Epic: BMTOS-EPIC-3 (OS Foundation & Infrastructure)

## 1. Container Isolation Model

All AI-stack containers run under a hardened security posture. The security
overlay (`bmt-ai-os/runtime/security/container-security.yml`) is applied on
top of the base Docker Compose file.

### 1.1 Non-Root Execution

Containers run as UID 1000 (non-root) wherever possible. This limits the
blast radius of any container escape. Named volumes are pre-initialized
with correct ownership.

### 1.2 Capability Matrix

| Service  | Capabilities                    | Rationale                              |
|----------|---------------------------------|----------------------------------------|
| Ollama   | NET_BIND_SERVICE, SYS_RESOURCE  | Network listen + mmap for large models |
| ChromaDB | NET_BIND_SERVICE                | Network listen only                    |

All other capabilities are dropped via `cap_drop: ALL`.

### 1.3 Filesystem Restrictions

| Service  | Root FS    | tmpfs  | Notes                                 |
|----------|------------|--------|---------------------------------------|
| Ollama   | Read-write | /tmp   | Needs rw for model cache under volume |
| ChromaDB | Read-only  | /tmp   | Data on named volume, rootfs locked   |

### 1.4 Privilege Escalation Prevention

- `no-new-privileges:true` on all containers
- Custom seccomp profile blocks `ptrace`, `mount`, `keyctl`, and other
  dangerous syscalls
- PID limits prevent fork bombs (256 for Ollama, 128 for ChromaDB)

### 1.5 AppArmor

An AppArmor profile (`apparmor-ollama.profile`) restricts Ollama's file
access to model directories and runtime paths, denying access to sensitive
files (`/etc/shadow`, `/root/.ssh/`, Docker socket, etc.).

## 2. Secrets Management

### 2.1 Storage

Secrets are stored as individual files under `/etc/bmt-ai-os/secrets/`:

```
/etc/bmt-ai-os/secrets/          (0700 root:root)
  OPENAI_API_KEY                  (0600 root:root)
  ANTHROPIC_API_KEY               (0600 root:root)
  GOOGLE_API_KEY                  (0600 root:root)
  MISTRAL_API_KEY                 (0600 root:root)
  GROQ_API_KEY                    (0600 root:root)
  CHROMA_AUTH_CREDENTIALS         (0600 root:root)
  ollama/                         (0700 root:root)  <- mount dir
  chromadb/                       (0700 root:root)  <- mount dir
  .archive/                       (0700 root:root)  <- rotated secrets
```

### 2.2 Injection

Secrets are **never** passed as environment variables. They are:

1. Written to `/etc/bmt-ai-os/secrets/<KEY>` via `secrets-manager.sh set`
2. Copied to per-service directories via `secrets-manager.sh inject`
3. Bind-mounted into containers at `/run/secrets/` (read-only)
4. Read by application code from the filesystem

This approach prevents secrets from appearing in `docker inspect` output,
`/proc/*/environ`, or container logs.

### 2.3 Rotation

```bash
sudo secrets-manager.sh rotate OPENAI_API_KEY
# Archives old value to /etc/bmt-ai-os/secrets/.archive/OPENAI_API_KEY.<timestamp>
sudo secrets-manager.sh set OPENAI_API_KEY sk-new-key-here
sudo secrets-manager.sh inject ollama
docker compose restart ollama
```

### 2.4 Supported Keys

- `OPENAI_API_KEY` -- OpenAI API access
- `ANTHROPIC_API_KEY` -- Anthropic Claude API access
- `GOOGLE_API_KEY` -- Google AI (Gemini) API access
- `MISTRAL_API_KEY` -- Mistral AI API access
- `GROQ_API_KEY` -- Groq inference API access
- `CHROMA_AUTH_CREDENTIALS` -- ChromaDB authentication token

## 3. Network Security

### 3.1 Isolated Bridge Network

All AI-stack containers communicate over the `bmt-ai-net` bridge network.
Inter-container traffic is isolated from the host network and other Docker
networks.

### 3.2 Port Exposure

Only required ports are published to the host:

| Port  | Service  | Protocol |
|-------|----------|----------|
| 11434 | Ollama   | TCP      |
| 8000  | ChromaDB | TCP      |

In production, bind ports to `127.0.0.1` to prevent external access:

```yaml
ports:
  - "127.0.0.1:11434:11434"
```

### 3.3 DNS

Containers use Docker's embedded DNS for service discovery. No external DNS
queries are needed for inter-service communication.

## 4. Seccomp Profile

The custom seccomp profile (`seccomp-default.json`) targets ARM64
(SCMP_ARCH_AARCH64) with a default-deny policy:

- **Allowed:** Standard POSIX syscalls, networking, file I/O, threading
- **Blocked:** `ptrace`, `mount`, `umount`, `keyctl`, `kexec_load`,
  `bpf`, `reboot`, `swapon/swapoff`, kernel module loading, namespace
  manipulation

## 5. Image Security

### 5.1 No Hardcoded Credentials

- No secrets are baked into container images
- All credentials are injected at runtime via file mounts
- CI/CD pipelines must scan images for leaked secrets before pushing

### 5.2 Image Provenance

- Use pinned image tags (e.g., `ollama/ollama:0.6.2`, not `:latest`)
- Verify image digests for production deployments
- Pull images only from trusted registries

## 6. Update and Patching Policy

### 6.1 Container Images

- Check for security updates weekly
- Apply critical CVE patches within 48 hours
- Test updated images on staging before production rollout
- Keep one previous image version for rollback

### 6.2 Host OS

- Alpine/Buildroot base receives security patches via automated builds
- Kernel updates follow the same test-then-deploy cycle
- `apk upgrade` (Alpine) or rootfs rebuild (Buildroot) for host packages

## 7. Incident Response

### 7.1 Detection

- Monitor container logs for authentication failures
- Alert on unexpected container restarts or resource spikes
- Check seccomp audit logs for blocked syscall attempts

### 7.2 Containment

1. Isolate affected container: `docker network disconnect bmt-ai-net <container>`
2. Capture forensic data: `docker logs <container> > incident.log`
3. Stop the container: `docker stop <container>`

### 7.3 Recovery

1. Rotate all secrets: `sudo secrets-manager.sh rotate <KEY>` for each key
2. Rebuild container from clean image
3. Review and tighten security policies as needed
4. Document findings in post-incident review

### 7.4 Reporting

Security incidents should be reported to the BMT AI OS maintainers via
the project's security advisory process (GitHub Security Advisories).
