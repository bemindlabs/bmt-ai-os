"""FastAPI routes for the BMT AI OS plugin management API.

Endpoints
---------
GET  /api/v1/plugins                   — list all discovered plugins
GET  /api/v1/plugins/{name}            — get details for a single plugin
POST /api/v1/plugins/{name}/install    — install a discovered plugin
POST /api/v1/plugins/{name}/uninstall  — uninstall an installed plugin
POST /api/v1/plugins/{name}/enable     — enable a plugin
POST /api/v1/plugins/{name}/disable    — disable a plugin
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException

from bmt_ai_os.plugins.manager import PluginManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/plugins", tags=["plugins"])

_DEFAULT_STATE_FILE = os.environ.get("BMT_PLUGIN_STATE", "/tmp/bmt-plugins.json")
_DEFAULT_PLUGIN_DIR = os.environ.get("BMT_PLUGIN_DIR", "/opt/bmt/plugins")


def _get_manager() -> PluginManager:
    """Return a PluginManager configured from environment variables."""
    return PluginManager(state_file=_DEFAULT_STATE_FILE, plugin_dir=_DEFAULT_PLUGIN_DIR)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("")
async def list_plugins() -> dict:
    """List all discovered plugins with their current state."""
    manager = _get_manager()
    plugins = manager.list_plugins()
    return {
        "plugins": [
            {
                **p.to_dict(),
                "installed": manager.is_installed(p.name),
            }
            for p in plugins
        ]
    }


@router.get("/{name}")
async def get_plugin(name: str) -> dict:
    """Return details for a single plugin by name."""
    manager = _get_manager()
    try:
        info = manager.get_plugin_info(name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Plugin '{name}' not found.")
    return {
        **info.to_dict(),
        "installed": manager.is_installed(name),
    }


@router.post("/{name}/install")
async def install_plugin(name: str) -> dict:
    """Install a discovered plugin (mark it as active in the state registry).

    The plugin manifest must already exist in the plugin directory or be
    registered as a Python entry-point.
    """
    manager = _get_manager()
    try:
        manager.install(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"plugin": name, "status": "installed"}


@router.post("/{name}/uninstall")
async def uninstall_plugin(name: str) -> dict:
    """Uninstall a plugin (remove it from the active state registry)."""
    manager = _get_manager()
    try:
        manager.uninstall(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"plugin": name, "status": "uninstalled"}


@router.post("/{name}/enable")
async def enable_plugin(name: str) -> dict:
    """Enable a previously disabled plugin."""
    manager = _get_manager()
    try:
        manager.enable(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"plugin": name, "status": "enabled"}


@router.post("/{name}/disable")
async def disable_plugin(name: str) -> dict:
    """Disable an active plugin without uninstalling it."""
    manager = _get_manager()
    try:
        manager.disable(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"plugin": name, "status": "disabled"}
