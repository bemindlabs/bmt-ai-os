"""BMT AI OS Controller — FastAPI application."""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from bmt_ai_os.fleet.routes import router as fleet_router

from .auth_routes import router as auth_router
from .metrics import get_collector
from .middleware import apply_middleware
from .openai_compat import router as openai_router
from .plugin_routes import router as plugin_router
from .prometheus import router as prometheus_router
from .provider_routes import router as provider_router
from .rag_routes import router as rag_router
from .user_routes import router as user_router

_CONTROLLER_VERSION = "2026.4.11"
logger = logging.getLogger(__name__)

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
app.include_router(user_router)
app.include_router(openai_router)
app.include_router(rag_router, prefix="/api/v1")
app.include_router(fleet_router, prefix="/api/v1")
app.include_router(provider_router)
app.include_router(plugin_router)
app.include_router(prometheus_router)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/api/v1/metrics")
async def metrics_summary() -> dict:
    """Return collected request and health-check metrics for the controller."""
    return get_collector().get_summary()


@app.get("/api/v1/logs")
async def recent_logs() -> dict:
    """Return recent request log entries (ring buffer, last 200)."""
    from .middleware import get_recent_logs

    return {"logs": get_recent_logs()}


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


# ---------------------------------------------------------------------------
# Ollama model management (used by dashboard)
# ---------------------------------------------------------------------------


class PullRequest(BaseModel):
    name: str


async def _get_ollama_provider():
    """Return the Ollama provider instance from the registry."""
    try:
        from bmt_ai_os.providers.registry import get_registry

        registry = get_registry()
        provider = registry.get("ollama")
        if provider is None:
            raise HTTPException(status_code=503, detail="Ollama provider not registered")
        return provider
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/models")
async def list_ollama_models() -> dict:
    """List models installed on Ollama (dashboard format)."""
    provider = await _get_ollama_provider()
    try:
        models = await provider.list_models()
        return {
            "models": [
                {
                    "name": m.name,
                    "size": m.size_bytes,
                    "modified_at": "",
                    "digest": "",
                }
                for m in models
            ]
        }
    except Exception as exc:
        logger.warning("Failed to list Ollama models: %s", exc)
        return {"models": []}


@app.post("/api/pull")
async def pull_model(body: PullRequest) -> dict:
    """Pull a model onto the local Ollama instance."""
    import aiohttp

    provider = await _get_ollama_provider()
    base_url = provider._base_url

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base_url}/api/pull",
                json={"name": body.name, "stream": False},
                timeout=aiohttp.ClientTimeout(total=600),
            ) as resp:
                if resp.status != 200:
                    try:
                        err = await resp.json()
                        detail = err.get("error", str(err))
                    except Exception:
                        detail = await resp.text()
                    raise HTTPException(status_code=422, detail=detail)
                data = await resp.json()
                return {"status": "success", "model": body.name, "detail": data}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Ollama pull failed: {exc}")
