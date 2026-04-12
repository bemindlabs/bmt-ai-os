"""DLC build profiles — combine hardware target + tool packages + tier into a build manifest."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bmt_ai_os.dlc.registry import PackageRegistry

_PROFILES_DIR = Path("/data/bmt_ai_os/dlc/profiles")


@dataclass
class BuildProfile:
    id: str
    name: str
    target: str
    tier: str
    packages: list[str]
    description: str = ""
    preset: str | None = None
    custom_options: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def to_build_manifest(self, registry: PackageRegistry) -> dict[str, Any]:
        """Generate a build manifest JSON consumed by scripts/build.sh --profile."""
        resolved = registry.resolve_dependencies(self.packages)
        target = registry.get_target(self.target)
        tier = registry.get_tier(self.tier)

        buildroot_packages: list[str] = []
        container_images: list[str] = []
        install_commands: list[str] = []
        ports: list[int] = []

        for pid in resolved:
            pkg = registry.get_package(pid)
            if not pkg:
                continue
            buildroot_packages.extend(pkg.buildroot_packages)
            if pkg.container_image:
                container_images.append(pkg.container_image)
            if pkg.install_command:
                install_commands.append(pkg.install_command)
            ports.extend(pkg.ports)

        return {
            "profile_id": self.id,
            "profile_name": self.name,
            "target": self.target,
            "tier": self.tier,
            "target_specs": asdict(target) if target else {},
            "tier_specs": asdict(tier) if tier else {},
            "packages": resolved,
            "buildroot_packages": sorted(set(buildroot_packages)),
            "container_images": container_images,
            "install_commands": install_commands,
            "ports": sorted(set(ports)),
            "estimated_size_mb": registry.estimate_image_size_mb(resolved),
            "custom_options": self.custom_options,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


class ProfileManager:
    """Manages build profiles on disk."""

    def __init__(self, profiles_dir: str | Path | None = None) -> None:
        self._dir = Path(profiles_dir) if profiles_dir else _PROFILES_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, profile_id: str) -> Path:
        return self._dir / f"{profile_id}.json"

    def list_profiles(self) -> list[BuildProfile]:
        profiles: list[BuildProfile] = []
        for f in sorted(self._dir.glob("*.json")):
            try:
                data = json.loads(f.read_text())
                profiles.append(BuildProfile(**data))
            except (json.JSONDecodeError, TypeError):
                continue
        return profiles

    def get_profile(self, profile_id: str) -> BuildProfile | None:
        path = self._path(profile_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return BuildProfile(**data)
        except (json.JSONDecodeError, TypeError):
            return None

    def save_profile(self, profile: BuildProfile) -> BuildProfile:
        if not profile.id:
            profile.id = uuid.uuid4().hex[:12]
        profile.updated_at = datetime.now(timezone.utc).isoformat()
        self._path(profile.id).write_text(json.dumps(asdict(profile), indent=2) + "\n")
        return profile

    def delete_profile(self, profile_id: str) -> bool:
        path = self._path(profile_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def create_from_preset(
        self,
        preset_id: str,
        target: str,
        tier: str,
        registry: PackageRegistry,
        name: str | None = None,
    ) -> BuildProfile | None:
        preset = registry.get_preset(preset_id)
        if not preset:
            return None
        profile = BuildProfile(
            id=uuid.uuid4().hex[:12],
            name=name or f"{preset.name} — {target}",
            target=target,
            tier=tier,
            packages=list(preset.packages),
            preset=preset_id,
            description=preset.description,
        )
        return self.save_profile(profile)

    def export_build_manifest(
        self, profile_id: str, registry: PackageRegistry, output_path: Path | None = None
    ) -> Path | None:
        profile = self.get_profile(profile_id)
        if not profile:
            return None
        manifest = profile.to_build_manifest(registry)
        if output_path is None:
            output_path = self._dir.parent / "manifests" / f"{profile_id}.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(manifest, indent=2) + "\n")
        return output_path
