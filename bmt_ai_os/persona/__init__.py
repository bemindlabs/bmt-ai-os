"""BMT AI OS — Persona system.

Assembles agent personas from SOUL.md / IDENTITY.md files stored in per-agent
workspace directories.  The active persona is injected into the system message
when clients do not provide one of their own.

Priority ordering (lower = higher priority):
    10  agents   — agent-level overrides (future)
    20  soul     — SOUL.md  (personality & tone)
    30  identity — IDENTITY.md (name, role, avatar)
    40  user     — user-provided system prompt
    50  tools    — tool descriptions (future)
    70  memory   — long-term memory injections (future)
"""

from .assembler import PersonaAssembler, assemble_system_prompt, get_persona_assembler
from .config import AgentPersona, resolve_workspace
from .loader import ContextFile, load_context_file, load_workspace_files

__all__ = [
    "AgentPersona",
    "ContextFile",
    "PersonaAssembler",
    "assemble_system_prompt",
    "get_persona_assembler",
    "load_context_file",
    "load_workspace_files",
    "resolve_workspace",
]
