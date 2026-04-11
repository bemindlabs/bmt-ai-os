"""Plugin lifecycle manager for BMT AI OS.

Tracks enabled/disabled state for discovered plugins in a JSON file and
provides integration with the provider registry for PROVIDER-hook plugins.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from bmt_ai_os.plugins.hooks import PluginHook, PluginInfo
from bmt_ai_os.plugins.loader import Plugin, discover_plugins, load_plugin
from bmt_ai_os.providers.registry import get_registry

if TYPE_CHECKING:
    pass

_DEFAULT_STATE_FILE = "/tmp/bmt-plugins.json"


class PluginManager:
    """Manage the lifecycle (enable / disable / list) of BMT AI OS plugins.

    Plugin enabled/disabled state is persisted to a JSON file so it survives
    process restarts.

    Parameters
    ----------
    state_file:
        Path to the JSON state file.  Defaults to ``/tmp/bmt-plugins.json``.
    """

    def __init__(self, state_file: str = _DEFAULT_STATE_FILE) -> None:
        self._state_path = Path(state_file)
        self._lock = threading.Lock()
        # name -> enabled
        self._state: dict[str, bool] = self._load_state()

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> dict[str, bool]:
        """Read persisted state from disk; return empty dict on any error."""
        if not self._state_path.exists():
            return {}
        try:
            raw = self._state_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                return {k: bool(v) for k, v in data.items()}
        except (json.JSONDecodeError, OSError):
            pass
        return {}

    def _save_state(self) -> None:
        """Persist current enabled/disabled state to disk atomically.

        Writes to a temporary file in the same directory then renames it into
        place so that a concurrent reader never sees a partial write.  Must be
        called while ``self._lock`` is held.
        """
        try:
            dir_path = self._state_path.parent
            dir_path.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(self._state, fh, indent=2)
                os.replace(tmp_path, self._state_path)
            except Exception:
                # Clean up the temp file on any error before re-raising.
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError:
            # Non-fatal — e.g. read-only filesystem.
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_plugins(self) -> list[PluginInfo]:
        """Return metadata for all discovered plugins with current enabled state.

        Calls :func:`~bmt_ai_os.plugins.loader.discover_plugins` on every
        invocation so that newly installed packages are picked up without a
        restart.
        """
        infos = discover_plugins()
        for info in infos:
            # Override the default (True) with persisted state if present.
            if info.name in self._state:
                info.enabled = self._state[info.name]
        return infos

    def enable(self, name: str) -> None:
        """Enable plugin *name*.

        Raises
        ------
        KeyError
            If no plugin with *name* is discoverable.
        """
        self._assert_exists(name)
        with self._lock:
            self._state[name] = True
            self._save_state()

    def disable(self, name: str) -> None:
        """Disable plugin *name*.

        Raises
        ------
        KeyError
            If no plugin with *name* is discoverable.
        """
        self._assert_exists(name)
        with self._lock:
            self._state[name] = False
            self._save_state()

    def is_enabled(self, name: str) -> bool:
        """Return whether plugin *name* is currently enabled."""
        if name in self._state:
            return self._state[name]
        # Unknown plugins default to enabled once discovered.
        return True

    def register_provider_plugin(self, plugin: Plugin) -> None:
        """Load *plugin* and register it with the global :class:`ProviderRegistry`.

        Only plugins whose ``hook_type`` is :attr:`PluginHook.PROVIDER` are
        registered.  All others are silently ignored.

        The plugin instance is registered under its ``name`` attribute.
        """
        hook_type = getattr(plugin, "hook_type", None)
        if hook_type != PluginHook.PROVIDER:
            return

        registry = get_registry()

        # Provider plugins must expose an LLMProvider via .provider attribute
        # or be directly usable as one.
        provider = getattr(plugin, "provider", plugin)
        registry.register(plugin.name, provider)  # type: ignore[arg-type]

    def load_and_register_providers(self) -> list[str]:
        """Discover, load, and register all enabled PROVIDER plugins.

        Returns the names of successfully registered plugins.
        """
        registered: list[str] = []
        for info in self.list_plugins():
            if not info.enabled or info.hook_type != PluginHook.PROVIDER:
                continue
            try:
                plugin = load_plugin(info.name)
                self.register_provider_plugin(plugin)
                registered.append(info.name)
            except Exception:
                # Individual plugin failures must not abort the startup sequence.
                pass
        return registered

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _assert_exists(self, name: str) -> None:
        """Raise KeyError if *name* is not among the discovered plugins."""
        known = {info.name for info in discover_plugins()}
        if name not in known:
            available = ", ".join(sorted(known)) or "(none)"
            raise KeyError(f"Plugin '{name}' not found. Discoverable plugins: {available}")
