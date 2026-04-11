"""
tests/smoke/test_security.py — Security hardening validation for container configs.

BMTOS-50 | Epic: BMTOS-EPIC-3 (OS Foundation & Infrastructure)

Validates that Docker Compose files and security profiles satisfy the
container-security acceptance criteria without requiring a running Docker daemon.

Tests cover:
  - Per-service seccomp profiles present and structurally valid (JSON, ARM64)
  - Per-service AppArmor profiles present and contain required directives
  - Compose files reference security_opt with no-new-privileges and seccomp
  - Capability drops (cap_drop: ALL) are applied to every service
  - PID limits are set for every hardened service
  - tmpfs /tmp is configured for every hardened service
  - Secrets management: secrets volumes are mounted read-only
  - No plaintext API key environment variables in production compose
  - Dockerfile runs as non-root user

Run with:
    pytest tests/smoke/test_security.py -v
"""

import json
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.smoke, pytest.mark.security]

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SECURITY_DIR = PROJECT_ROOT / "bmt_ai_os" / "runtime" / "security"
PROD_COMPOSE = PROJECT_ROOT / "bmt_ai_os" / "ai-stack" / "docker-compose.yml"
DEV_COMPOSE = PROJECT_ROOT / "docker-compose.dev.yml"
DOCKERFILE = PROJECT_ROOT / "Dockerfile"

# Services that must be hardened in production compose
PROD_HARDENED_SERVICES = {"ollama", "chromadb"}

# Services that must be hardened in dev compose
DEV_HARDENED_SERVICES = {"ollama", "chromadb", "controller"}

# Per-service seccomp profile files expected on disk
SECCOMP_PROFILES = {
    "ollama": SECURITY_DIR / "seccomp-ollama.json",
    "chromadb": SECURITY_DIR / "seccomp-chromadb.json",
    "controller": SECURITY_DIR / "seccomp-controller.json",
}

# Per-service AppArmor profile files expected on disk
APPARMOR_PROFILES = {
    "ollama": SECURITY_DIR / "apparmor-ollama.profile",
    "chromadb": SECURITY_DIR / "apparmor-chromadb.profile",
    "controller": SECURITY_DIR / "apparmor-controller.profile",
}

# Sensitive env-var names that must NOT appear in production compose
FORBIDDEN_ENV_VARS = {
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "MISTRAL_API_KEY",
    "GROQ_API_KEY",
    "CHROMA_AUTH_CREDENTIALS",
    "CHROMA_SERVER_AUTHN_CREDENTIALS",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def prod_compose() -> dict:
    assert PROD_COMPOSE.is_file(), f"Production compose not found: {PROD_COMPOSE}"
    return yaml.safe_load(PROD_COMPOSE.read_text())


@pytest.fixture(scope="module")
def dev_compose() -> dict:
    assert DEV_COMPOSE.is_file(), f"Dev compose not found: {DEV_COMPOSE}"
    return yaml.safe_load(DEV_COMPOSE.read_text())


# ---------------------------------------------------------------------------
# Seccomp profile tests
# ---------------------------------------------------------------------------


class TestSeccompProfiles:
    """Validate per-service seccomp JSON profiles."""

    @pytest.mark.parametrize("service", sorted(SECCOMP_PROFILES))
    def test_seccomp_profile_exists(self, service):
        """Each service must have a dedicated seccomp profile file."""
        profile_path = SECCOMP_PROFILES[service]
        assert profile_path.is_file(), f"Seccomp profile for '{service}' not found: {profile_path}"

    @pytest.mark.parametrize("service", sorted(SECCOMP_PROFILES))
    def test_seccomp_profile_valid_json(self, service):
        """Seccomp profiles must be valid JSON."""
        profile_path = SECCOMP_PROFILES[service]
        if not profile_path.is_file():
            pytest.skip(f"Profile file missing: {profile_path}")
        data = json.loads(profile_path.read_text())
        assert isinstance(data, dict), f"Seccomp profile for '{service}' is not a JSON object"

    @pytest.mark.parametrize("service", sorted(SECCOMP_PROFILES))
    def test_seccomp_default_deny(self, service):
        """Seccomp profiles must use a default-deny action (SCMP_ACT_ERRNO)."""
        profile_path = SECCOMP_PROFILES[service]
        if not profile_path.is_file():
            pytest.skip(f"Profile file missing: {profile_path}")
        data = json.loads(profile_path.read_text())
        assert data.get("defaultAction") == "SCMP_ACT_ERRNO", (
            f"Seccomp profile for '{service}' does not use default-deny "
            f"(expected SCMP_ACT_ERRNO, got {data.get('defaultAction')!r})"
        )

    @pytest.mark.parametrize("service", sorted(SECCOMP_PROFILES))
    def test_seccomp_targets_aarch64(self, service):
        """Seccomp profiles must target SCMP_ARCH_AARCH64 (ARM64)."""
        profile_path = SECCOMP_PROFILES[service]
        if not profile_path.is_file():
            pytest.skip(f"Profile file missing: {profile_path}")
        data = json.loads(profile_path.read_text())
        arch_map = data.get("archMap", [])
        archs = [entry.get("architecture") for entry in arch_map]
        assert "SCMP_ARCH_AARCH64" in archs, (
            f"Seccomp profile for '{service}' does not include SCMP_ARCH_AARCH64. "
            f"Found architectures: {archs}"
        )

    @pytest.mark.parametrize("service", sorted(SECCOMP_PROFILES))
    def test_seccomp_has_allow_rules(self, service):
        """Seccomp profiles must have at least one SCMP_ACT_ALLOW rule."""
        profile_path = SECCOMP_PROFILES[service]
        if not profile_path.is_file():
            pytest.skip(f"Profile file missing: {profile_path}")
        data = json.loads(profile_path.read_text())
        allow_rules = [
            rule for rule in data.get("syscalls", []) if rule.get("action") == "SCMP_ACT_ALLOW"
        ]
        assert allow_rules, f"Seccomp profile for '{service}' has no SCMP_ACT_ALLOW rules"

    @pytest.mark.parametrize("service", sorted(SECCOMP_PROFILES))
    def test_seccomp_blocks_ptrace(self, service):
        """Seccomp profiles must block ptrace (process introspection)."""
        profile_path = SECCOMP_PROFILES[service]
        if not profile_path.is_file():
            pytest.skip(f"Profile file missing: {profile_path}")
        data = json.loads(profile_path.read_text())
        # ptrace must NOT appear in any SCMP_ACT_ALLOW rule
        for rule in data.get("syscalls", []):
            if rule.get("action") == "SCMP_ACT_ALLOW":
                allowed = rule.get("names", [])
                assert "ptrace" not in allowed, (
                    f"Seccomp profile for '{service}' allows ptrace — this must be blocked"
                )

    @pytest.mark.parametrize("service", sorted(SECCOMP_PROFILES))
    def test_seccomp_blocks_mount(self, service):
        """Seccomp profiles must block mount (filesystem namespace escapes)."""
        profile_path = SECCOMP_PROFILES[service]
        if not profile_path.is_file():
            pytest.skip(f"Profile file missing: {profile_path}")
        data = json.loads(profile_path.read_text())
        for rule in data.get("syscalls", []):
            if rule.get("action") == "SCMP_ACT_ALLOW":
                allowed = rule.get("names", [])
                assert "mount" not in allowed, (
                    f"Seccomp profile for '{service}' allows mount — this must be blocked"
                )

    @pytest.mark.parametrize("service", sorted(SECCOMP_PROFILES))
    def test_seccomp_includes_futex(self, service):
        """Seccomp profiles must allow futex (required by Python/Go threading)."""
        profile_path = SECCOMP_PROFILES[service]
        if not profile_path.is_file():
            pytest.skip(f"Profile file missing: {profile_path}")
        data = json.loads(profile_path.read_text())
        all_allowed: list[str] = []
        for rule in data.get("syscalls", []):
            if rule.get("action") == "SCMP_ACT_ALLOW":
                all_allowed.extend(rule.get("names", []))
        assert "futex" in all_allowed, (
            f"Seccomp profile for '{service}' does not allow 'futex' — "
            "Python/Go threads will deadlock without it"
        )


# ---------------------------------------------------------------------------
# AppArmor profile tests
# ---------------------------------------------------------------------------


class TestAppArmorProfiles:
    """Validate per-service AppArmor profile files."""

    @pytest.mark.parametrize("service", sorted(APPARMOR_PROFILES))
    def test_apparmor_profile_exists(self, service):
        """Each service must have a dedicated AppArmor profile file."""
        profile_path = APPARMOR_PROFILES[service]
        assert profile_path.is_file(), f"AppArmor profile for '{service}' not found: {profile_path}"

    @pytest.mark.parametrize("service", sorted(APPARMOR_PROFILES))
    def test_apparmor_profile_name_matches(self, service):
        """AppArmor profile file must declare the expected bmt-<service> profile name."""
        profile_path = APPARMOR_PROFILES[service]
        if not profile_path.is_file():
            pytest.skip(f"Profile file missing: {profile_path}")
        content = profile_path.read_text()
        expected_name = f"bmt-{service}"
        assert f"profile {expected_name}" in content, (
            f"AppArmor profile for '{service}' does not declare 'profile {expected_name}'"
        )

    @pytest.mark.parametrize("service", sorted(APPARMOR_PROFILES))
    def test_apparmor_denies_docker_socket(self, service):
        """
        AppArmor profile for Ollama and ChromaDB must deny Docker socket access.
        The controller is the only service permitted Docker socket access.
        """
        if service == "controller":
            pytest.skip("Controller is permitted Docker socket access by design")
        profile_path = APPARMOR_PROFILES[service]
        if not profile_path.is_file():
            pytest.skip(f"Profile file missing: {profile_path}")
        content = profile_path.read_text()
        assert "deny /var/run/docker.sock" in content or "deny /run/docker.sock" in content, (
            f"AppArmor profile for '{service}' does not deny Docker socket access"
        )

    @pytest.mark.parametrize("service", sorted(APPARMOR_PROFILES))
    def test_apparmor_denies_shadow(self, service):
        """AppArmor profiles must deny read access to /etc/shadow."""
        profile_path = APPARMOR_PROFILES[service]
        if not profile_path.is_file():
            pytest.skip(f"Profile file missing: {profile_path}")
        content = profile_path.read_text()
        assert "deny /etc/shadow" in content, (
            f"AppArmor profile for '{service}' does not deny /etc/shadow"
        )

    @pytest.mark.parametrize("service", sorted(APPARMOR_PROFILES))
    def test_apparmor_denies_kernel_modules(self, service):
        """AppArmor profiles must deny kernel module loading paths."""
        profile_path = APPARMOR_PROFILES[service]
        if not profile_path.is_file():
            pytest.skip(f"Profile file missing: {profile_path}")
        content = profile_path.read_text()
        assert "deny /boot/" in content or "deny /lib/modules/" in content, (
            f"AppArmor profile for '{service}' does not deny kernel/module paths"
        )

    @pytest.mark.parametrize("service", sorted(APPARMOR_PROFILES))
    def test_apparmor_denies_sys_admin_capability(self, service):
        """AppArmor profiles must deny the sys_admin capability."""
        profile_path = APPARMOR_PROFILES[service]
        if not profile_path.is_file():
            pytest.skip(f"Profile file missing: {profile_path}")
        content = profile_path.read_text()
        assert "deny capability sys_admin" in content, (
            f"AppArmor profile for '{service}' does not deny capability sys_admin"
        )

    @pytest.mark.parametrize("service", sorted(APPARMOR_PROFILES))
    def test_apparmor_allows_secrets_mount(self, service):
        """AppArmor profiles must allow reading from /run/secrets (secret file mounts)."""
        profile_path = APPARMOR_PROFILES[service]
        if not profile_path.is_file():
            pytest.skip(f"Profile file missing: {profile_path}")
        content = profile_path.read_text()
        assert "/run/secrets/" in content, (
            f"AppArmor profile for '{service}' does not reference /run/secrets — "
            "secrets file mounts will be blocked"
        )


# ---------------------------------------------------------------------------
# Production compose security tests
# ---------------------------------------------------------------------------


class TestProductionComposeSecurity:
    """Validate security hardening in the production compose file."""

    @pytest.mark.parametrize("service", sorted(PROD_HARDENED_SERVICES))
    def test_no_new_privileges(self, prod_compose, service):
        """Every hardened service must set no-new-privileges:true."""
        svc = prod_compose["services"].get(service, {})
        security_opt = svc.get("security_opt", [])
        assert "no-new-privileges:true" in security_opt, (
            f"Production service '{service}' missing no-new-privileges:true in security_opt"
        )

    @pytest.mark.parametrize("service", sorted(PROD_HARDENED_SERVICES))
    def test_seccomp_referenced(self, prod_compose, service):
        """Every hardened service must reference a seccomp profile."""
        svc = prod_compose["services"].get(service, {})
        security_opt = svc.get("security_opt", [])
        seccomp_entries = [opt for opt in security_opt if opt.startswith("seccomp=")]
        assert seccomp_entries, (
            f"Production service '{service}' has no seccomp= entry in security_opt"
        )

    @pytest.mark.parametrize("service", sorted(PROD_HARDENED_SERVICES))
    def test_cap_drop_all(self, prod_compose, service):
        """Every hardened service must drop all capabilities."""
        svc = prod_compose["services"].get(service, {})
        cap_drop = [c.upper() for c in svc.get("cap_drop", [])]
        assert "ALL" in cap_drop, f"Production service '{service}' does not have cap_drop: [ALL]"

    @pytest.mark.parametrize("service", sorted(PROD_HARDENED_SERVICES))
    def test_pids_limit_set(self, prod_compose, service):
        """
        Every hardened service must have a PID limit to prevent fork bombs.
        Accepts either top-level pids_limit or deploy.resources.limits.pids
        (they cannot coexist in the same service definition).
        """
        svc = prod_compose["services"].get(service, {})
        # Top-level pids_limit (simple form)
        pids_limit = svc.get("pids_limit")
        # Or nested under deploy.resources.limits.pids (used when deploy block exists)
        deploy_pids = svc.get("deploy", {}).get("resources", {}).get("limits", {}).get("pids")
        effective_limit = pids_limit if pids_limit is not None else deploy_pids
        assert effective_limit is not None, (
            f"Production service '{service}' has no PID limit set "
            "(set pids_limit or deploy.resources.limits.pids)"
        )
        assert isinstance(effective_limit, int) and effective_limit > 0, (
            f"Production service '{service}' PID limit must be a positive integer, "
            f"got {effective_limit!r}"
        )

    @pytest.mark.parametrize("service", sorted(PROD_HARDENED_SERVICES))
    def test_tmpfs_tmp_configured(self, prod_compose, service):
        """Every hardened service must mount /tmp as tmpfs (noexec, nosuid)."""
        svc = prod_compose["services"].get(service, {})
        tmpfs = svc.get("tmpfs", [])
        tmp_entries = [t for t in tmpfs if t.startswith("/tmp")]
        assert tmp_entries, f"Production service '{service}' has no tmpfs /tmp configured"
        tmp_entry = tmp_entries[0]
        assert "noexec" in tmp_entry, (
            f"Production service '{service}' tmpfs /tmp is missing noexec flag"
        )
        assert "nosuid" in tmp_entry, (
            f"Production service '{service}' tmpfs /tmp is missing nosuid flag"
        )

    @pytest.mark.parametrize("service", sorted(PROD_HARDENED_SERVICES))
    def test_secrets_mounted_readonly(self, prod_compose, service):
        """Sensitive services must mount secrets as read-only volumes."""
        svc = prod_compose["services"].get(service, {})
        volumes = svc.get("volumes", [])
        # Look for a secrets volume mount (either bind or named volume at /run/secrets)
        secrets_mounts = [v for v in volumes if "secrets" in str(v) and "run/secrets" in str(v)]
        assert secrets_mounts, (
            f"Production service '{service}' has no /run/secrets volume mount. "
            "Secrets should be injected via file mounts, not env vars."
        )
        # Verify it is read-only
        for mount in secrets_mounts:
            assert ":ro" in str(mount), (
                f"Production service '{service}' secrets mount '{mount}' is not read-only (:ro)"
            )

    def test_no_plaintext_api_keys_in_environment(self, prod_compose):
        """
        Production compose must not pass API keys as plain environment variables.
        Secrets must be injected via /run/secrets file mounts instead.
        """
        for service_name, service_def in prod_compose.get("services", {}).items():
            env_entries = service_def.get("environment", [])
            # environment can be a list of "KEY=VALUE" or a dict
            if isinstance(env_entries, list):
                for entry in env_entries:
                    key = entry.split("=")[0].strip() if "=" in entry else entry.strip()
                    assert key not in FORBIDDEN_ENV_VARS, (
                        f"Service '{service_name}' exposes secret key '{key}' as "
                        "environment variable — use /run/secrets file mounts instead"
                    )
            elif isinstance(env_entries, dict):
                for key in env_entries:
                    assert key not in FORBIDDEN_ENV_VARS, (
                        f"Service '{service_name}' exposes secret key '{key}' as "
                        "environment variable — use /run/secrets file mounts instead"
                    )


# ---------------------------------------------------------------------------
# Dev compose security tests
# ---------------------------------------------------------------------------


class TestDevComposeSecurity:
    """Validate that dev compose also applies baseline security hardening."""

    @pytest.mark.parametrize("service", sorted(DEV_HARDENED_SERVICES))
    def test_no_new_privileges_dev(self, dev_compose, service):
        """Every hardened dev service must set no-new-privileges:true."""
        svc = dev_compose["services"].get(service, {})
        security_opt = svc.get("security_opt", [])
        assert "no-new-privileges:true" in security_opt, (
            f"Dev service '{service}' missing no-new-privileges:true in security_opt"
        )

    @pytest.mark.parametrize("service", sorted(DEV_HARDENED_SERVICES))
    def test_cap_drop_all_dev(self, dev_compose, service):
        """Every hardened dev service must drop all capabilities."""
        svc = dev_compose["services"].get(service, {})
        cap_drop = [c.upper() for c in svc.get("cap_drop", [])]
        assert "ALL" in cap_drop, f"Dev service '{service}' does not have cap_drop: [ALL]"

    @pytest.mark.parametrize("service", sorted(DEV_HARDENED_SERVICES))
    def test_pids_limit_dev(self, dev_compose, service):
        """Every hardened dev service must have a PID limit."""
        svc = dev_compose["services"].get(service, {})
        pids_limit = svc.get("pids_limit")
        assert pids_limit is not None, f"Dev service '{service}' has no pids_limit set"

    @pytest.mark.parametrize("service", sorted(DEV_HARDENED_SERVICES))
    def test_seccomp_referenced_dev(self, dev_compose, service):
        """Every hardened dev service must reference a seccomp profile."""
        svc = dev_compose["services"].get(service, {})
        security_opt = svc.get("security_opt", [])
        seccomp_entries = [opt for opt in security_opt if opt.startswith("seccomp=")]
        assert seccomp_entries, f"Dev service '{service}' has no seccomp= entry in security_opt"


# ---------------------------------------------------------------------------
# Dockerfile security tests
# ---------------------------------------------------------------------------


class TestDockerfileSecurity:
    """Validate Dockerfile security best practices."""

    def test_dockerfile_exists(self):
        """Dockerfile must exist at project root."""
        assert DOCKERFILE.is_file(), f"Dockerfile not found: {DOCKERFILE}"

    def test_dockerfile_runs_as_nonroot(self):
        """
        Dockerfile must specify a non-root USER.
        Running as root inside a container expands the blast radius of any
        container escape vulnerability.
        """
        content = DOCKERFILE.read_text()
        lines = content.splitlines()
        user_directives = [ln.strip() for ln in lines if ln.strip().upper().startswith("USER ")]
        assert user_directives, "Dockerfile has no USER directive — container runs as root"
        # The final USER directive must not be root
        final_user = user_directives[-1].split(None, 1)[1].strip()
        assert final_user not in ("root", "0", "0:0", "root:root"), (
            f"Dockerfile final USER is '{final_user}' — must be a non-root user"
        )

    def test_dockerfile_exposes_only_expected_port(self):
        """Dockerfile must expose only the controller API port (8080)."""
        content = DOCKERFILE.read_text()
        lines = content.splitlines()
        expose_lines = [ln.strip() for ln in lines if ln.strip().upper().startswith("EXPOSE ")]
        exposed_ports = set()
        for line in expose_lines:
            parts = line.split()[1:]
            for port in parts:
                exposed_ports.add(port.split("/")[0])
        assert exposed_ports == {"8080"}, (
            f"Dockerfile exposes unexpected ports: {exposed_ports} (expected only 8080)"
        )


# ---------------------------------------------------------------------------
# Security profile completeness tests
# ---------------------------------------------------------------------------


class TestSecurityProfileCompleteness:
    """Verify that all expected security files are present and non-empty."""

    def test_seccomp_default_profile_exists(self):
        """The default seccomp profile (base for all services) must exist."""
        default_path = SECURITY_DIR / "seccomp-default.json"
        assert default_path.is_file(), f"Default seccomp profile not found: {default_path}"
        data = json.loads(default_path.read_text())
        assert data.get("syscalls"), "Default seccomp profile has no syscall rules"

    def test_container_security_overlay_exists(self):
        """The container-security.yml Compose overlay must exist."""
        overlay = SECURITY_DIR / "container-security.yml"
        assert overlay.is_file(), f"container-security.yml not found: {overlay}"

    def test_container_security_overlay_covers_all_services(self):
        """container-security.yml must define hardening for all three services."""
        overlay = SECURITY_DIR / "container-security.yml"
        if not overlay.is_file():
            pytest.skip("container-security.yml not found")
        data = yaml.safe_load(overlay.read_text())
        services = set(data.get("services", {}).keys())
        required = {"ollama", "chromadb", "controller"}
        missing = required - services
        assert not missing, f"container-security.yml is missing hardening for services: {missing}"

    def test_secrets_manager_script_exists(self):
        """The secrets-manager.sh script must exist."""
        script = SECURITY_DIR / "secrets-manager.sh"
        assert script.is_file(), f"secrets-manager.sh not found: {script}"

    def test_secrets_manager_handles_controller_service(self):
        """secrets-manager.sh must recognise 'controller' as a valid service."""
        script = SECURITY_DIR / "secrets-manager.sh"
        if not script.is_file():
            pytest.skip("secrets-manager.sh not found")
        content = script.read_text()
        assert "controller)" in content, (
            "secrets-manager.sh does not handle the 'controller' service"
        )
