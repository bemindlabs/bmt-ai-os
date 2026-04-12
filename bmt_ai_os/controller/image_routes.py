"""Image builder API for BMT AI OS controller.

Endpoints
---------
GET    /api/v1/image/targets          — list hardware targets
GET    /api/v1/image/packages         — list tool packages (optional ?category=)
GET    /api/v1/image/tiers            — list device tiers
GET    /api/v1/image/presets          — list build presets
GET    /api/v1/image/profiles         — list saved build profiles
POST   /api/v1/image/profiles         — create/save a build profile
GET    /api/v1/image/profiles/{id}    — get profile details
DELETE /api/v1/image/profiles/{id}    — delete a profile
POST   /api/v1/image/validate         — validate package selection
POST   /api/v1/image/build            — trigger an image build
GET    /api/v1/image/builds/{id}      — get build status
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from bmt_ai_os.dlc.profiles import BuildProfile, ProfileManager
from bmt_ai_os.dlc.registry import PackageRegistry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/image", tags=["image-builder"])

# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------

_registry: PackageRegistry | None = None
_profile_mgr: ProfileManager | None = None
_builds: dict[str, dict[str, Any]] = {}


def _get_registry() -> PackageRegistry:
    global _registry
    if _registry is None:
        _registry = PackageRegistry()
    return _registry


def _get_profile_mgr() -> ProfileManager:
    global _profile_mgr
    if _profile_mgr is None:
        profiles_dir = os.environ.get("BMT_DLC_PROFILES_DIR")
        _profile_mgr = ProfileManager(profiles_dir) if profiles_dir else ProfileManager()
    return _profile_mgr


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class ProfileCreateRequest(BaseModel):
    name: str
    target: str
    tier: str
    packages: list[str]
    description: str = ""
    preset: str | None = None
    custom_options: dict[str, Any] = Field(default_factory=dict)


class ValidateRequest(BaseModel):
    target: str
    tier: str
    packages: list[str]


class BuildRequest(BaseModel):
    profile_id: str


# ---------------------------------------------------------------------------
# Targets, packages, tiers, presets
# ---------------------------------------------------------------------------


@router.get("/targets")
async def list_targets():
    reg = _get_registry()
    return {"targets": [t.__dict__ for t in reg.list_targets()]}


@router.get("/packages")
async def list_packages(category: str | None = Query(None)):
    reg = _get_registry()
    pkgs = reg.list_packages(category=category)
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
            for p in pkgs
        ],
        "categories": reg.get_categories(),
    }


@router.get("/tiers")
async def list_tiers():
    reg = _get_registry()
    return {"tiers": [t.__dict__ for t in reg.list_tiers()]}


@router.get("/presets")
async def list_presets():
    reg = _get_registry()
    return {"presets": [p.__dict__ for p in reg.list_presets()]}


# ---------------------------------------------------------------------------
# Profiles CRUD
# ---------------------------------------------------------------------------


@router.get("/profiles")
async def list_profiles():
    mgr = _get_profile_mgr()
    profiles = mgr.list_profiles()
    return {"profiles": [p.__dict__ for p in profiles]}


@router.post("/profiles", status_code=201)
async def create_profile(req: ProfileCreateRequest):
    reg = _get_registry()
    mgr = _get_profile_mgr()

    # Validate target and tier exist
    if not reg.get_target(req.target):
        raise HTTPException(404, f"Unknown target: {req.target}")
    if not reg.get_tier(req.tier):
        raise HTTPException(404, f"Unknown tier: {req.tier}")

    # Validate packages exist
    for pid in req.packages:
        if not reg.get_package(pid):
            raise HTTPException(400, f"Unknown package: {pid}")

    profile = BuildProfile(
        id=uuid.uuid4().hex[:12],
        name=req.name,
        target=req.target,
        tier=req.tier,
        packages=req.packages,
        description=req.description,
        preset=req.preset,
        custom_options=req.custom_options,
    )
    saved = mgr.save_profile(profile)

    # Run validation
    resolved = reg.resolve_dependencies(req.packages)
    warnings = reg.validate_packages_for_target(resolved, req.target, req.tier)

    return {
        "profile": saved.__dict__,
        "resolved_packages": resolved,
        "warnings": warnings,
        "estimated_size_mb": reg.estimate_image_size_mb(resolved),
    }


@router.get("/profiles/{profile_id}")
async def get_profile(profile_id: str):
    mgr = _get_profile_mgr()
    profile = mgr.get_profile(profile_id)
    if not profile:
        raise HTTPException(404, f"Profile not found: {profile_id}")

    reg = _get_registry()
    resolved = reg.resolve_dependencies(profile.packages)
    warnings = reg.validate_packages_for_target(resolved, profile.target, profile.tier)

    return {
        "profile": profile.__dict__,
        "resolved_packages": resolved,
        "warnings": warnings,
        "estimated_size_mb": reg.estimate_image_size_mb(resolved),
    }


@router.delete("/profiles/{profile_id}")
async def delete_profile(profile_id: str):
    mgr = _get_profile_mgr()
    if not mgr.delete_profile(profile_id):
        raise HTTPException(404, f"Profile not found: {profile_id}")
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------


@router.post("/validate")
async def validate_selection(req: ValidateRequest):
    reg = _get_registry()
    resolved = reg.resolve_dependencies(req.packages)
    warnings = reg.validate_packages_for_target(resolved, req.target, req.tier)
    return {
        "resolved_packages": resolved,
        "warnings": warnings,
        "estimated_size_mb": reg.estimate_image_size_mb(resolved),
        "valid": len(warnings) == 0,
    }


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


@router.get("/build/ready")
async def build_ready():
    """Check whether the build environment is available."""
    script = _find_build_script()
    return {"ready": script is not None, "build_script": script}


@router.post("/build", status_code=202)
async def trigger_build(req: BuildRequest):
    if not _find_build_script():
        raise HTTPException(
            503,
            "Image builds are not available in this environment. "
            "Set BMT_BUILD_SCRIPT or BMT_PROJECT_ROOT, or run the controller on a Linux host.",
        )

    mgr = _get_profile_mgr()
    reg = _get_registry()

    profile = mgr.get_profile(req.profile_id)
    if not profile:
        raise HTTPException(404, f"Profile not found: {req.profile_id}")

    # Export build manifest
    manifest_path = mgr.export_build_manifest(req.profile_id, reg)
    if not manifest_path:
        raise HTTPException(500, "Failed to export build manifest")

    build_id = uuid.uuid4().hex[:12]
    _builds[build_id] = {
        "id": build_id,
        "profile_id": req.profile_id,
        "status": "pending",
        "manifest_path": str(manifest_path),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "log": [],
        "error": None,
    }

    # Launch build in background
    build_env = profile.custom_options.get("env", {}) if profile.custom_options else {}
    asyncio.create_task(_run_build(build_id, profile.target, str(manifest_path), build_env))

    return {"build_id": build_id, "status": "pending", "manifest_path": str(manifest_path)}


@router.get("/builds/{build_id}")
async def get_build_status(build_id: str):
    build = _builds.get(build_id)
    if not build:
        raise HTTPException(404, f"Build not found: {build_id}")
    return build


def _find_build_script() -> str | None:
    """Locate scripts/build.sh, checking env override and common paths."""
    # Explicit override (e.g. host-mounted path in Docker)
    explicit = os.environ.get("BMT_BUILD_SCRIPT")
    if explicit and os.path.isfile(explicit):
        return explicit

    # Derive from BMT_PROJECT_ROOT or from this file's location
    project_root = os.environ.get(
        "BMT_PROJECT_ROOT",
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    )
    candidate = os.path.join(project_root, "scripts", "build.sh")
    if os.path.isfile(candidate):
        return candidate

    return None


async def _run_build(
    build_id: str,
    target: str,
    manifest_path: str,
    extra_env: dict[str, str] | None = None,
) -> None:
    """Run scripts/build.sh --target <target> --profile <manifest> in background."""
    build = _builds[build_id]
    build["status"] = "running"

    build_script = _find_build_script()

    if not build_script:
        build["status"] = "failed"
        build["error"] = (
            "Build script not found. Image builds require a Linux host with Buildroot. "
            "Set BMT_BUILD_SCRIPT or BMT_PROJECT_ROOT to the path containing scripts/build.sh, "
            "or volume-mount the project root into the container."
        )
        return

    cmd = [build_script, "--target", target, "--profile", manifest_path]
    logger.info("Starting image build: %s", " ".join(cmd))

    proc_env = {**os.environ, **(extra_env or {})}

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=proc_env,
        )

        while True:
            line = await proc.stdout.readline()  # type: ignore[union-attr]
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace").rstrip()
            build["log"].append(decoded)

        await proc.wait()

        if proc.returncode == 0:
            build["status"] = "completed"
        else:
            build["status"] = "failed"
            build["error"] = f"Build exited with code {proc.returncode}"
    except Exception as exc:
        build["status"] = "failed"
        build["error"] = str(exc)
        logger.exception("Build %s failed", build_id)
    finally:
        build["completed_at"] = datetime.now(timezone.utc).isoformat()
