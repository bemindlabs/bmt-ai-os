"""Fleet management FastAPI routes.

Mounted at ``/api/v1/fleet`` by the controller.

Endpoints
---------
POST /api/v1/fleet/register
    Register (or re-register) a device with the central registry.

POST /api/v1/fleet/heartbeat
    Receive a heartbeat from a device agent; return next pending command.

GET  /api/v1/fleet/devices
    List all registered devices with their latest status.

GET  /api/v1/fleet/devices/{device_id}
    Get detailed record for a single device.

DELETE /api/v1/fleet/devices/{device_id}
    Remove a device from the registry.

GET  /api/v1/fleet/summary
    Aggregated fleet-wide metrics (device counts, models).

GET  /api/v1/fleet/health
    Lightweight health probe (always 200 when the server is up).

POST /api/v1/fleet/devices/{device_id}/command
    Queue a command for a specific device.

POST /api/v1/fleet/deploy-model
    Queue a ``pull-model`` command on one or all devices.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .models import DeviceHeartbeat, FleetCommand
from .registry import get_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/fleet", tags=["fleet"])


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    device_id: str
    hostname: str = ""
    arch: str = ""
    board: str = ""
    hardware: dict[str, Any] = Field(default_factory=dict)


class HeartbeatRequest(BaseModel):
    device_id: str
    timestamp: str
    os_version: str = ""
    hardware: dict[str, Any] = Field(default_factory=dict)
    loaded_models: list[str] = Field(default_factory=list)
    service_health: dict[str, str] = Field(default_factory=dict)
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    disk_percent: float = 0.0


class CommandRequest(BaseModel):
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    command_id: str = ""


class DeployModelRequest(BaseModel):
    model: str
    device_ids: list[str] | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/register", status_code=200)
async def register_device(req: RegisterRequest) -> dict[str, Any]:
    """Register (or re-register) a device with the central fleet registry."""
    registry = get_registry()
    rec = registry.register_device(
        device_id=req.device_id,
        hostname=req.hostname,
        arch=req.arch,
        board=req.board,
        hardware=req.hardware or None,
    )
    logger.info("Device registered via API: %s", req.device_id)
    return {
        "status": "registered",
        "device_id": rec.device_id,
        "registered_at": rec.registered_at,
    }


@router.post("/heartbeat", status_code=200)
async def receive_heartbeat(req: HeartbeatRequest) -> dict[str, Any]:
    """Accept a device heartbeat and return the next pending command (if any)."""
    registry = get_registry()

    hb = DeviceHeartbeat(
        device_id=req.device_id,
        timestamp=req.timestamp,
        os_version=req.os_version,
        hardware=req.hardware,
        loaded_models=req.loaded_models,
        service_health=req.service_health,
        cpu_percent=req.cpu_percent,
        memory_percent=req.memory_percent,
        disk_percent=req.disk_percent,
    )

    cmd = registry.apply_heartbeat(hb)
    logger.debug("Heartbeat from %s — returning command: %r", req.device_id, cmd.action)

    return {
        "action": cmd.action,
        "params": cmd.params,
        "command_id": cmd.command_id,
        "status": cmd.status,
    }


@router.get("/devices", status_code=200)
async def list_devices() -> dict[str, Any]:
    """Return a list of all registered devices and their current status."""
    registry = get_registry()
    return {
        "devices": registry.list_devices(),
        "total": registry.device_count(),
        "online": registry.online_count(),
    }


@router.get("/devices/{device_id}", status_code=200)
async def get_device(device_id: str) -> dict[str, Any]:
    """Return the full record for a single device."""
    registry = get_registry()
    rec = registry.get_device(device_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"Device not found: {device_id}")
    return rec.to_dict()


@router.delete("/devices/{device_id}", status_code=200)
async def remove_device(device_id: str) -> dict[str, Any]:
    """Remove a device from the fleet registry."""
    registry = get_registry()
    removed = registry.remove_device(device_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Device not found: {device_id}")
    return {"status": "removed", "device_id": device_id}


@router.get("/summary", status_code=200)
async def fleet_summary() -> dict[str, Any]:
    """Return aggregated fleet-wide metrics suitable for a dashboard."""
    return get_registry().summary()


@router.get("/health", status_code=200)
async def fleet_health() -> dict[str, Any]:
    """Lightweight health probe — always 200 when the fleet server is up."""
    registry = get_registry()
    return {
        "status": "ok",
        "total_devices": registry.device_count(),
        "online_devices": registry.online_count(),
    }


@router.post("/devices/{device_id}/command", status_code=202)
async def queue_command(device_id: str, req: CommandRequest) -> dict[str, Any]:
    """Queue a command for delivery to a specific device on its next heartbeat."""
    registry = get_registry()
    cmd = FleetCommand(
        action=req.action,
        params=req.params,
        command_id=req.command_id,
        status="pending",
    )
    queued = registry.enqueue_command(device_id, cmd)
    if not queued:
        raise HTTPException(status_code=404, detail=f"Device not found: {device_id}")
    logger.info(
        "Command %r queued for device %s (command_id=%r)",
        req.action,
        device_id,
        req.command_id,
    )
    return {
        "status": "queued",
        "device_id": device_id,
        "action": req.action,
        "command_id": req.command_id,
    }


@router.post("/deploy-model", status_code=202)
async def deploy_model(req: DeployModelRequest) -> dict[str, Any]:
    """Queue a ``pull-model`` command on one or more devices.

    Omit ``device_ids`` to broadcast to the entire fleet.
    """
    if not req.model.strip():
        raise HTTPException(status_code=422, detail="model must not be empty")

    registry = get_registry()
    targeted = registry.deploy_model(
        model=req.model.strip(),
        device_ids=req.device_ids,
    )
    logger.info("Model deploy %r queued on %d device(s)", req.model, len(targeted))
    return {
        "status": "queued",
        "model": req.model,
        "targeted_devices": targeted,
        "device_count": len(targeted),
    }
