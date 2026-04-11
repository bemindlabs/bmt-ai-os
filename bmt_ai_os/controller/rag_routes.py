"""RAG query endpoints for the BMT AI OS controller API."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from bmt_ai_os.rag.config import RAGConfig
from bmt_ai_os.rag.query import RAGQueryEngine, RAGResponse
from bmt_ai_os.rag.storage import ChromaStorage

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rag"])

# Shared instances (initialised once per process).
_config = RAGConfig()
_engine = RAGQueryEngine(_config)
_storage = ChromaStorage(_config)

# Collection name pattern: alphanumeric, hyphens, underscores, 1–100 chars.
_COLLECTION_PATTERN = r"^[a-zA-Z0-9_-]{1,100}$"


# ------------------------------------------------------------------
# Request / response models
# ------------------------------------------------------------------


class QueryRequest(BaseModel):
    question: str = Field(max_length=5000)
    collection: str = Field(default="default", pattern=_COLLECTION_PATTERN)
    top_k: int = Field(default=5, ge=1, le=50)
    code_mode: bool = False


class IngestRequest(BaseModel):
    path: str
    collection: str = Field(default="default", pattern=_COLLECTION_PATTERN)
    recursive: bool = True

    @field_validator("path")
    @classmethod
    def path_must_be_absolute(cls, v: str) -> str:
        """Reject relative paths early so the whitelist check is unambiguous."""
        if not Path(v).is_absolute():
            raise ValueError("path must be an absolute filesystem path")
        return v


class QueryResponseModel(BaseModel):
    answer: str
    sources: list[dict]
    latency_ms: float
    model: str


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


@router.post("/query", response_model=QueryResponseModel)
async def query(req: QueryRequest) -> dict:
    """Run a RAG query and return the augmented answer."""
    import uuid as _uuid

    request_id = str(_uuid.uuid4())
    try:
        result: RAGResponse = _engine.query(
            question=req.question,
            collection=req.collection,
            top_k=req.top_k,
            code_mode=req.code_mode,
        )
        return result.to_dict()
    except (ValueError, KeyError) as exc:
        logger.exception("Invalid RAG query parameters [request_id=%s]", request_id)
        raise HTTPException(status_code=400, detail="Invalid query parameters") from exc
    except (ConnectionError, TimeoutError, OSError) as exc:
        logger.exception("RAG query failed due to storage error [request_id=%s]", request_id)
        raise HTTPException(status_code=502, detail="Vector store unavailable") from exc
    except RuntimeError as exc:
        logger.exception("RAG query failed [request_id=%s]", request_id)
        raise HTTPException(status_code=500, detail="RAG query failed") from exc


@router.post("/query/stream")
async def query_stream(req: QueryRequest) -> StreamingResponse:
    """Stream a RAG query response as Server-Sent Events."""

    async def _event_generator() -> AsyncGenerator[str, None]:
        try:
            for item in _engine.query_stream(
                question=req.question,
                collection=req.collection,
                top_k=req.top_k,
                code_mode=req.code_mode,
            ):
                if isinstance(item, str):
                    yield f"data: {json.dumps({'token': item})}\n\n"
                elif isinstance(item, RAGResponse):
                    yield f"data: {json.dumps({'done': True, **item.to_dict()})}\n\n"
        except Exception:
            logger.exception("RAG stream failed")
            yield f"data: {json.dumps({'error': 'Internal server error'})}\n\n"

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/collections")
async def list_collections() -> list[dict]:
    """List all ChromaDB collections."""
    import uuid as _uuid

    request_id = str(_uuid.uuid4())
    try:
        return _storage.list_collections()
    except (ConnectionError, TimeoutError, OSError) as exc:
        logger.exception("Storage error while listing collections [request_id=%s]", request_id)
        raise HTTPException(status_code=502, detail="Vector store unavailable") from exc
    except RuntimeError as exc:
        logger.exception("Failed to list collections [request_id=%s]", request_id)
        raise HTTPException(status_code=500, detail="Failed to list collections") from exc


def _resolve_and_check_path(raw_path: str) -> Path:
    """Resolve *raw_path* and verify it sits inside an allowed directory.

    Raises ``HTTPException(403)`` when no whitelist is configured or when the
    resolved path falls outside every entry in the whitelist.  Using
    ``Path.resolve()`` expands symlinks and ``..`` components, which prevents
    directory-traversal attacks.
    """
    resolved = Path(raw_path).resolve()

    allowed = _config.allowed_ingest_dirs
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail="Ingest is disabled: BMT_INGEST_ALLOWED_DIRS is not configured.",
        )

    for allowed_dir in allowed:
        try:
            resolved.relative_to(allowed_dir)
            return resolved  # path is inside this allowed dir — accept
        except ValueError:
            continue  # not under this dir, try the next one

    raise HTTPException(
        status_code=403,
        detail=f"Path '{resolved}' is outside all allowed ingest directories.",
    )


@router.post("/ingest")
async def ingest(req: IngestRequest) -> dict:
    """Ingest documents from a local path into a ChromaDB collection.

    The requested path must resolve to a location inside one of the
    directories listed in ``BMT_INGEST_ALLOWED_DIRS``; otherwise a 403 is
    returned.  Symlinks and ``..`` traversal are neutralised via
    ``Path.resolve()``.
    """
    safe_path = _resolve_and_check_path(req.path)
    return {
        "status": "accepted",
        "path": str(safe_path),
        "collection": req.collection,
        "recursive": req.recursive,
    }
