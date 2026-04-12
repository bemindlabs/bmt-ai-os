"""Provider registry — register, look up, and switch LLM backends."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from bmt_ai_os.providers.base import ProviderError, ProviderHealth

if TYPE_CHECKING:
    from bmt_ai_os.providers.base import LLMProvider


class ProviderRegistry:
    """Thread-safe registry of :class:`LLMProvider` instances.

    Supports runtime switching of the *active* provider and health-checking
    all registered backends.
    """

    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {}
        self._active_name: str | None = None

    # -- Registration -----------------------------------------------------

    def register(self, name: str, provider: LLMProvider) -> None:
        """Register *provider* under *name*.

        If this is the first provider registered it automatically becomes the
        active provider.
        """
        self._providers[name] = provider
        if self._active_name is None:
            self._active_name = name

    def unregister(self, name: str) -> None:
        """Remove a previously registered provider."""
        self._providers.pop(name, None)
        if self._active_name == name:
            self._active_name = next(iter(self._providers), None)

    # -- Lookup -----------------------------------------------------------

    def get(self, name: str) -> LLMProvider:
        """Return the provider registered under *name*.

        Raises :class:`ProviderError` if not found.
        """
        try:
            return self._providers[name]
        except KeyError:
            raise ProviderError(
                f"Provider '{name}' is not registered. "
                f"Available: {', '.join(self._providers) or '(none)'}"
            ) from None

    def list(self) -> list[str]:
        """Return the names of all registered providers."""
        return list(self._providers)

    def reorder(self, names: list[str]) -> None:
        """Reorder providers according to *names*.

        *names* must contain exactly the same provider names that are currently
        registered (no additions, no omissions). The internal dict is rebuilt in
        the specified order so that :meth:`list` reflects the new priority.

        Raises :class:`ProviderError` if the supplied names do not match the
        currently registered set.
        """
        registered = set(self._providers)
        supplied = set(names)
        if registered != supplied:
            missing = registered - supplied
            extra = supplied - registered
            parts: list[str] = []
            if missing:
                parts.append(f"missing: {', '.join(sorted(missing))}")
            if extra:
                parts.append(f"unknown: {', '.join(sorted(extra))}")
            raise ProviderError(f"Provider name mismatch — {'; '.join(parts)}")
        self._providers = {n: self._providers[n] for n in names}

    # -- Active provider --------------------------------------------------

    def set_active(self, name: str) -> None:
        """Switch the active provider at runtime.

        Raises :class:`ProviderError` if *name* is not registered.
        """
        if name not in self._providers:
            raise ProviderError(
                f"Cannot activate unknown provider '{name}'. "
                f"Registered: {', '.join(self._providers) or '(none)'}"
            )
        self._active_name = name

    def get_active(self) -> LLMProvider:
        """Return the currently active provider.

        Raises :class:`ProviderError` if no provider has been registered.
        """
        if self._active_name is None:
            raise ProviderError("No provider has been registered yet.")
        return self.get(self._active_name)

    @property
    def active_name(self) -> str | None:
        """Name of the currently active provider (or ``None``)."""
        return self._active_name

    # -- Health -----------------------------------------------------------

    async def health_check_all(self) -> dict[str, ProviderHealth]:
        """Run health checks on every registered provider concurrently."""
        if not self._providers:
            return {}

        names = list(self._providers)
        results = await asyncio.gather(
            *(self._providers[n].health_check() for n in names),
            return_exceptions=True,
        )

        out: dict[str, ProviderHealth] = {}
        for name, result in zip(names, results):
            if isinstance(result, BaseException):
                out[name] = ProviderHealth(healthy=False, latency_ms=0.0, error=str(result))
            else:
                out[name] = result
        return out


# ---------------------------------------------------------------------------
# Singleton access
# ---------------------------------------------------------------------------

_global_registry: ProviderRegistry | None = None


def get_registry() -> ProviderRegistry:
    """Return the process-wide :class:`ProviderRegistry` singleton."""
    global _global_registry
    if _global_registry is None:
        _global_registry = ProviderRegistry()
    return _global_registry


def reset_registry() -> None:
    """Reset the global registry (primarily for testing)."""
    global _global_registry
    _global_registry = None
