"""Persona management API routes for BMT AI OS controller.

GET  /api/v1/persona                   — return current SOUL.md content
PUT  /api/v1/persona                   — save SOUL.md content to workspace
GET  /api/v1/persona/presets           — list available preset names + content
POST /api/v1/persona/presets/{name}/apply — copy preset to active workspace
POST /api/v1/persona/activate/{name}   — activate a persona + scaffold workspace dirs
GET  /api/v1/persona/active            — return the currently active persona
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/persona", tags=["persona"])

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PACKAGE_DIR = Path(__file__).parent.parent
_PRESETS_DIR = _PACKAGE_DIR / "persona" / "presets"
_PRESET_NAMES = ("coding", "general", "creative")

_ENV_PERSONA_DIR = "BMT_PERSONA_DIR"
_ENV_DEFAULT_PERSONA = "BMT_DEFAULT_PERSONA"
_USER_PERSONA_BASE = Path.home() / ".bmt-ai-os" / "personas"

# ---------------------------------------------------------------------------
# Workspace root (mirrors api.py _get_workspace_root logic)
# ---------------------------------------------------------------------------

_ENV = os.environ.get("BMT_ENV", "production")
_DEFAULT_WS = str(Path.home() / "workspace") if _ENV == "dev" else "/data/workspace"
_WORKSPACE_ROOT = Path(os.environ.get("BMT_WORKSPACE_DIR", _DEFAULT_WS))

# ---------------------------------------------------------------------------
# Active persona state (module-level, reset per process)
# ---------------------------------------------------------------------------

_active_persona: str | None = None


def _get_active_persona() -> str | None:
    return _active_persona


def _set_active_persona(name: str) -> None:
    global _active_persona
    _active_persona = name


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_workspace() -> Path:
    """Return the active persona workspace directory."""
    explicit = os.getenv(_ENV_PERSONA_DIR, "").strip()
    if explicit:
        return Path(explicit)

    name = os.getenv(_ENV_DEFAULT_PERSONA, "").strip() or "default"
    user_ws = _USER_PERSONA_BASE / name
    if user_ws.is_dir():
        return user_ws

    return _PRESETS_DIR


def _soul_path() -> Path:
    """Return the path to the active SOUL.md (may not exist yet)."""
    return _resolve_workspace() / "SOUL.md"


def _persona_workspace_path(name: str) -> Path:
    """Return the agents/<name> workspace path under the workspace root."""
    return _WORKSPACE_ROOT / "agents" / name


def _persona_collection(name: str) -> str:
    """Return the RAG collection name for a given persona."""
    return f"persona-{name}"


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class PersonaResponse(BaseModel):
    content: str
    workspace: str


class SavePersonaRequest(BaseModel):
    content: str = Field(max_length=32_000)


class PresetInfo(BaseModel):
    name: str
    content: str
    workspace_path: str
    collection: str


class PresetsResponse(BaseModel):
    presets: list[PresetInfo]


class ApplyPresetResponse(BaseModel):
    name: str
    workspace: str
    message: str


class ActivatePersonaResponse(BaseModel):
    active: str
    workspace_path: str


class ActivePersonaResponse(BaseModel):
    active: str | None
    workspace_path: str | None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=PersonaResponse)
async def get_persona() -> PersonaResponse:
    """Return the current active SOUL.md content."""
    soul = _soul_path()

    if soul.is_file():
        try:
            content = soul.read_text(encoding="utf-8")
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Failed to read SOUL.md: {exc}") from exc
    else:
        # Fall back to the bundled general preset
        fallback = _PRESETS_DIR / "general.md"
        try:
            content = fallback.read_text(encoding="utf-8")
        except OSError:
            content = ""

    return PersonaResponse(content=content, workspace=str(soul.parent))


@router.put("", response_model=PersonaResponse)
async def save_persona(body: SavePersonaRequest) -> PersonaResponse:
    """Persist SOUL.md content to the active workspace."""
    soul = _soul_path()
    try:
        soul.parent.mkdir(parents=True, exist_ok=True)
        soul.write_text(body.content, encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write SOUL.md: {exc}") from exc

    return PersonaResponse(content=body.content, workspace=str(soul.parent))


@router.get("/presets", response_model=PresetsResponse)
async def list_presets() -> PresetsResponse:
    """List all available persona presets with their content, workspace path, and RAG collection."""
    presets: list[PresetInfo] = []
    for name in _PRESET_NAMES:
        preset_file = _PRESETS_DIR / f"{name}.md"
        if preset_file.is_file():
            try:
                content = preset_file.read_text(encoding="utf-8")
            except OSError:
                content = ""
        else:
            content = ""
        presets.append(
            PresetInfo(
                name=name,
                content=content,
                workspace_path=str(_persona_workspace_path(name)),
                collection=_persona_collection(name),
            )
        )
    return PresetsResponse(presets=presets)


@router.post("/activate/{name}", response_model=ActivatePersonaResponse)
async def activate_persona(name: str) -> ActivatePersonaResponse:
    """Activate a named persona, scaffold its workspace dirs, and copy its SOUL.md.

    - Creates agents/<name>/notes/ and agents/<name>/files/ under the workspace root.
    - Copies the preset SOUL.md into the workspace if not already present.
    - Stores the active persona name in module-level state.
    """
    if name not in _PRESET_NAMES:
        raise HTTPException(
            status_code=404,
            detail=f"Persona '{name}' not found. Available: {', '.join(_PRESET_NAMES)}",
        )

    persona_dir = _persona_workspace_path(name)

    # Create workspace subdirectories (idempotent)
    try:
        (persona_dir / "notes").mkdir(parents=True, exist_ok=True)
        (persona_dir / "files").mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to create workspace dirs: {exc}"
        ) from exc

    # Copy preset SOUL.md into the workspace if not already present
    preset_file = _PRESETS_DIR / f"{name}.md"
    soul_dst = persona_dir / "SOUL.md"
    if preset_file.is_file() and not soul_dst.exists():
        try:
            shutil.copy2(preset_file, soul_dst)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Failed to copy SOUL.md: {exc}") from exc

    _set_active_persona(name)
    logger.info("Persona '%s' activated, workspace: %s", name, persona_dir)

    return ActivatePersonaResponse(active=name, workspace_path=str(persona_dir))


@router.get("/active", response_model=ActivePersonaResponse)
async def get_active_persona() -> ActivePersonaResponse:
    """Return the currently active persona name and workspace path."""
    name = _get_active_persona()
    if name is None:
        return ActivePersonaResponse(active=None, workspace_path=None)
    return ActivePersonaResponse(
        active=name,
        workspace_path=str(_persona_workspace_path(name)),
    )


@router.post("/presets/{name}/apply", response_model=ApplyPresetResponse)
async def apply_preset(name: str) -> ApplyPresetResponse:
    """Copy a named preset to the active workspace as SOUL.md."""
    if name not in _PRESET_NAMES:
        raise HTTPException(
            status_code=404,
            detail=f"Preset '{name}' not found. Available: {', '.join(_PRESET_NAMES)}",
        )

    preset_file = _PRESETS_DIR / f"{name}.md"
    if not preset_file.is_file():
        raise HTTPException(status_code=404, detail=f"Preset file missing: {preset_file}")

    try:
        content = preset_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read preset: {exc}") from exc

    soul = _soul_path()
    try:
        soul.parent.mkdir(parents=True, exist_ok=True)
        soul.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write SOUL.md: {exc}") from exc

    logger.info("Persona preset '%s' applied to %s", name, soul)
    return ApplyPresetResponse(
        name=name,
        workspace=str(soul.parent),
        message=f"Preset '{name}' applied successfully.",
    )
