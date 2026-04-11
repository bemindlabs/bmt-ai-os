"""OpenAI-compatible API endpoints for IDE AI plugin support.

Implements the OpenAI REST API surface so that Cursor, Copilot, Cody, and
other IDEs can use BMT AI OS as their AI backend.

Endpoints:
    POST /v1/chat/completions   — Chat completions (with SSE streaming)
    POST /v1/completions        — Legacy text completions (code completion)
    POST /v1/embeddings         — Embeddings
    GET  /v1/models             — List available models
"""

from __future__ import annotations

import dataclasses
import json
import logging
import time
import uuid
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["openai-compat"])


# ---------------------------------------------------------------------------
# Request / response schemas (OpenAI-compatible)
# ---------------------------------------------------------------------------


class ChatMessageIn(BaseModel):
    role: str
    content: str
    name: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str = "default"
    messages: list[ChatMessageIn]
    temperature: float = 0.7
    max_tokens: int | None = None
    top_p: float = 1.0
    n: int = 1
    stream: bool = False
    stop: list[str] | str | None = None
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0
    user: str | None = None


class CompletionRequest(BaseModel):
    model: str = "default"
    prompt: str | list[str] = ""
    max_tokens: int = 256
    temperature: float = 0.7
    top_p: float = 1.0
    n: int = 1
    stream: bool = False
    stop: list[str] | str | None = None
    suffix: str | None = None
    echo: bool = False
    user: str | None = None


class EmbeddingRequest(BaseModel):
    input: str | list[str]
    model: str = "default"
    encoding_format: str = "float"
    user: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_id(prefix: str = "chatcmpl") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:24]}"


def _unix_ts() -> int:
    return int(time.time())


def _build_chat_response(
    content: str,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    finish_reason: str = "stop",
) -> dict[str, Any]:
    return {
        "id": _make_id("chatcmpl"),
        "object": "chat.completion",
        "created": _unix_ts(),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _build_completion_response(
    text: str,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    finish_reason: str = "stop",
) -> dict[str, Any]:
    return {
        "id": _make_id("cmpl"),
        "object": "text_completion",
        "created": _unix_ts(),
        "model": model,
        "choices": [
            {
                "text": text,
                "index": 0,
                "logprobs": None,
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


async def _stream_chat_chunks(
    stream: AsyncIterator[str],
    model: str,
    request_id: str,
) -> AsyncIterator[str]:
    """Wrap provider stream output into SSE-formatted chat completion chunks."""
    created = _unix_ts()

    # Initial chunk with role
    initial = {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": ""},
                "finish_reason": None,
            }
        ],
    }
    yield f"data: {json.dumps(initial)}\n\n"

    async for chunk in stream:
        payload = {
            "id": request_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": chunk},
                    "finish_reason": None,
                }
            ],
        }
        yield f"data: {json.dumps(payload)}\n\n"

    # Final chunk
    final = {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }
        ],
    }
    yield f"data: {json.dumps(final)}\n\n"
    yield "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Provider access helper
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _ChatMessage:
    """Lightweight chat message compatible with all provider base variants."""

    role: str
    content: str


def _make_chat_message(role: str, content: str) -> Any:
    """Create a ChatMessage using the provider base class if available,
    falling back to a local dataclass."""
    try:
        from bmt_ai_os.providers.base import ChatMessage

        return ChatMessage(role=role, content=content)
    except ImportError:
        logger.exception("Failed to import ChatMessage from providers.base; using fallback")
        return _ChatMessage(role=role, content=content)


def _get_provider_router():
    """Lazy import to avoid circular deps; returns the provider router singleton.

    Falls back to the provider registry when the router is not initialised.
    """
    try:
        from bmt_ai_os.providers.registry import get_registry

        return get_registry()
    except ImportError:
        logger.exception("Failed to import provider registry")
        return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/v1/chat/completions")
async def chat_completions(body: ChatCompletionRequest, request: Request):
    """OpenAI-compatible chat completions with optional SSE streaming."""
    request_id = _make_id("chatcmpl")

    registry = _get_provider_router()
    if registry is None:
        raise HTTPException(status_code=503, detail="No provider available")

    messages = [_make_chat_message(m.role, m.content) for m in body.messages]
    model = body.model if body.model != "default" else None
    max_tokens = body.max_tokens or 4096

    try:
        provider = registry.get_active()
    except (RuntimeError, LookupError) as exc:
        logger.exception("Failed to get active provider [request_id=%s]", request_id)
        raise HTTPException(status_code=503, detail="No active provider") from exc

    if body.stream:
        try:
            stream = await provider.chat(
                messages,
                model=model,
                temperature=body.temperature,
                max_tokens=max_tokens,
                stream=True,
            )
        except (ConnectionError, TimeoutError) as exc:
            logger.exception(
                "Upstream connection error during streaming chat [request_id=%s]", request_id
            )
            raise HTTPException(status_code=502, detail="Upstream provider unavailable") from exc
        except (ValueError, TypeError) as exc:
            logger.exception(
                "Invalid request parameters for streaming chat [request_id=%s]", request_id
            )
            raise HTTPException(status_code=400, detail="Invalid request parameters") from exc
        except OSError as exc:
            logger.exception("I/O error during streaming chat [request_id=%s]", request_id)
            raise HTTPException(status_code=502, detail="Upstream provider unavailable") from exc

        model_name = model or provider.name

        return StreamingResponse(
            _stream_chat_chunks(stream, model_name, request_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # Non-streaming
    try:
        response = await provider.chat(
            messages,
            model=model,
            temperature=body.temperature,
            max_tokens=max_tokens,
            stream=False,
        )
    except (ConnectionError, TimeoutError) as exc:
        logger.exception(
            "Upstream connection error during chat completion [request_id=%s]", request_id
        )
        raise HTTPException(status_code=502, detail="Upstream provider unavailable") from exc
    except (ValueError, TypeError) as exc:
        logger.exception(
            "Invalid request parameters for chat completion [request_id=%s]", request_id
        )
        raise HTTPException(status_code=400, detail="Invalid request parameters") from exc
    except OSError as exc:
        logger.exception("I/O error during chat completion [request_id=%s]", request_id)
        raise HTTPException(status_code=502, detail="Upstream provider unavailable") from exc

    _in = getattr(response, "input_tokens", None)
    prompt_tokens = _in if _in is not None else getattr(response, "prompt_tokens", 0)
    _out = getattr(response, "output_tokens", None)
    completion_tokens = _out if _out is not None else getattr(response, "completion_tokens", 0)

    return _build_chat_response(
        content=response.content,
        model=response.model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


@router.post("/v1/completions")
async def completions(body: CompletionRequest, request: Request):
    """OpenAI-compatible legacy completions (used by Copilot for code completion)."""
    request_id = _make_id("cmpl")

    registry = _get_provider_router()
    if registry is None:
        raise HTTPException(status_code=503, detail="No provider available")

    # Convert prompt to a chat message (single-turn)
    prompt = body.prompt if isinstance(body.prompt, str) else "\n".join(body.prompt)
    messages = [_make_chat_message("user", prompt)]

    try:
        provider = registry.get_active()
    except (RuntimeError, LookupError) as exc:
        logger.exception("Failed to get active provider [request_id=%s]", request_id)
        raise HTTPException(status_code=503, detail="No active provider") from exc

    if body.stream:
        try:
            stream = await provider.chat(
                messages,
                model=body.model if body.model != "default" else None,
                temperature=body.temperature,
                max_tokens=body.max_tokens,
                stream=True,
            )
        except (ConnectionError, TimeoutError) as exc:
            logger.exception(
                "Upstream connection error during streaming completion [request_id=%s]", request_id
            )
            raise HTTPException(status_code=502, detail="Upstream provider unavailable") from exc
        except (ValueError, TypeError) as exc:
            logger.exception(
                "Invalid request parameters for streaming completion [request_id=%s]", request_id
            )
            raise HTTPException(status_code=400, detail="Invalid request parameters") from exc
        except OSError as exc:
            logger.exception("I/O error during streaming completion [request_id=%s]", request_id)
            raise HTTPException(status_code=502, detail="Upstream provider unavailable") from exc

        model_name = body.model if body.model != "default" else provider.name

        async def _stream_completion() -> AsyncIterator[str]:
            created = _unix_ts()
            async for chunk in stream:
                payload = {
                    "id": request_id,
                    "object": "text_completion",
                    "created": created,
                    "model": model_name,
                    "choices": [
                        {
                            "text": chunk,
                            "index": 0,
                            "logprobs": None,
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(payload)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            _stream_completion(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # Non-streaming
    try:
        response = await provider.chat(
            messages,
            model=body.model if body.model != "default" else None,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            stream=False,
        )
    except (ConnectionError, TimeoutError) as exc:
        logger.exception("Upstream connection error during completion [request_id=%s]", request_id)
        raise HTTPException(status_code=502, detail="Upstream provider unavailable") from exc
    except (ValueError, TypeError) as exc:
        logger.exception("Invalid request parameters for completion [request_id=%s]", request_id)
        raise HTTPException(status_code=400, detail="Invalid request parameters") from exc
    except OSError as exc:
        logger.exception("I/O error during completion [request_id=%s]", request_id)
        raise HTTPException(status_code=502, detail="Upstream provider unavailable") from exc

    _in = getattr(response, "input_tokens", None)
    prompt_tokens = _in if _in is not None else getattr(response, "prompt_tokens", 0)
    _out = getattr(response, "output_tokens", None)
    completion_tokens = _out if _out is not None else getattr(response, "completion_tokens", 0)

    return _build_completion_response(
        text=response.content,
        model=response.model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


@router.post("/v1/embeddings")
async def embeddings(body: EmbeddingRequest):
    """OpenAI-compatible embeddings endpoint (used by Cody for RAG)."""
    request_id = _make_id("embed")

    registry = _get_provider_router()
    if registry is None:
        raise HTTPException(status_code=503, detail="No provider available")

    texts = body.input if isinstance(body.input, list) else [body.input]
    model = body.model if body.model != "default" else None

    try:
        provider = registry.get_active()
    except (RuntimeError, LookupError) as exc:
        logger.exception("Failed to get active provider [request_id=%s]", request_id)
        raise HTTPException(status_code=503, detail="No active provider") from exc

    try:
        result = await provider.embed(texts, model=model)
    except (ConnectionError, TimeoutError) as exc:
        logger.exception("Upstream connection error during embedding [request_id=%s]", request_id)
        raise HTTPException(status_code=502, detail="Upstream provider unavailable") from exc
    except (ValueError, TypeError) as exc:
        logger.exception("Invalid request parameters for embedding [request_id=%s]", request_id)
        raise HTTPException(status_code=400, detail="Invalid request parameters") from exc
    except OSError as exc:
        logger.exception("I/O error during embedding [request_id=%s]", request_id)
        raise HTTPException(status_code=502, detail="Upstream provider unavailable") from exc

    # Normalise result to a list of embedding vectors
    if isinstance(result, list) and len(result) > 0:
        if hasattr(result[0], "embedding"):
            # list[EmbedResponse]
            vectors = [r.embedding for r in result]
            total_tokens = sum(getattr(r, "input_tokens", 0) for r in result)
            model_name = result[0].model
        elif isinstance(result[0], list):
            # list[list[float]]
            vectors = result
            total_tokens = 0
            model_name = model or "unknown"
        else:
            vectors = [result]
            total_tokens = 0
            model_name = model or "unknown"
    elif hasattr(result, "embedding"):
        # Single EmbedResponse
        vectors = [result.embedding]
        total_tokens = getattr(result, "input_tokens", 0)
        model_name = result.model
    else:
        vectors = []
        total_tokens = 0
        model_name = model or "unknown"

    data = [
        {
            "object": "embedding",
            "embedding": vec,
            "index": idx,
        }
        for idx, vec in enumerate(vectors)
    ]

    return {
        "object": "list",
        "data": data,
        "model": model_name,
        "usage": {
            "prompt_tokens": total_tokens,
            "total_tokens": total_tokens,
        },
    }


@router.get("/v1/models")
async def list_models():
    """OpenAI-compatible model listing."""
    request_id = _make_id("models")

    registry = _get_provider_router()
    if registry is None:
        raise HTTPException(status_code=503, detail="No provider available")

    try:
        provider = registry.get_active()
    except (RuntimeError, LookupError):
        logger.exception(
            "Failed to get active provider for model listing [request_id=%s]", request_id
        )
        return {"object": "list", "data": []}

    try:
        models = await provider.list_models()
    except (ConnectionError, TimeoutError, OSError):
        logger.exception("Failed to list models from provider [request_id=%s]", request_id)
        return {"object": "list", "data": []}

    data = []
    for m in models:
        if isinstance(m, dict):
            name = m.get("name", m.get("id", "unknown"))
        else:
            name = getattr(m, "name", str(m))

        data.append(
            {
                "id": name,
                "object": "model",
                "created": _unix_ts(),
                "owned_by": "bmt_ai_os",
                "permission": [],
                "root": name,
                "parent": None,
            }
        )

    return {"object": "list", "data": data}
