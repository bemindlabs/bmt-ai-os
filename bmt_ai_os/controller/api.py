"""BMT AI OS Controller — FastAPI application."""

from __future__ import annotations

from fastapi import FastAPI

from .middleware import apply_middleware
from .openai_compat import router as openai_router
from .provider_routes import router as provider_router
from .rag_routes import router as rag_router

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
app.include_router(openai_router)
app.include_router(rag_router, prefix="/api/v1")
app.include_router(provider_router)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}
