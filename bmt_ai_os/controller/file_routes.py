"""File manager endpoints for the BMT AI OS controller API.

Provides directory listing, file reading, uploading, and downloading.
All paths are validated against BMT_FILES_ROOT (default: /data/files).
Symlinks and path traversal are neutralised via Path.resolve().
"""

from __future__ import annotations

import logging
import mimetypes
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse

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
        raise HTTPException(status_code=403, detail="Access denied: path outside files root.")

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
        raise HTTPException(status_code=403, detail="Permission denied.")

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
        raise HTTPException(status_code=403, detail="Permission denied.")

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
        raise HTTPException(status_code=403, detail="Permission denied.")

    return {
        "status": "uploaded",
        "path": str(dest.relative_to(_FILES_ROOT.resolve())),
        "name": filename,
        "size": len(contents),
    }
