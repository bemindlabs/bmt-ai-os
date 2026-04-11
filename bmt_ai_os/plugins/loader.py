"""Plugin discovery and loading for BMT AI OS.

Plugins are found via two mechanisms:

1. **Entry-points** — third-party packages register themselves under the
   ``bmt_ai_os.plugins`` entry-points group in their ``pyproject.toml``.

2. **Manifest directory** — a directory (default ``/opt/bmt/plugins/``) is
   scanned for ``plugin.yml`` manifest files.  Each sub-directory or flat
   ``*.yml`` file that contains a valid :class:`PluginManifest` is discovered.

Example pyproject.toml snippet for a third-party plugin:

    [project.entry-points."bmt_ai_os.plugins"]
    my-provider = "my_package.plugin:MyProviderPlugin"

Example plugin.yml manifest::

    name: my-tool
    version: 1.0.0
    description: A custom tool plugin
    hook_type: tool
    module: my_package.my_tool
    entry_class: MyToolPlugin
    author: Jane Dev
    dependencies:
      - requests>=2.28
"""

from __future__ import annotations

import importlib
import logging
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import yaml

from bmt_ai_os.plugins.hooks import PluginHook, PluginInfo, PluginManifest

logger = logging.getLogger(__name__)

_ENTRY_POINT_GROUP = "bmt_ai_os.plugins"
_DEFAULT_PLUGIN_DIR = "/opt/bmt/plugins"


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
# Manifest helpers
# ---------------------------------------------------------------------------


def load_manifest(path: Path) -> PluginManifest | None:
    """Parse a ``plugin.yml`` file and return a :class:`PluginManifest`.

    Returns ``None`` if the file is missing, unreadable, or malformed.
    """
    try:
        raw = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
        if not isinstance(data, dict):
            return None
        return PluginManifest.from_dict(data)
    except Exception as exc:
        logger.debug("Failed to parse manifest %s: %s", path, exc)
        return None


def discover_manifests(plugin_dir: str | Path = _DEFAULT_PLUGIN_DIR) -> list[PluginManifest]:
    """Scan *plugin_dir* for ``plugin.yml`` manifests.

    Searches both top-level ``plugin.yml`` files and one level of
    sub-directories (``<plugin_dir>/<name>/plugin.yml``).

    Returns a list of successfully parsed :class:`PluginManifest` objects.
    """
    root = Path(plugin_dir)
    if not root.is_dir():
        return []

    manifests: list[PluginManifest] = []
    seen_names: set[str] = set()

    # Top-level *.yml files
    for yml_file in sorted(root.glob("*.yml")):
        manifest = load_manifest(yml_file)
        if manifest and manifest.name not in seen_names:
            manifests.append(manifest)
            seen_names.add(manifest.name)

    # Sub-directory plugin.yml files
    for sub_dir in sorted(root.iterdir()):
        if not sub_dir.is_dir():
            continue
        plugin_yml = sub_dir / "plugin.yml"
        if plugin_yml.exists():
            manifest = load_manifest(plugin_yml)
            if manifest and manifest.name not in seen_names:
                manifests.append(manifest)
                seen_names.add(manifest.name)

    return manifests


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_plugins(
    plugin_dir: str | Path | None = None,
) -> list[PluginInfo]:
    """Discover plugins from entry-points and the manifest directory.

    Parameters
    ----------
    plugin_dir:
        Directory to scan for ``plugin.yml`` manifests.  Defaults to
        ``/opt/bmt/plugins``.  Pass an empty string or non-existent path to
        skip directory scanning.

    Returns one :class:`~bmt_ai_os.plugins.hooks.PluginInfo` per unique plugin
    found.  Import errors and malformed manifests are silently skipped so that
    a broken plugin does not prevent other plugins from loading.
    """
    infos: list[PluginInfo] = []
    seen_names: set[str] = set()

    # --- Entry-points ---
    eps = entry_points(group=_ENTRY_POINT_GROUP)
    for ep in eps:
        try:
            plugin_cls = ep.load()
        except Exception:
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

        if name not in seen_names:
            infos.append(
                PluginInfo(
                    name=name,
                    version=version,
                    hook_type=hook_type,
                    module=module,
                    enabled=True,
                    description=getattr(plugin_cls, "description", ""),
                    author=getattr(plugin_cls, "author", ""),
                )
            )
            seen_names.add(name)

    # --- Manifest directory ---
    scan_dir = plugin_dir if plugin_dir is not None else _DEFAULT_PLUGIN_DIR
    for manifest in discover_manifests(scan_dir):
        if manifest.name not in seen_names:
            infos.append(PluginInfo.from_manifest(manifest))
            seen_names.add(manifest.name)

    return infos


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_plugin(name: str, plugin_dir: str | Path | None = None) -> Plugin:
    """Import and initialize the plugin registered under *name*.

    Looks up the entry point first, then falls back to manifest-based loading
    from *plugin_dir*.

    Raises
    ------
    KeyError
        If no plugin with *name* is discoverable.
    TypeError
        If the loaded object does not satisfy the :class:`Plugin` protocol.
    """
    # --- Try entry-points first ---
    eps = entry_points(group=_ENTRY_POINT_GROUP)
    ep_map: dict[str, Any] = {ep.name: ep for ep in eps}

    if name in ep_map:
        plugin_cls = ep_map[name].load()
        instance = plugin_cls()

        if not isinstance(instance, Plugin):
            raise TypeError(
                f"Loaded object {plugin_cls!r} does not satisfy the Plugin protocol. "
                "It must expose: name, version, hook_type and an initialize() method."
            )

        instance.initialize()
        return instance

    # --- Try manifest directory ---
    scan_dir = plugin_dir if plugin_dir is not None else _DEFAULT_PLUGIN_DIR
    for manifest in discover_manifests(scan_dir):
        if manifest.name == name:
            return _load_from_manifest(manifest)

    available_ep = ", ".join(ep_map) or "(none)"
    raise KeyError(
        f"No plugin entry point named '{name}'. "
        f"Available in group '{_ENTRY_POINT_GROUP}': {available_ep}"
    )


def _load_from_manifest(manifest: PluginManifest) -> Plugin:
    """Load and initialize a plugin described by *manifest*."""
    try:
        module = importlib.import_module(manifest.module)
    except ImportError as exc:
        raise ImportError(
            f"Cannot import module '{manifest.module}' for plugin '{manifest.name}': {exc}"
        ) from exc

    plugin_cls = getattr(module, manifest.entry_class, None)
    if plugin_cls is None:
        raise AttributeError(
            f"Module '{manifest.module}' has no attribute '{manifest.entry_class}'"
        )

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
