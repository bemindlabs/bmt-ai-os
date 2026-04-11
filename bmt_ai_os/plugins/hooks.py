"""Plugin hook types and PluginInfo dataclass for BMT AI OS."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PluginHook(str, Enum):
    """Supported hook types that a plugin may implement."""

    # LLM provider extension
    PROVIDER = "provider"
    # RAG pipeline hook
    RAG_PROCESSOR = "rag_processor"
    # CLI command extension
    CLI_COMMAND = "cli_command"
    # HTTP request lifecycle hooks
    PRE_REQUEST = "pre_request"
    POST_REQUEST = "post_request"
    # ASGI / FastAPI middleware
    MIDDLEWARE = "middleware"
    # Arbitrary tool (function-calling tool)
    TOOL = "tool"


@dataclass
class PluginManifest:
    """Parsed contents of a plugin's ``plugin.yml`` manifest file.

    Fields
    ------
    name:
        Unique plugin identifier (kebab-case recommended).
    version:
        SemVer string, e.g. ``"1.2.3"``.
    description:
        Human-readable description shown in ``bmt-ai-os plugin list``.
    hook_type:
        Which :class:`PluginHook` category this plugin belongs to.
    module:
        Dotted Python import path for the plugin entry class.
    entry_class:
        Name of the class within *module* that satisfies the Plugin protocol.
    author:
        Optional author / maintainer string.
    dependencies:
        List of pip-installable package names required by this plugin.
    hooks:
        Additional hook names declared by the plugin (informational).
    config:
        Arbitrary key/value configuration passed to the plugin at init time.
    """

    name: str
    version: str
    description: str
    hook_type: PluginHook
    module: str
    entry_class: str
    author: str = ""
    dependencies: list[str] = field(default_factory=list)
    hooks: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "hook_type": self.hook_type.value,
            "module": self.module,
            "entry_class": self.entry_class,
            "author": self.author,
            "dependencies": self.dependencies,
            "hooks": self.hooks,
            "config": self.config,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PluginManifest":
        return cls(
            name=data["name"],
            version=data["version"],
            description=data.get("description", ""),
            hook_type=PluginHook(data["hook_type"]),
            module=data["module"],
            entry_class=data.get("entry_class", "Plugin"),
            author=data.get("author", ""),
            dependencies=data.get("dependencies", []),
            hooks=data.get("hooks", []),
            config=data.get("config", {}),
        )


@dataclass
class PluginInfo:
    """Metadata for a discovered plugin entry point."""

    name: str
    version: str
    hook_type: PluginHook
    module: str
    enabled: bool = field(default=True)
    description: str = ""
    author: str = ""
    manifest: PluginManifest | None = field(default=None, compare=False, repr=False)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "version": self.version,
            "hook_type": self.hook_type.value,
            "module": self.module,
            "enabled": self.enabled,
            "description": self.description,
            "author": self.author,
        }
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PluginInfo":
        return cls(
            name=data["name"],
            version=data["version"],
            hook_type=PluginHook(data["hook_type"]),
            module=data["module"],
            enabled=data.get("enabled", True),
            description=data.get("description", ""),
            author=data.get("author", ""),
        )

    @classmethod
    def from_manifest(cls, manifest: PluginManifest, enabled: bool = True) -> "PluginInfo":
        """Build a :class:`PluginInfo` from a :class:`PluginManifest`."""
        return cls(
            name=manifest.name,
            version=manifest.version,
            hook_type=manifest.hook_type,
            module=manifest.module,
            enabled=enabled,
            description=manifest.description,
            author=manifest.author,
            manifest=manifest,
        )
