"""Persona configuration and workspace resolution.

Provides the ``AgentPersona`` dataclass that describes a named agent, and
``resolve_workspace`` which maps an *agent_id* to its filesystem workspace
directory using the ``BMT_PERSONA_DIR`` environment variable.

Production path:  /data/bmt_ai_os/agents/{agent_id}/
Development path: /tmp/bmt-agents/{agent_id}/   (when BMT_PERSONA_DIR is unset
                  and /data/bmt_ai_os/agents/ is not writable)

Override with:
    BMT_PERSONA_DIR=/my/custom/path
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Production default; falls back to /tmp when unavailable.
_PROD_BASE = Path("/data/bmt_ai_os/agents")
_DEV_BASE = Path("/tmp/bmt-agents")


def _default_base_dir() -> Path:
    """Return the base agents directory, honouring ``BMT_PERSONA_DIR``."""
    env_val = os.environ.get("BMT_PERSONA_DIR")
    if env_val:
        return Path(env_val)
    # Use production path when it already exists (deployed device).
    if _PROD_BASE.exists():
        return _PROD_BASE
    return _DEV_BASE


def resolve_workspace(agent_id: str) -> Path:
    """Return the workspace directory path for *agent_id*.

    The directory is *not* created by this function; callers that need to
    write files must create it themselves.

    Parameters
    ----------
    agent_id:
        Unique identifier for the agent (alphanumeric + hyphens/underscores).

    Returns
    -------
    Path
        Absolute path to ``{base}/{agent_id}/``.
    """
    if not agent_id:
        raise ValueError("agent_id must be a non-empty string")
    return _default_base_dir() / agent_id


@dataclass
class AgentPersona:
    """Configuration for a single named agent.

    Attributes
    ----------
    agent_id:
        Unique, URL-safe identifier (e.g. ``"assistant"``, ``"coder"``).
    display_name:
        Human-readable name shown in the UI (defaults to *agent_id*).
    default_model:
        Provider model string to use for this agent (overrides global default).
    workspace_dir:
        Resolved workspace path.  Populated automatically from *agent_id* when
        not provided explicitly.
    description:
        Short description of this agent's purpose.
    tags:
        Arbitrary tags for grouping / filtering.
    """

    agent_id: str
    display_name: str = ""
    default_model: str = ""
    workspace_dir: Path = field(default=Path(""))
    description: str = ""
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.display_name:
            self.display_name = self.agent_id
        if not self.workspace_dir or self.workspace_dir == Path(""):
            self.workspace_dir = resolve_workspace(self.agent_id)
