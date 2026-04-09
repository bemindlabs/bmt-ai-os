"""HTTP API for BMT AI OS Controller.

Provides endpoints for service status, health, and stack management.
Serves on the configured API port (default 8080).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException

if TYPE_CHECKING:
    from .main import BMTAIOSController

logger = logging.getLogger("bmt-controller.api")

app = FastAPI(
    title="BMT AI OS Controller",
    version="0.1.0",
    description="AI stack orchestration API for BMT AI OS",
)

# The controller instance is attached at startup by main.py.
_controller: BMTAIOSController | None = None


def set_controller(controller: BMTAIOSController) -> None:
    """Attach the controller instance so endpoints can use it."""
    global _controller
    _controller = controller


def _get_controller() -> BMTAIOSController:
    if _controller is None:
        raise HTTPException(status_code=503, detail="Controller not initialized")
    return _controller


# --- Endpoints ---


@app.get("/health")
async def health() -> dict:
    """Controller own health check."""
    return {"status": "ok", "service": "bmt-controller"}


@app.get("/api/v1/status")
async def stack_status() -> dict:
    """Return status of all managed AI stack services."""
    ctrl = _get_controller()
    return {"services": ctrl.get_status()}


@app.post("/api/v1/services/{name}/restart")
async def restart_service(name: str) -> dict:
    """Restart a specific AI stack service by name."""
    ctrl = _get_controller()
    known = {svc.name for svc in ctrl.config.services}
    if name not in known:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown service '{name}'. Known: {sorted(known)}",
        )
    success = ctrl.restart_service(name)
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to restart {name}")
    return {"status": "restarted", "service": name}


@app.post("/api/v1/stack/start")
async def start_stack() -> dict:
    """Start the entire AI stack."""
    ctrl = _get_controller()
    ctrl.start_stack()
    return {"status": "started"}


@app.post("/api/v1/stack/stop")
async def stop_stack() -> dict:
    """Stop the entire AI stack."""
    ctrl = _get_controller()
    ctrl.stop_stack()
    return {"status": "stopped"}
