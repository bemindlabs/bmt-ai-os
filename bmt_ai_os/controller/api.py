"""BMT AI OS Controller — FastAPI application."""

from __future__ import annotations

import time

from fastapi import FastAPI, HTTPException, Request

from .auth_routes import router as auth_router
from .conversation_routes import router as conversation_router
from .file_routes import router as file_router
from .git_routes import router as git_router
from .image_routes import router as image_router
from .metrics import get_collector
from .middleware import apply_middleware
from .openai_compat import router as openai_router
from .persona_routes import router as persona_router
from .prometheus import router as prometheus_router
from .provider_config_routes import router as provider_config_router
from .provider_routes import router as provider_router
from .rag_routes import router as rag_router
from .ssh_key_routes import router as ssh_key_router
from .ssh_ws import router as ssh_ws_router
from .terminal_ws import router as terminal_ws_router
from .training_routes import router as training_router
from .user_routes import router as user_router

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
app.include_router(user_router)
app.include_router(openai_router)
app.include_router(rag_router, prefix="/api/v1")
app.include_router(persona_router)
app.include_router(conversation_router)
app.include_router(provider_router)
app.include_router(provider_config_router)
app.include_router(prometheus_router)

# Fleet management routes
from bmt_ai_os.fleet.routes import router as fleet_router  # noqa: E402

app.include_router(fleet_router, prefix="/api/v1")
app.include_router(file_router, prefix="/api/v1")
app.include_router(git_router)
app.include_router(ssh_key_router)
app.include_router(training_router)
app.include_router(image_router)
app.include_router(terminal_ws_router)
app.include_router(ssh_ws_router)

# MCP server (Model Context Protocol — Claude Code integration)
from bmt_ai_os.mcp.server import mcp_router  # noqa: E402

app.include_router(mcp_router, prefix="/mcp")


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


def _get_workspace_root() -> str:
    """Resolve the workspace root from environment variables."""
    import os
    from pathlib import Path

    env = os.environ.get("BMT_ENV", "production")
    default = str(Path.home() / "workspace") if env == "dev" else "/data/workspace"
    return os.environ.get("BMT_WORKSPACE_DIR", default)


# Ordered list of workspace directories to create.
# Each entry: (relative_path, description)
_WORKSPACE_DIRS: list[tuple[str, str]] = [
    ("agents/coding/notes", "Coding agent notes"),
    ("agents/coding/files", "Coding agent files"),
    ("agents/general/notes", "General agent notes"),
    ("agents/general/files", "General agent files"),
    ("agents/creative/notes", "Creative agent notes"),
    ("agents/creative/files", "Creative agent files"),
    ("projects", "User projects"),
    ("data/datasets", "Training datasets"),
    ("data/models", "Saved models"),
    ("data/exports", "Exported artefacts"),
    ("uploads", "Uploaded files"),
    ("shared/notes", "Shared notes"),
    ("shared/documents", "Shared documents"),
    (".config", "Workspace configuration"),
]

# Persona presets to copy as SOUL.md into each agent directory.
_AGENT_SOUL_MAP: dict[str, str] = {
    "coding": "coding.md",
    "general": "general.md",
    "creative": "creative.md",
}


def _scaffold_workspace(workspace_root: str) -> None:
    """Create the full workspace directory structure (idempotent)."""
    import json
    import shutil
    from datetime import datetime, timezone
    from pathlib import Path

    root = Path(workspace_root)

    # Create every declared directory.
    for rel, _desc in _WORKSPACE_DIRS:
        (root / rel).mkdir(parents=True, exist_ok=True)

    # Write .config/workspace.json only on first scaffold.
    config_file = root / ".config" / "workspace.json"
    if not config_file.exists():
        config_file.write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            )
        )

    # Copy persona preset files as SOUL.md into each agent directory.
    presets_dir = Path(__file__).parent.parent / "persona" / "presets"
    for agent, preset_file in _AGENT_SOUL_MAP.items():
        src = presets_dir / preset_file
        dst = root / "agents" / agent / "SOUL.md"
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)


@app.get("/api/v1/settings/workspace")
async def get_workspace() -> dict:
    """Return the default workspace directory path and auto-scaffold the structure."""
    workspace = _get_workspace_root()
    _scaffold_workspace(workspace)
    return {"workspace": workspace}


@app.post("/api/v1/workspace/init")
async def init_workspace() -> dict:
    """Explicitly create the workspace directory structure."""
    workspace = _get_workspace_root()
    _scaffold_workspace(workspace)
    return {"workspace": workspace, "status": "ok"}


@app.get("/api/v1/workspace/structure")
async def get_workspace_structure() -> dict:
    """Return the workspace directory tree as a structured list."""
    workspace = _get_workspace_root()

    # Top-level entries include both leaf dirs and their parents.
    structure = []
    seen: set[str] = set()

    descriptions: dict[str, str] = {rel: desc for rel, desc in _WORKSPACE_DIRS}

    for rel, _desc in _WORKSPACE_DIRS:
        # Emit parent segments first so callers can build a tree if desired.
        parts = rel.split("/")
        for depth in range(1, len(parts) + 1):
            partial = "/".join(parts[:depth])
            if partial not in seen:
                seen.add(partial)
                structure.append(
                    {
                        "name": parts[depth - 1],
                        "path": partial,
                        "description": descriptions.get(partial, ""),
                    }
                )

    return {"workspace": workspace, "structure": structure}


@app.get("/api/v1/logs")
async def get_logs() -> list:
    """Return recent request logs from middleware."""
    from .middleware import get_recent_logs

    return get_recent_logs()


@app.get("/api/models")
async def list_ollama_models() -> dict:
    """List models from Ollama in native format (name, size, digest, modified_at)."""
    import os

    import aiohttp

    ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{ollama_host}/api/tags",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {"models": data.get("models", [])}
    except Exception:
        pass
    return {"models": []}


@app.post("/api/pull")
async def pull_model(request: Request):
    """Pull a model via Ollama API. Streams NDJSON progress from Ollama."""
    import json as _json
    import os

    import aiohttp
    from starlette.responses import StreamingResponse

    body = await request.json()
    model_name = body.get("name", "")
    if not model_name:
        raise HTTPException(status_code=422, detail="Missing 'name' field")

    ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    async def stream_pull():
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{ollama_host}/api/pull",
                    json={"name": model_name, "stream": True},
                    timeout=aiohttp.ClientTimeout(total=1800),
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        yield _json.dumps({"error": text}) + "\n"
                        return
                    async for line in resp.content:
                        decoded = line.decode("utf-8").strip()
                        if decoded:
                            yield decoded + "\n"
        except aiohttp.ClientError as exc:
            yield _json.dumps({"error": f"Ollama unreachable: {exc}"}) + "\n"

    return StreamingResponse(stream_pull(), media_type="application/x-ndjson")


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
