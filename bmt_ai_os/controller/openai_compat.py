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
import os
import re
import time
import uuid
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .rate_limit import inference_rate_limit

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Persona injection helpers
# ---------------------------------------------------------------------------


def _persona_enabled() -> bool:
    """Return True when persona auto-injection is enabled (default: on)."""
    return os.getenv("BMT_PERSONA_ENABLED", "1").lower() not in ("0", "false", "no")


def _has_system_message(messages: list[Any]) -> bool:
    """Return True when the first message carries the 'system' role."""
    if not messages:
        return False
    first = messages[0]
    role = getattr(first, "role", None) or (first.get("role") if isinstance(first, dict) else None)
    return role == "system"


async def _inject_persona(messages: list[Any]) -> list[Any]:
    """Prepend the assembled persona as a system message when none is present.

    Returns *messages* unchanged when:
    - A system message is already present (client owns the system prompt).
    - Persona injection is disabled via ``BMT_PERSONA_ENABLED=0``.
    - The assembler returns an empty string.

    Never raises — persona errors must not break the chat flow.
    """
    if _has_system_message(messages):
        return messages

    if not _persona_enabled():
        return messages

    try:
        from bmt_ai_os.persona.assembler import get_persona_assembler

        assembler = get_persona_assembler()
        system_content = assembler.assemble()
        if not system_content:
            return messages

        try:
            from bmt_ai_os.providers.base import ChatMessage

            injected = ChatMessage(role="system", content=system_content)
        except Exception:
            injected = _ChatMessage(role="system", content=system_content)

        logger.debug("Persona injected (%d chars)", len(system_content))
        return [injected, *messages]

    except Exception as exc:
        logger.warning("Persona injection failed (non-fatal): %s", exc)
        return messages


# ---------------------------------------------------------------------------
# RAG injection helpers
# ---------------------------------------------------------------------------


def _rag_enabled() -> bool:
    """Return True when RAG auto-injection is enabled via env var."""
    return os.getenv("BMT_RAG_ENABLED", "").lower() in ("1", "true", "yes")


async def _inject_rag_context(messages: list[Any]) -> list[Any]:
    """Prepend a RAG-retrieved context system message to *messages*.

    Queries ChromaDB using the last user message as the search query.
    Returns the original list unchanged when RAG is unavailable or returns
    no useful results, so the behaviour is always non-breaking.

    Parameters
    ----------
    messages:
        List of ChatMessage-like objects (must have ``.role`` and ``.content``).

    Returns
    -------
    list
        Augmented list with a prepended system message, or the original list.
    """
    # Find the last user message to use as the RAG query
    query_text = ""
    for msg in reversed(messages):
        role = getattr(msg, "role", None) or (msg.get("role") if isinstance(msg, dict) else None)
        content = getattr(msg, "content", None) or (
            msg.get("content") if isinstance(msg, dict) else None
        )
        if role == "user" and content:
            query_text = content
            break

    if not query_text:
        return messages

    try:
        from bmt_ai_os.rag.config import RAGConfig
        from bmt_ai_os.rag.storage import ChromaStorage

        config = RAGConfig()
        storage = ChromaStorage(config)
        raw = storage.query("default", query_text, top_k=3)

        documents = (raw.get("documents") or [[]])[0]
        if not documents:
            return messages

        context_text = "\n\n".join(
            f"[Context {i + 1}]\n{doc}" for i, doc in enumerate(documents) if doc
        )
        if not context_text.strip():
            return messages

        system_content = (
            "Use the following retrieved context to help answer the user's question.\n\n"
            f"{context_text}"
        )

        # Build an injected system message using the same type as existing messages
        try:
            from bmt_ai_os.providers.base import ChatMessage

            injected = ChatMessage(role="system", content=system_content)
        except Exception:
            injected = _ChatMessage(role="system", content=system_content)

        logger.debug(
            "RAG injection: prepended context from %d chunk(s) for query: %.80s",
            len(documents),
            query_text,
        )
        return [injected, *messages]

    except Exception as exc:
        # RAG errors must never break the chat flow
        logger.warning("RAG auto-injection failed (non-fatal): %s", exc)
        return messages


router = APIRouter(tags=["openai-compat"])


# ---------------------------------------------------------------------------
# Request / response schemas (OpenAI-compatible)
# ---------------------------------------------------------------------------


class ChatMessageIn(BaseModel):
    role: str
    content: str
    name: str | None = None


class ToolFunctionParameters(BaseModel):
    """JSON Schema object describing function parameters."""

    type: str = "object"
    properties: dict[str, Any] = {}
    required: list[str] = []


class ToolFunction(BaseModel):
    """Definition of a callable function exposed as a tool."""

    name: str
    description: str = ""
    parameters: ToolFunctionParameters = ToolFunctionParameters()


class Tool(BaseModel):
    """An OpenAI-style tool wrapping a function definition."""

    type: str = "function"
    function: ToolFunction


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
    # Tool / function-calling fields (OpenAI spec)
    tools: list[Tool] | None = None
    tool_choice: str | dict[str, Any] | None = None


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
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
        finish_reason = "tool_calls"

    return {
        "id": _make_id("chatcmpl"),
        "object": "chat.completion",
        "created": _unix_ts(),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


# ---------------------------------------------------------------------------
# Tool / function-calling helpers
# ---------------------------------------------------------------------------


def _provider_supports_tools(provider: Any) -> bool:
    """Return True when *provider* declares native tool/function-calling support."""
    # Check for an explicit attribute or method
    supports = getattr(provider, "supports_tools", False)
    if callable(supports):
        return bool(supports())
    return bool(supports)


def _tools_to_system_message(tools: list[Tool]) -> str:
    """Serialise *tools* into a prose system message for providers that lack
    native tool support.

    The model is instructed to emit a structured JSON block so we can parse
    the call back out of the plain-text response.
    """
    lines = [
        "You have access to the following functions. "
        "When you need to call a function, respond ONLY with a JSON code block "
        "in the following format and nothing else:\n",
        "```json",
        '{"name": "<function_name>", "arguments": {<arg_key>: <arg_value>}}',
        "```\n",
        "Available functions:",
    ]
    for tool in tools:
        fn = tool.function
        params_desc = ", ".join(
            f"{k}: {v.get('type', 'any')}" for k, v in fn.parameters.properties.items()
        )
        lines.append(f"- {fn.name}({params_desc}): {fn.description}")

    return "\n".join(lines)


_TOOL_CALL_RE = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```",
    re.DOTALL | re.IGNORECASE,
)


def _parse_tool_call_from_text(text: str) -> list[dict[str, Any]] | None:
    """Try to extract a function call JSON block from a model's plain-text reply.

    Returns a list of OpenAI-style tool_call objects, or None if no call was
    found.
    """
    match = _TOOL_CALL_RE.search(text)
    if not match:
        return None

    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None

    fn_name = payload.get("name")
    fn_args = payload.get("arguments", {})
    if not fn_name:
        return None

    return [
        {
            "id": f"call_{uuid.uuid4().hex[:16]}",
            "type": "function",
            "function": {
                "name": fn_name,
                "arguments": json.dumps(fn_args),
            },
        }
    ]


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
        return _ChatMessage(role=role, content=content)


def _get_provider_router():
    """Lazy import to avoid circular deps; returns the provider router singleton.

    Falls back to the provider registry when the router is not initialised.
    """
    try:
        from bmt_ai_os.providers.registry import get_registry

        return get_registry()
    except ImportError:
        logger.exception("Provider registry import failed")
        return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/v1/chat/completions", dependencies=[Depends(inference_rate_limit)])
async def chat_completions(body: ChatCompletionRequest, request: Request):
    """OpenAI-compatible chat completions with optional SSE streaming.

    Supports the ``tools`` / ``tool_choice`` parameters (OpenAI function-calling
    spec).  When the active provider declares ``supports_tools = True`` the tools
    list is forwarded directly; otherwise a fallback system-message strategy is
    used and the model's text response is parsed for embedded JSON tool calls.
    """
    registry = _get_provider_router()
    if registry is None:
        raise HTTPException(status_code=503, detail="No provider available")

    messages = [_make_chat_message(m.role, m.content) for m in body.messages]
    model = body.model if body.model != "default" else None
    max_tokens = body.max_tokens or 4096

    # Persona auto-injection (opt-out via BMT_PERSONA_ENABLED=0)
    messages = await _inject_persona(messages)

    # RAG auto-injection (opt-in via BMT_RAG_ENABLED=true)
    if _rag_enabled():
        messages = await _inject_rag_context(messages)

    try:
        provider = registry.get_active()
    except (RuntimeError, LookupError) as exc:
        logger.warning("No active provider available: %s", exc)
        raise HTTPException(status_code=503, detail="No active provider")

    # ---- Tool / function-calling pre-processing ----------------------------
    tools = body.tools or []
    native_tools = False  # whether provider handles tools natively

    if tools:
        if _provider_supports_tools(provider):
            native_tools = True
            logger.debug(
                "Provider %s supports tools natively — forwarding %d tools",
                provider.name,
                len(tools),
            )
        else:
            # Fallback: inject a system message describing the functions
            tool_system_msg = _make_chat_message("system", _tools_to_system_message(tools))
            messages = [tool_system_msg, *messages]
            logger.debug(
                "Provider %s does not support tools — injected fallback system message",
                provider.name,
            )
    # -----------------------------------------------------------------------

    if body.stream:
        # Streaming does not support tool_calls in the current implementation;
        # fall back to streaming without tool detection for simplicity.
        try:
            stream = await provider.chat(
                messages,
                model=model,
                temperature=body.temperature,
                max_tokens=max_tokens,
                stream=True,
            )
        except (RuntimeError, OSError, ConnectionError, TimeoutError) as exc:
            logger.exception("Streaming chat failed")
            raise HTTPException(status_code=502, detail=str(exc))

        request_id = _make_id("chatcmpl")
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
    chat_kwargs: dict[str, Any] = {
        "model": model,
        "temperature": body.temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if native_tools:
        # Pass tools through to provider as-is (provider-specific handling)
        chat_kwargs["tools"] = [t.model_dump() for t in tools]
        if body.tool_choice is not None:
            chat_kwargs["tool_choice"] = body.tool_choice

    try:
        response = await provider.chat(messages, **chat_kwargs)
    except (RuntimeError, OSError, ConnectionError, TimeoutError) as exc:
        logger.exception("Chat completion failed")
        raise HTTPException(status_code=502, detail=str(exc))

    prompt_tokens = getattr(response, "input_tokens", 0) or getattr(response, "prompt_tokens", 0)
    completion_tokens = getattr(response, "output_tokens", 0) or getattr(
        response, "completion_tokens", 0
    )

    # ---- Tool-call extraction -------------------------------------------
    tool_calls: list[dict[str, Any]] | None = None

    if tools:
        if native_tools:
            # Provider may embed tool_calls in response.raw or a dedicated field
            raw_tool_calls = getattr(response, "tool_calls", None) or (
                response.raw.get("tool_calls") if isinstance(response.raw, dict) else None
            )
            if raw_tool_calls:
                tool_calls = raw_tool_calls
        else:
            # Parse tool call from plain-text response
            tool_calls = _parse_tool_call_from_text(response.content)

    return _build_chat_response(
        content=response.content,
        model=response.model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        tool_calls=tool_calls,
    )


@router.post("/v1/completions", dependencies=[Depends(inference_rate_limit)])
async def completions(body: CompletionRequest, request: Request):
    """OpenAI-compatible legacy completions (used by Copilot for code completion)."""
    registry = _get_provider_router()
    if registry is None:
        raise HTTPException(status_code=503, detail="No provider available")

    # Convert prompt to a chat message (single-turn)
    prompt = body.prompt if isinstance(body.prompt, str) else "\n".join(body.prompt)
    messages = [_make_chat_message("user", prompt)]

    try:
        provider = registry.get_active()
    except (RuntimeError, LookupError) as exc:
        logger.warning("No active provider available: %s", exc)
        raise HTTPException(status_code=503, detail="No active provider")

    if body.stream:
        try:
            stream = await provider.chat(
                messages,
                model=body.model if body.model != "default" else None,
                temperature=body.temperature,
                max_tokens=body.max_tokens,
                stream=True,
            )
        except (RuntimeError, OSError, ConnectionError, TimeoutError) as exc:
            logger.exception("Streaming completions failed")
            raise HTTPException(status_code=502, detail=str(exc))

        request_id = _make_id("cmpl")
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
    except (RuntimeError, OSError, ConnectionError, TimeoutError) as exc:
        logger.exception("Completions (non-streaming) failed")
        raise HTTPException(status_code=502, detail=str(exc))

    prompt_tokens = getattr(response, "input_tokens", 0) or getattr(response, "prompt_tokens", 0)
    completion_tokens = getattr(response, "output_tokens", 0) or getattr(
        response, "completion_tokens", 0
    )

    return _build_completion_response(
        text=response.content,
        model=response.model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


@router.post("/v1/embeddings")
async def embeddings(body: EmbeddingRequest):
    """OpenAI-compatible embeddings endpoint (used by Cody for RAG)."""
    registry = _get_provider_router()
    if registry is None:
        raise HTTPException(status_code=503, detail="No provider available")

    texts = body.input if isinstance(body.input, list) else [body.input]
    model = body.model if body.model != "default" else None

    try:
        provider = registry.get_active()
    except (RuntimeError, LookupError) as exc:
        logger.warning("No active provider available: %s", exc)
        raise HTTPException(status_code=503, detail="No active provider")

    try:
        result = await provider.embed(texts, model=model)
    except (RuntimeError, OSError, ConnectionError, TimeoutError) as exc:
        logger.exception("Embedding failed")
        raise HTTPException(status_code=502, detail=str(exc))

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
    registry = _get_provider_router()
    if registry is None:
        raise HTTPException(status_code=503, detail="No provider available")

    try:
        provider = registry.get_active()
    except Exception as exc:
        logger.warning("No active provider for model listing: %s", exc)
        return {"object": "list", "data": []}

    try:
        models = await provider.list_models()
    except (RuntimeError, OSError, ConnectionError, TimeoutError) as exc:
        logger.warning("Failed to list models from provider: %s", exc)
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
