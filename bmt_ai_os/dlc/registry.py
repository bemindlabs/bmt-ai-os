"""DLC package registry — loads and queries tool packages from packages.yml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_PACKAGES_YML = Path(__file__).parent / "packages.yml"


@dataclass
class HardwareRequirements:
    min_ram_gb: int = 0
    gpu_recommended: bool = False


@dataclass
class ToolPackage:
    id: str
    name: str
    description: str
    category: str
    size_mb: int
    arm64: bool
    required: bool = False
    tier_minimum: str = "lite"
    container_image: str | None = None
    buildroot_packages: list[str] = field(default_factory=list)
    install_command: str | None = None
    dependencies: list[str] = field(default_factory=list)
    ports: list[int] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    env_vars: dict[str, str] = field(default_factory=dict)
    hardware_requirements: HardwareRequirements = field(default_factory=HardwareRequirements)


@dataclass
class HardwareTarget:
    id: str
    name: str
    description: str
    arch: str
    accelerator: str
    default_tier: str
    image_format: str
    min_storage_gb: int
    specs: dict[str, str] = field(default_factory=dict)


@dataclass
class DeviceTier:
    id: str
    name: str
    description: str
    min_ram_gb: int
    max_ram_gb: int
    default_model: str
    max_image_size_gb: int


@dataclass
class Preset:
    id: str
    name: str
    description: str
    packages: list[str]


class PackageRegistry:
    """Loads and queries the DLC package registry."""

    def __init__(self, path: str | Path | None = None) -> None:
        path = Path(path) if path else _PACKAGES_YML
        with open(path) as f:
            data = yaml.safe_load(f)

        self._packages: dict[str, ToolPackage] = {}
        for p in data.get("packages", []):
            hw = p.pop("hardware_requirements", {})
            pkg = ToolPackage(
                **{k: v for k, v in p.items() if k != "hardware_requirements"},
                hardware_requirements=HardwareRequirements(**hw) if hw else HardwareRequirements(),
            )
            self._packages[pkg.id] = pkg

        self._targets: dict[str, HardwareTarget] = {}
        for t in data.get("targets", []):
            target = HardwareTarget(**t)
            self._targets[target.id] = target

        self._tiers: dict[str, DeviceTier] = {}
        for t in data.get("tiers", []):
            tier = DeviceTier(**t)
            self._tiers[tier.id] = tier

        self._presets: dict[str, Preset] = {}
        for p in data.get("presets", []):
            preset = Preset(**p)
            self._presets[preset.id] = preset

    # ── Packages ─────────────────────────────────────────────────────────────

    def list_packages(self, category: str | None = None) -> list[ToolPackage]:
        pkgs = list(self._packages.values())
        if category:
            pkgs = [p for p in pkgs if p.category == category]
        return pkgs

    def get_package(self, package_id: str) -> ToolPackage | None:
        return self._packages.get(package_id)

    def get_required_packages(self) -> list[ToolPackage]:
        return [p for p in self._packages.values() if p.required]

    def get_packages_for_tier(self, tier_id: str) -> list[ToolPackage]:
        tier_order = ["lite", "standard", "full"]
        if tier_id not in tier_order:
            return []
        max_idx = tier_order.index(tier_id)
        return [p for p in self._packages.values() if tier_order.index(p.tier_minimum) <= max_idx]

    def get_categories(self) -> list[str]:
        return sorted({p.category for p in self._packages.values()})

    # ── Targets ──────────────────────────────────────────────────────────────

    def list_targets(self) -> list[HardwareTarget]:
        return list(self._targets.values())

    def get_target(self, target_id: str) -> HardwareTarget | None:
        return self._targets.get(target_id)

    # ── Tiers ────────────────────────────────────────────────────────────────

    def list_tiers(self) -> list[DeviceTier]:
        return list(self._tiers.values())

    def get_tier(self, tier_id: str) -> DeviceTier | None:
        return self._tiers.get(tier_id)

    # ── Presets ──────────────────────────────────────────────────────────────

    def list_presets(self) -> list[Preset]:
        return list(self._presets.values())

    def get_preset(self, preset_id: str) -> Preset | None:
        return self._presets.get(preset_id)

    # ── Validation ───────────────────────────────────────────────────────────

    def resolve_dependencies(self, package_ids: list[str]) -> list[str]:
        """Return package_ids with all transitive dependencies included."""
        resolved: list[str] = []
        seen: set[str] = set()

        def _resolve(pid: str) -> None:
            if pid in seen:
                return
            seen.add(pid)
            pkg = self._packages.get(pid)
            if not pkg:
                return
            for dep in pkg.dependencies:
                _resolve(dep)
            resolved.append(pid)

        # Always include required packages
        for pkg in self.get_required_packages():
            _resolve(pkg.id)
        for pid in package_ids:
            _resolve(pid)
        return resolved

    def estimate_image_size_mb(self, package_ids: list[str]) -> int:
        """Estimate total image size in MB for selected packages."""
        base_size = 200  # Base OS (kernel, init, filesystem)
        total = base_size
        for pid in package_ids:
            pkg = self._packages.get(pid)
            if pkg:
                total += pkg.size_mb
        return total

    def validate_packages_for_target(
        self, package_ids: list[str], target_id: str, tier_id: str
    ) -> list[str]:
        """Return list of validation warnings for the given selection."""
        warnings: list[str] = []
        target = self._targets.get(target_id)
        tier = self._tiers.get(tier_id)

        if not target:
            warnings.append(f"Unknown hardware target: {target_id}")
            return warnings
        if not tier:
            warnings.append(f"Unknown device tier: {tier_id}")
            return warnings

        for pid in package_ids:
            pkg = self._packages.get(pid)
            if not pkg:
                warnings.append(f"Unknown package: {pid}")
                continue
            if not pkg.arm64 and target.arch == "aarch64":
                warnings.append(f"{pkg.name} is not ARM64 compatible")
            if pkg.hardware_requirements.gpu_recommended and target.accelerator == "cpu":
                warnings.append(f"{pkg.name} recommends GPU but {target.name} is CPU-only")
            if pkg.hardware_requirements.min_ram_gb > tier.max_ram_gb:
                warnings.append(
                    f"{pkg.name} needs {pkg.hardware_requirements.min_ram_gb}GB RAM "
                    f"but {tier.name} tier max is {tier.max_ram_gb}GB"
                )

        est_mb = self.estimate_image_size_mb(package_ids)
        est_gb = est_mb / 1024
        if est_gb > tier.max_image_size_gb:
            warnings.append(
                f"Estimated image size ({est_gb:.1f}GB) exceeds "
                f"{tier.name} tier limit ({tier.max_image_size_gb}GB)"
            )

        return warnings

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full registry for API responses."""
        return {
            "packages": [
                {
                    "id": p.id,
                    "name": p.name,
                    "description": p.description,
                    "category": p.category,
                    "size_mb": p.size_mb,
                    "arm64": p.arm64,
                    "required": p.required,
                    "tier_minimum": p.tier_minimum,
                    "dependencies": p.dependencies,
                    "ports": p.ports,
                    "tags": p.tags,
                }
                for p in self._packages.values()
            ],
            "targets": [
                {
                    "id": t.id,
                    "name": t.name,
                    "description": t.description,
                    "arch": t.arch,
                    "accelerator": t.accelerator,
                    "default_tier": t.default_tier,
                    "image_format": t.image_format,
                    "min_storage_gb": t.min_storage_gb,
                    "specs": t.specs,
                }
                for t in self._targets.values()
            ],
            "tiers": [
                {
                    "id": t.id,
                    "name": t.name,
                    "description": t.description,
                    "min_ram_gb": t.min_ram_gb,
                    "max_ram_gb": t.max_ram_gb,
                    "default_model": t.default_model,
                    "max_image_size_gb": t.max_image_size_gb,
                }
                for t in self._tiers.values()
            ],
            "presets": [
                {
                    "id": p.id,
                    "name": p.name,
                    "description": p.description,
                    "packages": p.packages,
                }
                for p in self._presets.values()
            ],
        }
