"""BMT AI OS Controller — FastAPI application."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the bmt-ai-os directory is on sys.path so that ``rag`` is importable.
_BMT_ROOT = str(Path(__file__).resolve().parent.parent)
if _BMT_ROOT not in sys.path:
    sys.path.insert(0, _BMT_ROOT)

from controller.middleware import apply_middleware  # noqa: E402
from controller.openai_compat import router as openai_router  # noqa: E402
from controller.rag_routes import router as rag_router  # noqa: E402
from fastapi import FastAPI  # noqa: E402

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


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}
