"""FastAPI routes for the LLM provider abstraction layer."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from bmt_ai_os.providers.base import ChatMessage, ModelNotFoundError, ProviderError, ProviderHealth
from bmt_ai_os.providers.registry import get_registry

router = APIRouter(prefix="/api/v1/providers", tags=["providers"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class SetActiveRequest(BaseModel):
    name: str


class FallbackOrderRequest(BaseModel):
    order: list[str]


class ChatRequest(BaseModel):
    messages: list[dict]  # [{"role": "user", "content": "..."}]
    model: str | None = None
    temperature: float = 0.7
    max_tokens: int = 2048


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("")
async def list_providers():
    """List all registered providers with their health status."""
    registry = get_registry()
    names = registry.list()
    health_map = await registry.health_check_all()

    providers = []
    for name in names:
        health = health_map.get(name)
        providers.append(
            {
                "name": name,
                "active": name == registry.active_name,
                "health": health.to_dict()
                if isinstance(health, ProviderHealth)
                else {"healthy": bool(health)}
                if health is not None
                else None,
            }
        )
    return {"providers": providers}


@router.get("/active")
async def get_active_provider():
    """Return the currently active provider."""
    registry = get_registry()
    try:
        provider = registry.get_active()
    except ProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    health = await provider.health_check()
    return {
        "name": provider.name,
        "health": health.to_dict()
        if isinstance(health, ProviderHealth)
        else {"healthy": bool(health)},
    }


@router.put("/fallback-order")
async def set_fallback_order(body: FallbackOrderRequest):
    """Persist the fallback chain order (priority index 0 = highest priority)."""
    registry = get_registry()
    try:
        registry.reorder(body.order)
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"order": registry.list()}


@router.post("/active")
async def set_active_provider(body: SetActiveRequest):
    """Switch the active provider at runtime."""
    registry = get_registry()
    try:
        registry.set_active(body.name)
    except ProviderError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"active_provider": body.name}


@router.post("/{name}/chat")
async def chat_with_provider(name: str, body: ChatRequest):
    """Send a chat request to a specific provider."""
    registry = get_registry()
    try:
        provider = registry.get(name)
    except ProviderError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    messages = [ChatMessage(role=m["role"], content=m["content"]) for m in body.messages]

    try:
        response = await provider.chat(
            messages,
            model=body.model,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            stream=False,
        )
    except ModelNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return response.to_dict()


@router.get("/{name}/models")
async def list_provider_models(name: str):
    """List models available on a specific provider."""
    registry = get_registry()
    try:
        provider = registry.get(name)
    except ProviderError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    try:
        models = await provider.list_models()
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return {"models": [m.to_dict() for m in models]}
