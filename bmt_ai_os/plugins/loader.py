"""Plugin discovery via importlib.metadata for BMT AI OS.

Plugins register themselves under the entry-points group
``bmt_ai_os.plugins``.  Each entry point must expose a class (or callable)
that implements the ``Plugin`` protocol and provides the attributes:

    name: str
    version: str
    hook_type: PluginHook   (value from bmt_ai_os.plugins.hooks)
    module: str             (dotted import path)

Example pyproject.toml snippet for a third-party plugin:

    [project.entry-points."bmt_ai_os.plugins"]
    my-provider = "my_package.plugin:MyProviderPlugin"
"""

from __future__ import annotations

import importlib
from importlib.metadata import entry_points
from typing import Any, Protocol, runtime_checkable

from bmt_ai_os.plugins.hooks import PluginHook, PluginInfo

_ENTRY_POINT_GROUP = "bmt_ai_os.plugins"


# ---------------------------------------------------------------------------
# Plugin protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Plugin(Protocol):
    """Structural protocol every BMT AI OS plugin must satisfy.

    The attributes below are checked at load time; ``initialize`` is called
    once after the class is instantiated.
    """

    name: str
    version: str
    hook_type: PluginHook

    def initialize(self) -> None:
        """One-time initialization called by the loader after instantiation."""
        ...


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_plugins() -> list[PluginInfo]:
    """Scan the ``bmt_ai_os.plugins`` entry-points group and return metadata.

    Returns one :class:`~bmt_ai_os.plugins.hooks.PluginInfo` per entry point
    found.  Import errors are silently skipped so that a broken plugin does not
    prevent other plugins from loading.
    """
    infos: list[PluginInfo] = []

    eps = entry_points(group=_ENTRY_POINT_GROUP)
    for ep in eps:
        try:
            plugin_cls = ep.load()
        except Exception:
            # Broken or missing package — skip gracefully.
            continue

        name: str = getattr(plugin_cls, "name", ep.name)
        version: str = getattr(plugin_cls, "version", "0.0.0")
        hook_type_raw = getattr(plugin_cls, "hook_type", None)

        if isinstance(hook_type_raw, PluginHook):
            hook_type = hook_type_raw
        else:
            try:
                hook_type = PluginHook(str(hook_type_raw))
            except ValueError:
                hook_type = PluginHook.PROVIDER  # safe default

        module: str = getattr(plugin_cls, "__module__", ep.value.split(":")[0])

        infos.append(
            PluginInfo(
                name=name,
                version=version,
                hook_type=hook_type,
                module=module,
                enabled=True,
            )
        )

    return infos


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_plugin(name: str) -> Plugin:
    """Import and initialize the plugin registered under *name*.

    Looks up the entry point by name in ``bmt_ai_os.plugins``, loads the
    class, instantiates it (no constructor arguments required), and calls
    :py:meth:`Plugin.initialize`.

    Raises
    ------
    KeyError
        If no entry point with *name* exists.
    TypeError
        If the loaded object does not satisfy the :class:`Plugin` protocol.
    """
    eps = entry_points(group=_ENTRY_POINT_GROUP)

    # Build a mapping by entry-point name as well as by the plugin's own
    # ``name`` attribute (they may differ).
    ep_map: dict[str, Any] = {ep.name: ep for ep in eps}

    if name not in ep_map:
        available = ", ".join(ep_map) or "(none)"
        raise KeyError(
            f"No plugin entry point named '{name}'. "
            f"Available in group '{_ENTRY_POINT_GROUP}': {available}"
        )

    plugin_cls = ep_map[name].load()
    instance = plugin_cls()

    if not isinstance(instance, Plugin):
        raise TypeError(
            f"Loaded object {plugin_cls!r} does not satisfy the Plugin protocol. "
            "It must expose: name, version, hook_type and an initialize() method."
        )

    instance.initialize()
    return instance


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _import_module(dotted_path: str) -> Any:
    """Import *dotted_path* and return the module (internal helper)."""
    return importlib.import_module(dotted_path)
