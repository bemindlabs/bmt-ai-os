"""Provider auto-discovery — scan common local ports and register providers.

Scans well-known local inference ports on controller startup and on demand.
Any reachable endpoint that is not already registered gets auto-registered.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import aiohttp

logger = logging.getLogger("bmt-controller.discovery")

# ---------------------------------------------------------------------------
# Known local provider endpoints
# ---------------------------------------------------------------------------

#: (port, provider_type, health_path, module_path, class_name)
_CANDIDATE_PORTS: list[tuple[int, str, str, str, str]] = [
    (11434, "ollama", "/api/tags", "bmt_ai_os.providers.ollama", "OllamaProvider"),
    (8001, "vllm", "/health", "bmt_ai_os.providers.vllm", "VLLMProvider"),
    (8002, "llamacpp", "/health", "bmt_ai_os.providers.llamacpp", "LlamaCppProvider"),
]

_CONNECT_TIMEOUT = aiohttp.ClientTimeout(total=2.0)


@dataclass
class DiscoveredProvider:
    """Metadata for a provider found during port scanning."""

    name: str
    port: int
    base_url: str
    provider_type: str
    latency_ms: float
    already_registered: bool = False
    registered_now: bool = False
    error: str | None = None
    discovered_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "port": self.port,
            "base_url": self.base_url,
            "provider_type": self.provider_type,
            "latency_ms": round(self.latency_ms, 2),
            "already_registered": self.already_registered,
            "registered_now": self.registered_now,
            "discovered": True,
            "error": self.error,
            "discovered_at": self.discovered_at,
        }


# ---------------------------------------------------------------------------
# Scan logic
# ---------------------------------------------------------------------------


async def _probe_port(port: int, health_path: str) -> tuple[bool, float, str | None]:
    """Attempt an HTTP GET to *health_path* on localhost:*port*.

    Returns (reachable, latency_ms, error_message).
    """
    url = f"http://localhost:{port}{health_path}"
    start = time.perf_counter()
    try:
        async with aiohttp.ClientSession(timeout=_CONNECT_TIMEOUT) as session:
            async with session.get(url) as resp:
                latency_ms = (time.perf_counter() - start) * 1000
                if resp.status < 500:
                    return True, latency_ms, None
                return False, latency_ms, f"HTTP {resp.status}"
    except aiohttp.ClientConnectorError:
        latency_ms = (time.perf_counter() - start) * 1000
        return False, latency_ms, "connection refused"
    except Exception as exc:  # noqa: BLE001
        latency_ms = (time.perf_counter() - start) * 1000
        return False, latency_ms, str(exc)


async def scan_local_providers() -> list[DiscoveredProvider]:
    """Scan all candidate ports and return discovered providers."""
    results: list[DiscoveredProvider] = []
    for port, provider_type, health_path, _mod, _cls in _CANDIDATE_PORTS:
        reachable, latency_ms, error = await _probe_port(port, health_path)
        if not reachable:
            logger.debug("Port %d (%s) not reachable: %s", port, provider_type, error)
            continue

        base_url = f"http://localhost:{port}"
        # Disambiguate names if multiple instances could exist on different ports
        name = provider_type if port == _CANDIDATE_PORTS[0][0] else f"{provider_type}-{port}"
        results.append(
            DiscoveredProvider(
                name=name,
                port=port,
                base_url=base_url,
                provider_type=provider_type,
                latency_ms=latency_ms,
                error=error,
            )
        )
        logger.info("Discovered %s at %s (%.0fms)", provider_type, base_url, latency_ms)

    return results


async def auto_register_discovered(discovered: list[DiscoveredProvider]) -> None:
    """Register any discovered providers not already in the global registry."""
    import importlib

    from bmt_ai_os.providers.registry import get_registry

    registry = get_registry()
    registered_names = set(registry.list())

    # Build a lookup from provider_type → (module_path, class_name)
    type_map: dict[str, tuple[str, str]] = {
        pt: (mod, cls) for _, pt, _, mod, cls in _CANDIDATE_PORTS
    }

    for item in discovered:
        item.already_registered = item.name in registered_names
        if item.already_registered:
            logger.debug("Provider '%s' already registered — skipping", item.name)
            continue

        mapping = type_map.get(item.provider_type)
        if mapping is None:
            logger.warning("No provider class for type '%s'", item.provider_type)
            continue

        module_path, class_name = mapping
        try:
            module = importlib.import_module(module_path)
            provider_cls = getattr(module, class_name)
            provider = provider_cls(base_url=item.base_url)
            registry.register(item.name, provider)
            item.registered_now = True
            logger.info(
                "Auto-registered discovered provider '%s' (%s) at %s",
                item.name,
                class_name,
                item.base_url,
            )
        except (ImportError, AttributeError, TypeError, ValueError, OSError) as exc:
            item.error = str(exc)
            logger.warning("Failed to auto-register '%s': %s", item.name, exc)


async def run_discovery() -> list[DiscoveredProvider]:
    """Scan local ports, auto-register new providers, and return results."""
    discovered = await scan_local_providers()
    await auto_register_discovered(discovered)
    return discovered
