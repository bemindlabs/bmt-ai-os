"""File read/write endpoints for the BMT AI OS controller API.

GET  /api/v1/files?path=         — list directory contents
GET  /api/v1/files/read?path=    — read file content as text
PUT  /api/v1/files/write         — write file content

All paths are validated against BMT_FILES_ALLOWED_DIRS (env var, colon-separated).
Falls back to a hard-coded safe list when the env var is not set.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/files", tags=["files"])

# ---------------------------------------------------------------------------
# Allowed directories
# ---------------------------------------------------------------------------

_DEFAULT_ALLOWED = [
    "/home",
    "/opt/bmt",
    "/var/lib/bmt",
    "/tmp/bmt-editor",
]


def _get_allowed_dirs() -> list[Path]:
    """Return resolved allowed root directories from env or defaults."""
    raw = os.environ.get("BMT_FILES_ALLOWED_DIRS", "")
    if raw.strip():
        dirs = [Path(p.strip()).resolve() for p in raw.split(":") if p.strip()]
    else:
        dirs = [Path(p).resolve() for p in _DEFAULT_ALLOWED]
    return dirs


def _resolve_and_check(raw_path: str, *, must_exist: bool = False) -> Path:
    """Resolve *raw_path* and assert it is within an allowed directory.

    Raises ``HTTPException(400)`` for relative paths.
    Raises ``HTTPException(403)`` when the resolved path escapes allowed roots.
    Raises ``HTTPException(404)`` when *must_exist* is True and path is absent.
    """
    if not Path(raw_path).is_absolute():
        raise HTTPException(status_code=400, detail="path must be absolute")

    resolved = Path(raw_path).resolve()

    allowed_dirs = _get_allowed_dirs()
    for allowed in allowed_dirs:
        try:
            resolved.relative_to(allowed)
            break  # inside this allowed dir — OK
        except ValueError:
            continue
    else:
        raise HTTPException(
            status_code=403,
            detail=f"Path '{resolved}' is outside all allowed directories.",
        )

    if must_exist and not resolved.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {resolved}")

    return resolved


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class FileEntry(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int | None = None
    extension: str | None = None


class FileListResponse(BaseModel):
    path: str
    entries: list[FileEntry]


class FileReadResponse(BaseModel):
    path: str
    content: str
    size: int


class FileWriteRequest(BaseModel):
    path: str
    content: str


class FileWriteResponse(BaseModel):
    path: str
    size: int
    ok: bool = True


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=FileListResponse)
async def list_directory(
    path: str = Query(..., description="Absolute path to list"),
) -> FileListResponse:
    """List directory contents."""
    resolved = _resolve_and_check(path, must_exist=True)

    if not resolved.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    entries: list[FileEntry] = []
    try:
        for child in sorted(resolved.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            try:
                stat = child.stat()
                size = stat.st_size if child.is_file() else None
            except OSError:
                size = None

            entries.append(
                FileEntry(
                    name=child.name,
                    path=str(child),
                    is_dir=child.is_dir(),
                    size=size,
                    extension=child.suffix.lstrip(".")
                    if child.is_file() and child.suffix
                    else None,
                )
            )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Permission denied") from exc

    return FileListResponse(path=str(resolved), entries=entries)


@router.get("/read", response_model=FileReadResponse)
async def read_file(
    path: str = Query(..., description="Absolute path to read"),
) -> FileReadResponse:
    """Read a text file and return its content."""
    resolved = _resolve_and_check(path, must_exist=True)

    if resolved.is_dir():
        raise HTTPException(status_code=400, detail="Path is a directory, not a file")

    # Guard against very large files (>10 MB)
    try:
        stat = resolved.stat()
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Could not stat file") from exc

    max_bytes = 10 * 1024 * 1024  # 10 MB
    if stat.st_size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({stat.st_size} bytes). Max 10 MB.",
        )

    try:
        content = resolved.read_text(encoding="utf-8", errors="replace")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Permission denied") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Could not read file") from exc

    return FileReadResponse(path=str(resolved), content=content, size=stat.st_size)


@router.put("/write", response_model=FileWriteResponse)
async def write_file(req: FileWriteRequest) -> FileWriteResponse:
    """Write (create or overwrite) a text file."""
    resolved = _resolve_and_check(req.path)

    # Ensure parent directory exists
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        raise HTTPException(
            status_code=403, detail="Permission denied creating directories"
        ) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Could not create parent directories") from exc

    try:
        resolved.write_text(req.content, encoding="utf-8")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Permission denied writing file") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Could not write file") from exc

    size = len(req.content.encode("utf-8"))
    logger.info("File written: %s (%d bytes)", resolved, size)

    return FileWriteResponse(path=str(resolved), size=size)
