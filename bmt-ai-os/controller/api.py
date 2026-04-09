"""BMT AI OS Controller — FastAPI application."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the bmt-ai-os directory is on sys.path so that ``rag`` is importable.
_BMT_ROOT = str(Path(__file__).resolve().parent.parent)
if _BMT_ROOT not in sys.path:
    sys.path.insert(0, _BMT_ROOT)

from fastapi import FastAPI  # noqa: E402

from controller.rag_routes import router as rag_router  # noqa: E402

app = FastAPI(
    title="BMT AI OS Controller",
    version="0.1.0",
    description="On-device AI stack controller for BMT AI OS.",
)

app.include_router(rag_router, prefix="/api/v1")


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}
