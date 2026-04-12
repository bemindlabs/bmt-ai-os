"""FastAPI routes for the LLM provider abstraction layer."""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from bmt_ai_os.providers.base import ChatMessage, ModelNotFoundError, ProviderError, ProviderHealth
from bmt_ai_os.providers.registry import get_registry

router = APIRouter(prefix="/api/v1/providers", tags=["providers"])

# ---------------------------------------------------------------------------
# Per-provider health history (in-memory, last 5 checks per provider)
# ---------------------------------------------------------------------------

#: provider_name → deque of (timestamp, latency_ms, healthy, error|None)
_health_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=5))

#: provider_name → (timestamp, error_count, cooldown_until)
_error_state: dict[str, dict] = defaultdict(lambda: {"count": 0, "cooldown_until": 0.0})

#: provider_name → timestamp of last successful credential use
_last_success_ts: dict[str, float] = {}

_COOLDOWN_SECONDS = 60.0


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
    """List all registered providers with health status and trend data."""
    from bmt_ai_os.controller.discovery import _CANDIDATE_PORTS

    registry = get_registry()
    names = registry.list()
    health_map = await registry.health_check_all()

    # Determine which providers were auto-discovered (match port/type mapping)
    discovered_types = {pt for _, pt, _, _, _ in _CANDIDATE_PORTS}

    now = time.time()
    providers = []
    for name in names:
        health = health_map.get(name)
        healthy = health.healthy if isinstance(health, ProviderHealth) else bool(health)
        latency = health.latency_ms if isinstance(health, ProviderHealth) else 0.0
        error = health.error if isinstance(health, ProviderHealth) else None

        # Record health check in history
        _health_history[name].append(
            {"ts": now, "latency_ms": latency, "healthy": healthy, "error": error}
        )

        # Track error state and cooldown
        estate = _error_state[name]
        if healthy:
            _last_success_ts[name] = now
            estate["count"] = 0
            estate["cooldown_until"] = 0.0
        else:
            estate["count"] = estate.get("count", 0) + 1
            estate["cooldown_until"] = now + _COOLDOWN_SECONDS

        cooldown_remaining = max(0.0, estate["cooldown_until"] - now)

        # Provider is "discovered" if its name matches a known auto-discovery type
        provider_type = name.split("-")[0]  # strip port suffix if present
        is_discovered = provider_type in discovered_types

        providers.append(
            {
                "name": name,
                "active": name == registry.active_name,
                "discovered": is_discovered,
                "health": health.to_dict()
                if isinstance(health, ProviderHealth)
                else {"healthy": bool(health)}
                if health is not None
                else None,
                "latency_history": [h["latency_ms"] for h in _health_history[name]],
                "error_count": estate["count"],
                "cooldown_remaining_s": round(cooldown_remaining, 1),
                "last_success_ts": _last_success_ts.get(name),
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
        raise HTTPException(status_code=503, detail=str(exc)) from exc
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"order": registry.list()}


@router.post("/active")
async def set_active_provider(body: SetActiveRequest):
    """Switch the active provider at runtime."""
    registry = get_registry()
    try:
        registry.set_active(body.name)
    except ProviderError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"active_provider": body.name}


@router.post("/{name}/chat")
async def chat_with_provider(name: str, body: ChatRequest):
    """Send a chat request to a specific provider."""
    registry = get_registry()
    try:
        provider = registry.get(name)
    except ProviderError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

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
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return response.to_dict()


@router.get("/discover")
async def discover_providers():
    """Scan local ports for LLM inference endpoints and auto-register new ones.

    Scans ports 11434 (Ollama), 8001 (vLLM), and 8002 (llama.cpp).
    Providers that are reachable but not yet registered are automatically
    registered and returned with ``registered_now: true``.
    """
    from bmt_ai_os.controller.discovery import run_discovery

    discovered = await run_discovery()
    return {
        "discovered": [d.to_dict() for d in discovered],
        "count": len(discovered),
    }


@router.get("/{name}/models")
async def list_provider_models(name: str):
    """List models available on a specific provider."""
    registry = get_registry()
    try:
        provider = registry.get(name)
    except ProviderError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        models = await provider.list_models()
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"models": [m.to_dict() for m in models]}
