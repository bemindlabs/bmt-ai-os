"""BMT AI OS Controller — FastAPI application."""

from __future__ import annotations

import time

from fastapi import FastAPI

from .auth_routes import router as auth_router
from .conversation_routes import router as conversation_router
from .metrics import get_collector
from .middleware import apply_middleware
from .openai_compat import router as openai_router
from .prometheus import router as prometheus_router
from .provider_routes import router as provider_router
from .rag_routes import router as rag_router

_CONTROLLER_VERSION = "2026.4.11"

_controller = None


def set_controller(ctrl) -> None:
    """Store a reference to the AIController for use by API routes."""
    global _controller
    _controller = ctrl


def get_controller():
    """Return the current AIController instance."""
    return _controller


app = FastAPI(
    title="BMT AI OS Controller",
    version="0.1.0",
    description="On-device AI stack controller for BMT AI OS.",
)

# OpenAI-compatible API and middleware for IDE plugin support
apply_middleware(app)
app.include_router(auth_router)
app.include_router(openai_router)
app.include_router(rag_router, prefix="/api/v1")
app.include_router(conversation_router)
app.include_router(provider_router)
app.include_router(prometheus_router)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/api/v1/metrics")
async def metrics_summary() -> dict:
    """Return collected request and health-check metrics for the controller."""
    return get_collector().get_summary()


@app.get("/api/v1/status")
async def system_status() -> dict:
    """Overall system status: version, uptime, and per-service health."""
    ctrl = get_controller()

    if ctrl is not None:
        uptime_seconds = round(time.time() - ctrl._start_time, 1)
        services = ctrl.get_status()
    else:
        uptime_seconds = None
        services = []

    return {
        "version": _CONTROLLER_VERSION,
        "status": "running",
        "uptime_seconds": uptime_seconds,
        "services": services,
    }
