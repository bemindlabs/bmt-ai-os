"""RAG query endpoints for the BMT AI OS controller API."""

from __future__ import annotations

import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from bmt_ai_os.rag.config import RAGConfig
from bmt_ai_os.rag.query import RAGQueryEngine, RAGResponse
from bmt_ai_os.rag.storage import ChromaStorage

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rag"])

# Shared instances (initialised once per process).
_config = RAGConfig()
_engine = RAGQueryEngine(_config)
_storage = ChromaStorage(_config)


# ------------------------------------------------------------------
# Request / response models
# ------------------------------------------------------------------


class QueryRequest(BaseModel):
    question: str
    collection: str = "default"
    top_k: int = Field(default=5, ge=1, le=50)
    code_mode: bool = False


class IngestRequest(BaseModel):
    path: str
    collection: str = "default"
    recursive: bool = True


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
    try:
        result: RAGResponse = _engine.query(
            question=req.question,
            collection=req.collection,
            top_k=req.top_k,
            code_mode=req.code_mode,
        )
        return result.to_dict()
    except Exception as exc:
        logger.exception("RAG query failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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
        except Exception as exc:
            logger.exception("RAG stream failed")
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/collections")
async def list_collections() -> list[dict]:
    """List all ChromaDB collections."""
    try:
        return _storage.list_collections()
    except Exception as exc:
        logger.exception("Failed to list collections")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/ingest")
async def ingest(req: IngestRequest) -> dict:
    """Ingest documents from a local path into a ChromaDB collection.

    This is a placeholder -- full ingestion logic lives in the ingest module
    and will be wired in a follow-up story.
    """
    return {
        "status": "accepted",
        "path": req.path,
        "collection": req.collection,
        "recursive": req.recursive,
    }
