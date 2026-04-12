"""File manager endpoints for the BMT AI OS controller API.

Provides directory listing, file reading, uploading, and downloading.
All paths are validated against BMT_FILES_ROOT (default: /data/files).
Symlinks and path traversal are neutralised via Path.resolve().
"""

from __future__ import annotations

import logging
import mimetypes
import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["files"])

# ---------------------------------------------------------------------------
# Root directory — override with BMT_FILES_ROOT env var
# ---------------------------------------------------------------------------

_DEFAULT_ROOT = "/" if os.environ.get("BMT_ENV") == "dev" else "/data/files"
_FILES_ROOT = Path(os.environ.get("BMT_FILES_ROOT", _DEFAULT_ROOT))


def _resolve_safe(rel: str) -> Path:
    """Resolve *rel* relative to _FILES_ROOT and guard against traversal.

    Raises HTTPException(403) if the resolved path escapes the root.
    Raises HTTPException(404) if the path does not exist.
    """
    # Strip leading slashes so Path("/etc/passwd") doesn't break join
    clean = rel.lstrip("/") if rel else ""
    resolved = (_FILES_ROOT / clean).resolve()

    try:
        resolved.relative_to(_FILES_ROOT.resolve())
    except ValueError:
        raise HTTPException(
            status_code=403, detail="Access denied: path outside files root."
        ) from None

    return resolved


# ---------------------------------------------------------------------------
# Models (inline — no Pydantic needed for simple dicts)
# ---------------------------------------------------------------------------


def _entry_dict(path: Path) -> dict:
    """Return a JSON-serialisable dict describing a filesystem entry."""
    stat = path.stat()
    return {
        "name": path.name,
        "path": str(path)
        if str(_FILES_ROOT.resolve()) == "/"
        else str(path.relative_to(_FILES_ROOT.resolve())),
        "is_dir": path.is_dir(),
        "size": stat.st_size if not path.is_dir() else None,
        "modified": stat.st_mtime,
        "mime": mimetypes.guess_type(path.name)[0] if not path.is_dir() else None,
    }


# ---------------------------------------------------------------------------
# Background ingest helpers
# ---------------------------------------------------------------------------

# Regex to extract the persona name from a workspace path segment.
# Matches:  .../agents/<name>/...  anywhere in the resolved path string.
_PERSONA_PATH_RE = re.compile(r"[/\\]agents[/\\]([^/\\]+)[/\\]")

# Only ingest text-based files — skip binary blobs.
_INGESTABLE_EXTENSIONS = {
    ".md",
    ".txt",
    ".rst",
    ".yaml",
    ".yml",
    ".json",
    ".toml",
    ".csv",
    ".log",
    ".py",
    ".js",
    ".ts",
    ".sh",
}


async def _maybe_ingest_persona_file(path: str) -> None:
    """If *path* falls inside a persona workspace, ingest it into the persona's RAG collection.

    Only markdown and plain-text files are ingested.  All exceptions are caught
    silently so that a RAG failure never causes the file write to fail.
    """
    try:
        resolved = _resolve_safe(path)
        suffix = resolved.suffix.lower()

        if suffix not in _INGESTABLE_EXTENSIONS:
            logger.debug("Skipping ingest for non-text file: %s", resolved)
            return

        # Check whether the resolved path lives under workspace/agents/<name>/
        path_str = str(resolved)
        match = _PERSONA_PATH_RE.search(path_str)
        if not match:
            return  # Not inside a persona workspace — nothing to do

        persona_name = match.group(1)

        from bmt_ai_os.rag.config import RAGConfig
        from bmt_ai_os.rag.ingest import DocumentIngester

        from .persona_routes import _persona_collection

        config = RAGConfig()
        collection_name = _persona_collection(persona_name)
        # Override the collection name so DocumentIngester targets the
        # persona-scoped collection rather than the global default.
        config.collection_name = collection_name  # type: ignore[attr-defined]

        ingester = DocumentIngester(config)
        count = ingester.ingest_file(resolved)
        logger.info(
            "Auto-ingested '%s' into persona collection '%s' (%d chunks)",
            resolved,
            collection_name,
            count,
        )

    except Exception as exc:
        logger.warning("Background persona ingest failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/files/list")
async def list_files(path: str = "") -> dict:
    """List entries in a directory.

    Query param ``path`` is relative to the files root (default: "").
    Returns ``{ entries: [...], breadcrumbs: [...] }``.
    """
    target = _resolve_safe(path)

    if not target.exists():
        # Return empty listing with breadcrumbs for non-existent paths
        root_resolved = _FILES_ROOT.resolve()
        rel = path.strip("/")
        parts = rel.split("/") if rel else []
        crumbs = [{"name": "Files", "path": ""}]
        acc = ""
        for p in parts:
            acc = f"{acc}/{p}".lstrip("/")
            crumbs.append({"name": p, "path": acc})
        return {"entries": [], "breadcrumbs": crumbs, "error": f"Directory not found: /{rel}"}

    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory.")

    try:
        entries = sorted(
            target.iterdir(),
            key=lambda p: (not p.is_dir(), p.name.lower()),
        )
        entry_list = [_entry_dict(e) for e in entries]
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied.") from None

    # Build breadcrumb chain
    root_resolved = _FILES_ROOT.resolve()
    rel_parts = target.relative_to(root_resolved).parts
    breadcrumbs = [{"name": "Files", "path": ""}]
    accumulated = ""
    for part in rel_parts:
        accumulated = f"{accumulated}/{part}".lstrip("/")
        breadcrumbs.append({"name": part, "path": accumulated})

    return {"entries": entry_list, "breadcrumbs": breadcrumbs}


@router.get("/files/read")
async def read_file(path: str) -> dict:
    """Return the text content of a file (max 1 MB).

    Binary files are rejected with a 415 error. The caller should use
    ``/files/download`` to fetch binary content.
    """
    target = _resolve_safe(path)

    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Path is a directory.")

    size = target.stat().st_size
    if size > 1 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large for inline preview (max 1 MB).")

    mime, _ = mimetypes.guess_type(target.name)
    # Accept text/* and common code/data types
    text_types = {
        "application/json",
        "application/xml",
        "application/javascript",
        "application/typescript",
        "application/x-sh",
        "application/toml",
        "application/yaml",
        "application/x-yaml",
    }
    is_text = (mime is None) or (mime.startswith("text/")) or (mime in text_types)
    if not is_text:
        raise HTTPException(
            status_code=415,
            detail="Binary file — use /api/v1/files/download to retrieve it.",
        )

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied.") from None

    return {
        "path": path,
        "name": target.name,
        "content": content,
        "size": size,
        "mime": mime or "text/plain",
    }


@router.get("/files/download")
async def download_file(path: str) -> FileResponse:
    """Stream a file to the client as a download."""
    target = _resolve_safe(path)

    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Cannot download a directory.")

    mime, _ = mimetypes.guess_type(target.name)
    return FileResponse(
        path=str(target),
        filename=target.name,
        media_type=mime or "application/octet-stream",
    )


@router.put("/files/write")
async def write_file(request: Request) -> JSONResponse:
    """Write text content to a file (create or overwrite).

    Accepts JSON body ``{ "path": "...", "content": "..." }``.
    The path is relative to the files root.  Max 1 MB.

    After a successful write, if the file lives inside a persona workspace
    (``workspace/agents/<name>/``), it is automatically ingested into the
    persona's RAG collection as a background task.
    """

    body = await request.json()
    path = body.get("path", "")
    content = body.get("content", "")

    if not path:
        raise HTTPException(status_code=422, detail="Missing 'path' field.")

    if len(content) > 1 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Content too large (max 1 MB).")

    target = _resolve_safe(path)

    # Ensure parent directory exists
    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        target.write_text(content, encoding="utf-8")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied.") from None

    response_body = {
        "status": "written",
        "path": path,
        "name": target.name,
        "size": len(content.encode("utf-8")),
    }
    return JSONResponse(
        content=response_body,
        background=BackgroundTask(_maybe_ingest_persona_file, path),
    )


@router.post("/files/upload")
async def upload_file(path: str = "", file: UploadFile = None) -> dict:  # type: ignore[assignment]
    """Upload a file into the directory at *path* (relative to files root)."""
    if file is None:
        raise HTTPException(status_code=422, detail="No file provided.")

    target_dir = _resolve_safe(path)

    if target_dir.exists() and not target_dir.is_dir():
        raise HTTPException(status_code=400, detail="Target path is not a directory.")

    target_dir.mkdir(parents=True, exist_ok=True)

    filename = Path(file.filename or "upload").name  # strip any directory component
    dest = target_dir / filename

    try:
        contents = await file.read()
        dest.write_bytes(contents)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied.") from None

    return {
        "status": "uploaded",
        "path": str(dest.relative_to(_FILES_ROOT.resolve())),
        "name": filename,
        "size": len(contents),
    }


@router.post("/files/mkdir")
async def make_directory(request: Request) -> dict:
    """Create a new directory."""
    body = await request.json()
    path = body.get("path", "")
    if not path:
        raise HTTPException(status_code=422, detail="Missing 'path' field.")

    target = _resolve_safe(path)
    if target.exists():
        raise HTTPException(status_code=409, detail="Path already exists.")

    try:
        target.mkdir(parents=True, exist_ok=False)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied.") from None

    return {"status": "created", "path": path}


@router.post("/files/rename")
async def rename_file(request: Request) -> dict:
    """Rename or move a file or directory."""
    body = await request.json()
    old_path = body.get("old_path", "")
    new_path = body.get("new_path", "")
    if not old_path or not new_path:
        raise HTTPException(status_code=422, detail="Missing 'old_path' or 'new_path'.")

    source = _resolve_safe(old_path)
    dest = _resolve_safe(new_path)

    if not source.exists():
        raise HTTPException(status_code=404, detail="Source not found.")
    if dest.exists():
        raise HTTPException(status_code=409, detail="Destination already exists.")

    try:
        source.rename(dest)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied.") from None

    return {"status": "renamed", "old_path": old_path, "new_path": new_path}


@router.delete("/files/delete")
async def delete_file_or_dir(path: str) -> dict:
    """Delete a file or empty directory."""
    if not path:
        raise HTTPException(status_code=422, detail="Missing 'path' parameter.")

    target = _resolve_safe(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Not found.")

    try:
        if target.is_dir():
            import shutil

            shutil.rmtree(target)
        else:
            target.unlink()
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied.") from None

    return {"status": "deleted", "path": path}
