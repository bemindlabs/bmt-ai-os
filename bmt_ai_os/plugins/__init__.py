"""BMT AI OS plugin system.

Public surface:

    from bmt_ai_os.plugins import PluginHook, PluginInfo, PluginManifest, PluginManager
    from bmt_ai_os.plugins.loader import discover_plugins, load_plugin, Plugin
"""

from bmt_ai_os.plugins.hooks import PluginHook, PluginInfo, PluginManifest
from bmt_ai_os.plugins.loader import Plugin, discover_plugins, load_plugin
from bmt_ai_os.plugins.manager import PluginManager

__all__ = [
    "Plugin",
    "PluginHook",
    "PluginInfo",
    "PluginManifest",
    "PluginManager",
    "discover_plugins",
    "load_plugin",
]
