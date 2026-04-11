"""Plugin lifecycle manager for BMT AI OS.

Tracks enabled/disabled/installed state for discovered plugins in a JSON
file and provides integration with the provider registry for PROVIDER-hook
plugins.

Lifecycle states
----------------
* **discovered** — plugin.yml exists in the plugin directory (or entry-point
  registered) but has not been explicitly installed.
* **installed** — the plugin has been registered in the state file via
  :meth:`PluginManager.install`.  Enabled by default on install.
* **enabled** — plugin will be loaded and activated at startup.
* **disabled** — plugin is installed but will not be loaded.
* **uninstalled** — plugin has been removed from the state file.  The
  manifest file on disk is NOT deleted (that would require OS permissions).

Sandboxing
----------
Plugin code is executed inside a :func:`_sandboxed_call` wrapper that catches
all exceptions and enforces a per-call timeout via a background thread.  This
prevents a misbehaving plugin from crashing the controller process.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from bmt_ai_os.plugins.hooks import PluginHook, PluginInfo
from bmt_ai_os.plugins.loader import Plugin, discover_plugins, load_plugin
from bmt_ai_os.providers.registry import get_registry

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_DEFAULT_STATE_FILE = "/tmp/bmt-plugins.json"
_DEFAULT_PLUGIN_DIR = "/opt/bmt/plugins"
_SANDBOX_TIMEOUT_SECONDS = 5


# ---------------------------------------------------------------------------
# Sandboxed execution helper
# ---------------------------------------------------------------------------


def _sandboxed_call(
    fn: Callable[..., Any],
    *args: Any,
    timeout: float = _SANDBOX_TIMEOUT_SECONDS,
    **kwargs: Any,
) -> Any:
    """Call *fn* with *args*/*kwargs* inside a sandboxed thread.

    Catches all exceptions so that a misbehaving plugin cannot crash the
    controller.  Returns the function's return value on success, or ``None``
    on failure / timeout.

    Parameters
    ----------
    fn:
        Callable to invoke.
    timeout:
        Wall-clock deadline in seconds.  Defaults to
        ``_SANDBOX_TIMEOUT_SECONDS``.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn, *args, **kwargs)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            logger.warning("Plugin call %s timed out after %ss", fn, timeout)
            return None
        except Exception as exc:
            logger.warning("Plugin call %s raised: %s", fn, exc)
            return None


# ---------------------------------------------------------------------------
# PluginManager
# ---------------------------------------------------------------------------

_STATE_LOCK = threading.Lock()


class PluginManager:
    """Manage the lifecycle (install / enable / disable / uninstall / list)
    of BMT AI OS plugins.

    Plugin state is persisted to a JSON file so it survives process restarts.

    Parameters
    ----------
    state_file:
        Path to the JSON state file.  Defaults to ``/tmp/bmt-plugins.json``.
    plugin_dir:
        Directory scanned for ``plugin.yml`` manifests.  Defaults to
        ``/opt/bmt/plugins``.
    """

    def __init__(
        self,
        state_file: str = _DEFAULT_STATE_FILE,
        plugin_dir: str = _DEFAULT_PLUGIN_DIR,
    ) -> None:
        self._state_path = Path(state_file)
        self._plugin_dir = plugin_dir
        # name -> {"enabled": bool, "installed": bool}
        self._state: dict[str, dict[str, Any]] = self._load_state()

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> dict[str, dict[str, Any]]:
        """Read persisted state from disk; return empty dict on any error."""
        if not self._state_path.exists():
            return {}
        try:
            raw = self._state_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                # Support legacy format where value was bool (enabled flag only)
                result: dict[str, dict[str, Any]] = {}
                for k, v in data.items():
                    if isinstance(v, bool):
                        result[k] = {"enabled": v, "installed": True}
                    elif isinstance(v, dict):
                        result[k] = {
                            "enabled": bool(v.get("enabled", True)),
                            "installed": bool(v.get("installed", True)),
                        }
                return result
        except (json.JSONDecodeError, OSError):
            pass
        return {}

    def _save_state(self) -> None:
        """Persist current enabled/disabled state to disk."""
        with _STATE_LOCK:
            try:
                self._state_path.write_text(
                    json.dumps(self._state, indent=2),
                    encoding="utf-8",
                )
            except OSError:
                # Non-fatal — e.g. read-only filesystem.
                pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_entry(self, name: str) -> dict[str, Any]:
        return self._state.setdefault(name, {"enabled": True, "installed": False})

    def _discovered_names(self) -> set[str]:
        return {info.name for info in discover_plugins(plugin_dir=self._plugin_dir)}

    def _assert_exists(self, name: str) -> None:
        """Raise KeyError if *name* is not among the discovered plugins."""
        known = self._discovered_names()
        if name not in known:
            available = ", ".join(sorted(known)) or "(none)"
            raise KeyError(f"Plugin '{name}' not found. Discoverable plugins: {available}")

    # ------------------------------------------------------------------
    # Lifecycle: install / uninstall
    # ------------------------------------------------------------------

    def install(self, name: str) -> None:
        """Mark plugin *name* as installed and enabled.

        The plugin manifest must already exist in *plugin_dir* or be registered
        as an entry-point.

        Raises
        ------
        KeyError
            If the plugin is not discoverable.
        """
        self._assert_exists(name)
        self._state[name] = {"enabled": True, "installed": True}
        self._save_state()
        logger.info("Plugin '%s' installed", name)

    def uninstall(self, name: str) -> None:
        """Remove plugin *name* from the state registry.

        The manifest file on disk is not deleted — only the in-process state
        entry is removed.

        Raises
        ------
        KeyError
            If the plugin is not currently installed.
        """
        if name not in self._state:
            raise KeyError(f"Plugin '{name}' is not installed.")
        del self._state[name]
        self._save_state()
        logger.info("Plugin '%s' uninstalled", name)

    def is_installed(self, name: str) -> bool:
        """Return whether plugin *name* has been explicitly installed."""
        entry = self._state.get(name)
        if entry is None:
            return False
        return bool(entry.get("installed", False))

    # ------------------------------------------------------------------
    # Lifecycle: enable / disable
    # ------------------------------------------------------------------

    def enable(self, name: str) -> None:
        """Enable plugin *name*.

        Raises
        ------
        KeyError
            If no plugin with *name* is discoverable.
        """
        self._assert_exists(name)
        entry = self._get_entry(name)
        entry["enabled"] = True
        entry["installed"] = True
        self._save_state()

    def disable(self, name: str) -> None:
        """Disable plugin *name*.

        Raises
        ------
        KeyError
            If no plugin with *name* is discoverable.
        """
        self._assert_exists(name)
        entry = self._get_entry(name)
        entry["enabled"] = False
        entry["installed"] = entry.get("installed", True)
        self._save_state()

    def is_enabled(self, name: str) -> bool:
        """Return whether plugin *name* is currently enabled."""
        entry = self._state.get(name)
        if entry is None:
            # Unknown plugins default to enabled once discovered.
            return True
        return bool(entry.get("enabled", True))

    # ------------------------------------------------------------------
    # Discovery and listing
    # ------------------------------------------------------------------

    def list_plugins(self) -> list[PluginInfo]:
        """Return metadata for all discovered plugins with current enabled state.

        Calls :func:`~bmt_ai_os.plugins.loader.discover_plugins` on every
        invocation so that newly installed packages are picked up without a
        restart.
        """
        infos = discover_plugins(plugin_dir=self._plugin_dir)
        for info in infos:
            entry = self._state.get(info.name)
            if entry is not None:
                info.enabled = bool(entry.get("enabled", True))
        return infos

    def get_plugin_info(self, name: str) -> PluginInfo:
        """Return :class:`PluginInfo` for plugin *name*.

        Raises
        ------
        KeyError
            If no plugin with *name* is discoverable.
        """
        for info in self.list_plugins():
            if info.name == name:
                return info
        raise KeyError(f"Plugin '{name}' not found.")

    # ------------------------------------------------------------------
    # Provider integration
    # ------------------------------------------------------------------

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
                plugin = load_plugin(info.name, plugin_dir=self._plugin_dir)
                self.register_provider_plugin(plugin)
                registered.append(info.name)
            except Exception:
                # Individual plugin failures must not abort the startup sequence.
                pass
        return registered

    # ------------------------------------------------------------------
    # Hook dispatch (pre/post request, middleware)
    # ------------------------------------------------------------------

    def dispatch_hook(
        self,
        hook: PluginHook,
        payload: Any = None,
        *,
        timeout: float = _SANDBOX_TIMEOUT_SECONDS,
    ) -> list[Any]:
        """Invoke all enabled plugins registered for *hook* with *payload*.

        Each plugin call is sandboxed — exceptions and timeouts are caught and
        logged without interrupting other plugins or the caller.

        Parameters
        ----------
        hook:
            The hook to fire (e.g. ``PluginHook.PRE_REQUEST``).
        payload:
            Arbitrary data passed to each plugin's hook handler.
        timeout:
            Per-plugin execution timeout in seconds.

        Returns
        -------
        list
            Results returned by each plugin (``None`` entries for timed-out or
            errored plugin calls are omitted).
        """
        results: list[Any] = []
        for info in self.list_plugins():
            if not info.enabled or info.hook_type != hook:
                continue
            try:
                plugin = load_plugin(info.name, plugin_dir=self._plugin_dir)
                handler = getattr(plugin, "handle", None)
                if callable(handler):
                    result = _sandboxed_call(handler, payload, timeout=timeout)
                    if result is not None:
                        results.append(result)
            except Exception as exc:
                logger.warning("Hook dispatch failed for plugin '%s': %s", info.name, exc)
        return results
