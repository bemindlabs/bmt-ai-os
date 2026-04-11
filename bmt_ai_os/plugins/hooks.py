"""Plugin hook types and PluginInfo dataclass for BMT AI OS."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PluginHook(str, Enum):
    """Supported hook types that a plugin may implement."""

    PROVIDER = "provider"
    RAG_PROCESSOR = "rag_processor"
    CLI_COMMAND = "cli_command"


@dataclass
class PluginInfo:
    """Metadata for a discovered plugin entry point."""

    name: str
    version: str
    hook_type: PluginHook
    module: str
    enabled: bool = field(default=True)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "hook_type": self.hook_type.value,
            "module": self.module,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PluginInfo":
        return cls(
            name=data["name"],
            version=data["version"],
            hook_type=PluginHook(data["hook_type"]),
            module=data["module"],
            enabled=data.get("enabled", True),
        )
