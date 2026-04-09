"""Provider registry — register, look-up, and enumerate LLM providers."""

from __future__ import annotations

from bmt_ai_os.providers.base import LLMProvider


class ProviderNotFoundError(Exception):
    """Raised when a requested provider is not registered."""


class ProviderRegistry:
    """Thread-safe registry of LLM provider instances."""

    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {}
        self._active: str | None = None

    # ------------------------------------------------------------------ #
    # Registration
    # ------------------------------------------------------------------ #
    def register(self, name: str, provider: LLMProvider) -> None:
        self._providers[name] = provider
        if self._active is None:
            self._active = name

    def unregister(self, name: str) -> None:
        self._providers.pop(name, None)
        if self._active == name:
            self._active = next(iter(self._providers), None)

    # ------------------------------------------------------------------ #
    # Look-up
    # ------------------------------------------------------------------ #
    def get(self, name: str) -> LLMProvider:
        try:
            return self._providers[name]
        except KeyError:
            raise ProviderNotFoundError(f"Provider '{name}' not registered")

    def get_active(self) -> LLMProvider | None:
        if self._active is None:
            return None
        return self._providers.get(self._active)

    def set_active(self, name: str) -> None:
        if name not in self._providers:
            raise ProviderNotFoundError(f"Provider '{name}' not registered")
        self._active = name

    @property
    def active_name(self) -> str | None:
        return self._active

    def list_providers(self) -> list[str]:
        return list(self._providers.keys())

    # ------------------------------------------------------------------ #
    # Health
    # ------------------------------------------------------------------ #
    async def health_check_all(self) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for name, provider in self._providers.items():
            try:
                results[name] = await provider.health_check()
            except Exception:
                results[name] = False
        return results
