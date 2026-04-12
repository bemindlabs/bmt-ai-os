"""DLC image CLI — `bmt-ai-os image` command group.

Provides subcommands for configuring, building, and inspecting
DLC (Downloadable Content) OS image profiles.

Commands
--------
  configure      Interactive wizard to create a new build profile.
  build          Build the OS image from a saved profile.
  list-packages  List all available tool packages (optionally filtered).
  list-profiles  List saved build profiles.
"""

from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import click

from bmt_ai_os.dlc.profiles import BuildProfile, ProfileManager
from bmt_ai_os.dlc.registry import PackageRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REGISTRY_PATH: Path | None = None  # None → default packages.yml
_PROFILES_DIR: Path | None = None  # None → default /data/…


def _registry() -> PackageRegistry:
    return PackageRegistry(_REGISTRY_PATH)


def _manager() -> ProfileManager:
    return ProfileManager(_PROFILES_DIR)


def _fmt_col(value: str, width: int) -> str:
    """Left-justify *value* in a column of *width* characters."""
    return value.ljust(width)


def _separator(widths: list[int]) -> str:
    return "  ".join("-" * w for w in widths)


def _echo_header(title: str) -> None:
    click.echo(f"\n{title}")
    click.echo("=" * len(title))


def _size_label(size_mb: int) -> str:
    if size_mb >= 1024:
        return f"{size_mb / 1024:.1f} GB"
    return f"{size_mb} MB"


# ---------------------------------------------------------------------------
# image group
# ---------------------------------------------------------------------------


@click.group("image")
def image() -> None:
    """Configure and build DLC OS images."""


# ---------------------------------------------------------------------------
# configure — interactive wizard
# ---------------------------------------------------------------------------


@image.command("configure")
@click.option("--name", "-n", default=None, help="Profile name (prompted if omitted).")
@click.option(
    "--preset",
    "-p",
    default=None,
    help="Start from a preset instead of selecting packages manually.",
)
def configure(name: str | None, preset: str | None) -> None:
    """Interactive wizard: select hardware target, tier, and packages."""

    reg = _registry()
    mgr = _manager()

    click.echo("")
    click.echo("BMT AI OS — DLC Image Configuration Wizard")
    click.echo("=" * 46)

    # ── Step 1: Hardware target ───────────────────────────────────────────────

    _echo_header("Step 1 — Hardware Target")
    targets = reg.list_targets()
    if not targets:
        click.echo("Error: no hardware targets found in registry.", err=True)
        sys.exit(1)

    col_w = [22, 10, 12, 40]
    click.echo(
        "  "
        + "  ".join(
            [
                _fmt_col("ID", col_w[0]),
                _fmt_col("ARCH", col_w[1]),
                _fmt_col("ACCEL", col_w[2]),
                _fmt_col("DESCRIPTION", col_w[3]),
            ]
        )
    )
    click.echo("  " + _separator(col_w))
    for t in targets:
        click.echo(
            "  "
            + "  ".join(
                [
                    _fmt_col(t.id, col_w[0]),
                    _fmt_col(t.arch, col_w[1]),
                    _fmt_col(t.accelerator, col_w[2]),
                    _fmt_col(t.description, col_w[3]),
                ]
            )
        )

    target_ids = [t.id for t in targets]
    target_id: str = click.prompt(
        "\nHardware target",
        type=click.Choice(target_ids, case_sensitive=False),
    )
    selected_target = reg.get_target(target_id)

    # ── Step 2: Device tier ───────────────────────────────────────────────────

    _echo_header("Step 2 — Device Tier")
    tiers = reg.list_tiers()
    if not tiers:
        click.echo("Error: no device tiers found in registry.", err=True)
        sys.exit(1)

    col_w2 = [12, 20, 14, 14, 12]
    click.echo(
        "  "
        + "  ".join(
            [
                _fmt_col("ID", col_w2[0]),
                _fmt_col("NAME", col_w2[1]),
                _fmt_col("RAM RANGE", col_w2[2]),
                _fmt_col("MAX IMAGE", col_w2[3]),
                _fmt_col("DEFAULT MODEL", col_w2[4]),
            ]
        )
    )
    click.echo("  " + _separator(col_w2))
    for t in tiers:
        ram_range = f"{t.min_ram_gb}–{t.max_ram_gb} GB"
        click.echo(
            "  "
            + "  ".join(
                [
                    _fmt_col(t.id, col_w2[0]),
                    _fmt_col(t.name, col_w2[1]),
                    _fmt_col(ram_range, col_w2[2]),
                    _fmt_col(f"{t.max_image_size_gb} GB", col_w2[3]),
                    _fmt_col(t.default_model, col_w2[4]),
                ]
            )
        )

    default_tier = selected_target.default_tier if selected_target else tiers[0].id
    tier_ids = [t.id for t in tiers]
    tier_id: str = click.prompt(
        "\nDevice tier",
        type=click.Choice(tier_ids, case_sensitive=False),
        default=default_tier,
    )

    # ── Step 3: Package selection ─────────────────────────────────────────────

    _echo_header("Step 3 — Package Selection")

    presets = reg.list_presets()
    categories = reg.get_categories()

    # Show available presets
    if presets:
        click.echo("\nAvailable presets (enter preset ID to load one):")
        col_wp = [20, 28, 46]
        click.echo(
            "  "
            + "  ".join(
                [
                    _fmt_col("PRESET ID", col_wp[0]),
                    _fmt_col("NAME", col_wp[1]),
                    _fmt_col("DESCRIPTION", col_wp[2]),
                ]
            )
        )
        click.echo("  " + _separator(col_wp))
        for p in presets:
            click.echo(
                "  "
                + "  ".join(
                    [
                        _fmt_col(p.id, col_wp[0]),
                        _fmt_col(p.name, col_wp[1]),
                        _fmt_col(p.description, col_wp[2]),
                    ]
                )
            )

    # Show all packages grouped by category
    click.echo("\nAvailable packages:")
    col_wk = [26, 10, 10, 50]
    for cat in categories:
        pkgs = reg.list_packages(category=cat)
        click.echo(f"\n  [{cat.upper()}]")
        click.echo(
            "    "
            + "  ".join(
                [
                    _fmt_col("ID", col_wk[0]),
                    _fmt_col("SIZE", col_wk[1]),
                    _fmt_col("TIER MIN", col_wk[2]),
                    _fmt_col("DESCRIPTION", col_wk[3]),
                ]
            )
        )
        click.echo("    " + _separator(col_wk))
        for pkg in pkgs:
            req_marker = " *" if pkg.required else ""
            click.echo(
                "    "
                + "  ".join(
                    [
                        _fmt_col(pkg.id + req_marker, col_wk[0]),
                        _fmt_col(_size_label(pkg.size_mb), col_wk[1]),
                        _fmt_col(pkg.tier_minimum, col_wk[2]),
                        _fmt_col(pkg.description[:50], col_wk[3]),
                    ]
                )
            )

    click.echo("\n  (* = required, always included)")

    selected_packages: list[str]

    if preset is not None:
        # --preset flag was passed directly
        preset_obj = reg.get_preset(preset)
        if preset_obj is None:
            click.echo(f"Error: preset '{preset}' not found.", err=True)
            sys.exit(1)
        click.echo(f"\nLoading preset '{preset_obj.name}': {', '.join(preset_obj.packages)}")
        selected_packages = list(preset_obj.packages)
    else:
        preset_ids = {p.id for p in presets}
        raw_input: str = click.prompt(
            "\nEnter package IDs (comma-separated) or a preset ID",
            default="",
        )
        raw_input = raw_input.strip()

        if raw_input in preset_ids:
            preset_obj = reg.get_preset(raw_input)
            assert preset_obj is not None
            click.echo(f"Loading preset '{preset_obj.name}': {', '.join(preset_obj.packages)}")
            selected_packages = list(preset_obj.packages)
        elif raw_input:
            selected_packages = [s.strip() for s in raw_input.split(",") if s.strip()]
        else:
            # Empty input: include only required packages
            selected_packages = []

    # ── Step 4: Dependency resolution & validation ────────────────────────────

    _echo_header("Step 4 — Validation")

    resolved = reg.resolve_dependencies(selected_packages)
    added = [p for p in resolved if p not in selected_packages]
    if added:
        click.echo(f"\nDependencies auto-added: {', '.join(added)}")

    warnings = reg.validate_packages_for_target(resolved, target_id, tier_id)
    if warnings:
        click.echo("\nWarnings:")
        for w in warnings:
            click.echo(f"  ! {w}")
    else:
        click.echo("\nNo validation warnings.")

    est_mb = reg.estimate_image_size_mb(resolved)
    click.echo(f"\nEstimated image size: {_size_label(est_mb)} ({len(resolved)} packages)")

    # ── Step 5: Profile name & confirmation ───────────────────────────────────

    _echo_header("Step 5 — Save Profile")

    if name is None:
        default_name = f"{target_id}-{tier_id}"
        name = click.prompt("Profile name", default=default_name)

    click.echo(f"\n  Target   : {target_id}")
    click.echo(f"  Tier     : {tier_id}")
    click.echo(f"  Packages : {', '.join(resolved)}")
    click.echo(f"  Size est : {_size_label(est_mb)}")
    click.echo(f"  Name     : {name}")

    if not click.confirm("\nSave this profile?", default=True):
        click.echo("Aborted — profile not saved.")
        return

    profile = BuildProfile(
        id=uuid.uuid4().hex[:12],
        name=name,
        target=target_id,
        tier=tier_id,
        packages=resolved,
    )
    saved = mgr.save_profile(profile)
    click.echo(f"\nProfile saved: {saved.id}  ({name})")
    click.echo(f"Build with:    bmt-ai-os image build --profile {saved.id}")


# ---------------------------------------------------------------------------
# build — build from saved profile
# ---------------------------------------------------------------------------


@image.command("build")
@click.option(
    "--profile",
    "-p",
    required=True,
    metavar="PROFILE_ID",
    help="Profile ID to build (from `image list-profiles`).",
)
@click.option(
    "--output",
    "-o",
    default=None,
    metavar="DIR",
    help="Output directory for build artefacts (default: current directory).",
)
@click.option(
    "--manifest-only",
    is_flag=True,
    default=False,
    help="Export build manifest JSON without running the build.",
)
def build(profile: str, output: str | None, manifest_only: bool) -> None:
    """Build the OS image from a saved profile.

    Exports a build manifest and (unless --manifest-only) invokes
    scripts/build.sh --profile <manifest-path>.
    """

    reg = _registry()
    mgr = _manager()

    prof = mgr.get_profile(profile)
    if prof is None:
        click.echo(f"Error: profile '{profile}' not found.", err=True)
        click.echo("Run `bmt-ai-os image list-profiles` to see available profiles.", err=True)
        sys.exit(1)

    output_dir = Path(output) if output else Path.cwd()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / f"build-manifest-{prof.id}.json"

    click.echo(f"\nExporting build manifest for profile '{prof.name}' ({prof.id})...")
    exported = mgr.export_build_manifest(prof.id, reg, manifest_path)
    if exported is None:
        click.echo("Error: failed to export build manifest.", err=True)
        sys.exit(1)

    click.echo(f"Manifest written: {exported}")

    if manifest_only:
        click.echo("\nDone. Skipping build (--manifest-only).")
        return

    # Locate build script relative to this package
    build_script = Path(__file__).parents[2] / "scripts" / "build.sh"
    if not build_script.exists():
        click.echo(
            f"Warning: build script not found at {build_script}. "
            "Manifest is ready — run scripts/build.sh manually.",
            err=True,
        )
        return

    click.echo(f"\nStarting build: {build_script} --target {prof.target} --profile {exported}")
    click.echo("=" * 60)

    result = subprocess.run(
        ["bash", str(build_script), "--target", prof.target, "--profile", str(exported)],
        cwd=str(build_script.parent.parent),
    )

    if result.returncode == 0:
        click.echo("\nBuild completed successfully.")
    else:
        click.echo(f"\nBuild failed (exit code {result.returncode}).", err=True)
        sys.exit(result.returncode)


# ---------------------------------------------------------------------------
# list-packages
# ---------------------------------------------------------------------------


@image.command("list-packages")
@click.option(
    "--category",
    "-c",
    default=None,
    metavar="CATEGORY",
    help="Filter by package category (inference, coding-cli, agent, …).",
)
@click.option(
    "--target",
    "-t",
    default=None,
    metavar="TARGET_ID",
    help="Filter to packages compatible with a hardware target.",
)
@click.option(
    "--tier",
    default=None,
    metavar="TIER_ID",
    help="Filter to packages available in a device tier.",
)
@click.option(
    "--required-only",
    is_flag=True,
    default=False,
    help="Show only required (always-included) packages.",
)
def list_packages(
    category: str | None,
    target: str | None,
    tier: str | None,
    required_only: bool,
) -> None:
    """List available tool packages for image builds."""

    reg = _registry()

    # Build filtered package list
    if tier:
        pkgs = reg.get_packages_for_tier(tier)
        if category:
            pkgs = [p for p in pkgs if p.category == category]
    else:
        pkgs = reg.list_packages(category=category)

    if required_only:
        pkgs = [p for p in pkgs if p.required]

    # Target compatibility filter
    selected_target = reg.get_target(target) if target else None
    if selected_target and selected_target.arch == "aarch64":
        pkgs = [p for p in pkgs if p.arm64]

    if not pkgs:
        click.echo("No packages match the given filters.")
        return

    # Group by category for display
    by_cat: dict[str, list[Any]] = {}
    for p in pkgs:
        by_cat.setdefault(p.category, []).append(p)

    col_w = [26, 10, 10, 8, 52]
    header = "  ".join(
        [
            _fmt_col("ID", col_w[0]),
            _fmt_col("SIZE", col_w[1]),
            _fmt_col("TIER MIN", col_w[2]),
            _fmt_col("ARM64", col_w[3]),
            _fmt_col("DESCRIPTION", col_w[4]),
        ]
    )
    sep = _separator(col_w)

    total_pkgs = 0
    for cat in sorted(by_cat):
        click.echo(f"\n[{cat.upper()}]")
        click.echo("  " + header)
        click.echo("  " + sep)
        for p in by_cat[cat]:
            req_marker = " *" if p.required else ""
            deps_note = f"  (needs: {', '.join(p.dependencies)})" if p.dependencies else ""
            click.echo(
                "  "
                + "  ".join(
                    [
                        _fmt_col(p.id + req_marker, col_w[0]),
                        _fmt_col(_size_label(p.size_mb), col_w[1]),
                        _fmt_col(p.tier_minimum, col_w[2]),
                        _fmt_col("yes" if p.arm64 else "no", col_w[3]),
                        _fmt_col(p.description[:52], col_w[4]),
                    ]
                )
                + deps_note
            )
            total_pkgs += 1

    click.echo(f"\n{total_pkgs} package(s) listed.  (* = always included in image)")

    if category is None and tier is None:
        categories = sorted(by_cat.keys())
        click.echo(f"Filter by category: {', '.join(categories)}")


# ---------------------------------------------------------------------------
# list-profiles
# ---------------------------------------------------------------------------


@image.command("list-profiles")
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Show package list for each profile.",
)
def list_profiles(verbose: bool) -> None:
    """List saved build profiles."""

    mgr = _manager()
    reg = _registry()

    profiles = mgr.list_profiles()
    if not profiles:
        click.echo("No saved profiles found.")
        click.echo("Create one with: bmt-ai-os image configure")
        return

    col_w = [14, 28, 16, 10, 12, 24]
    click.echo(
        "  "
        + "  ".join(
            [
                _fmt_col("ID", col_w[0]),
                _fmt_col("NAME", col_w[1]),
                _fmt_col("TARGET", col_w[2]),
                _fmt_col("TIER", col_w[3]),
                _fmt_col("EST. SIZE", col_w[4]),
                _fmt_col("CREATED", col_w[5]),
            ]
        )
    )
    click.echo("  " + _separator(col_w))

    for prof in profiles:
        est_mb = reg.estimate_image_size_mb(prof.packages)
        # Trim ISO timestamp to date + short time
        created = prof.created_at[:19].replace("T", " ") if prof.created_at else ""
        click.echo(
            "  "
            + "  ".join(
                [
                    _fmt_col(prof.id, col_w[0]),
                    _fmt_col(prof.name, col_w[1]),
                    _fmt_col(prof.target, col_w[2]),
                    _fmt_col(prof.tier, col_w[3]),
                    _fmt_col(_size_label(est_mb), col_w[4]),
                    _fmt_col(created, col_w[5]),
                ]
            )
        )
        if verbose and prof.packages:
            click.echo(f"       packages: {', '.join(prof.packages)}")
            if prof.description:
                click.echo(f"       desc    : {prof.description}")

    click.echo(f"\n{len(profiles)} profile(s).")
    click.echo("Build a profile with: bmt-ai-os image build --profile <ID>")
