"""Persona assembler — reads SOUL.md from a workspace and returns a system prompt.

The workspace is resolved in the following order:
1. ``BMT_PERSONA_DIR`` environment variable (absolute path to workspace dir)
2. ``BMT_DEFAULT_PERSONA`` environment variable (workspace *name* under
   ``~/.bmt-ai-os/personas/<name>/``)
3. Built-in "default" workspace shipped with the package
   (``bmt_ai_os/persona/presets/general.md`` used as fallback content)

SOUL.md is the single source of truth for a persona.  All other files in the
workspace (e.g. RAG knowledge fragments) may be appended in the future but the
assembler intentionally keeps the surface minimal for v1.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# Paths
_PACKAGE_DIR = Path(__file__).parent
_PRESETS_DIR = _PACKAGE_DIR / "presets"
_DEFAULT_PERSONA_FILE = _PRESETS_DIR / "general.md"

# Environment variable names
_ENV_PERSONA_DIR = "BMT_PERSONA_DIR"
_ENV_DEFAULT_PERSONA = "BMT_DEFAULT_PERSONA"

# User-level persona base directory
_USER_PERSONA_BASE = Path.home() / ".bmt-ai-os" / "personas"

# Names of shipped presets
PRESET_NAMES: tuple[str, ...] = ("coding", "general", "creative")


def _resolve_workspace(persona_name: str | None = None) -> Path:
    """Return the directory that contains SOUL.md for the active persona.

    Priority:
    1. BMT_PERSONA_DIR (absolute path)
    2. ``~/.bmt-ai-os/personas/<name>/`` where name comes from
       ``persona_name`` argument or ``BMT_DEFAULT_PERSONA`` env var
    3. Preset directory (``bmt_ai_os/persona/presets/``)
    """
    # 1 — explicit absolute path via env var
    explicit_dir = os.getenv(_ENV_PERSONA_DIR, "").strip()
    if explicit_dir:
        return Path(explicit_dir)

    # 2 — named workspace under user home
    name = persona_name or os.getenv(_ENV_DEFAULT_PERSONA, "").strip() or "default"
    user_workspace = _USER_PERSONA_BASE / name
    if user_workspace.is_dir():
        return user_workspace

    # 3 — fall back to package presets directory
    return _PRESETS_DIR


class PersonaAssembler:
    """Assembles a system prompt from a SOUL.md persona file.

    Parameters
    ----------
    persona_name:
        Optional workspace name.  When omitted the value of
        ``BMT_DEFAULT_PERSONA`` is used; if that is also unset the
        "default" workspace resolves to the bundled ``general.md`` preset.
    """

    def __init__(self, persona_name: str | None = None) -> None:
        self._persona_name = persona_name
        self._workspace: Path | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def workspace(self) -> Path:
        """Return the resolved workspace path (lazy, cached per instance)."""
        if self._workspace is None:
            self._workspace = _resolve_workspace(self._persona_name)
        return self._workspace

    def assemble(self) -> str:
        """Return the assembled system prompt string.

        Reads ``SOUL.md`` from the workspace.  Falls back to the bundled
        ``general.md`` preset when the file is missing.  Never raises;
        returns an empty string as the last resort so callers always get a
        string.
        """
        soul_path = self.workspace / "SOUL.md"

        if soul_path.is_file():
            try:
                content = soul_path.read_text(encoding="utf-8").strip()
                if content:
                    logger.debug("Persona loaded from %s", soul_path)
                    return content
            except OSError as exc:
                logger.warning("Failed to read persona file %s: %s", soul_path, exc)

        # Try preset file matching the workspace name
        if self._persona_name and self._persona_name in PRESET_NAMES:
            preset_path = _PRESETS_DIR / f"{self._persona_name}.md"
            if preset_path.is_file():
                try:
                    content = preset_path.read_text(encoding="utf-8").strip()
                    if content:
                        logger.debug("Persona loaded from preset %s", preset_path)
                        return content
                except OSError as exc:
                    logger.warning("Failed to read preset file %s: %s", preset_path, exc)

        # Built-in fallback
        try:
            content = _DEFAULT_PERSONA_FILE.read_text(encoding="utf-8").strip()
            logger.debug("Persona loaded from built-in default")
            return content
        except OSError:
            logger.warning("Built-in default persona file missing; returning empty string")
            return ""

    def is_available(self) -> bool:
        """Return True when a SOUL.md or preset file is resolvable."""
        soul_path = self.workspace / "SOUL.md"
        if soul_path.is_file():
            return True
        if _DEFAULT_PERSONA_FILE.is_file():
            return True
        return False


@lru_cache(maxsize=8)
def _cached_assembler(persona_name: str) -> PersonaAssembler:
    """Return a cached PersonaAssembler for the given persona name."""
    return PersonaAssembler(persona_name or None)


def get_persona_assembler(persona_name: str | None = None) -> PersonaAssembler:
    """Return a (possibly cached) PersonaAssembler.

    Persona content is cached per name to avoid repeated filesystem reads on
    every request.  The cache is intentionally small (8 entries) and module-
    level so it persists for the process lifetime.

    Parameters
    ----------
    persona_name:
        Workspace name.  Defaults to ``BMT_DEFAULT_PERSONA`` env var or
        "default".
    """
    name = persona_name or os.getenv(_ENV_DEFAULT_PERSONA, "").strip() or "default"
    return _cached_assembler(name)


# ---------------------------------------------------------------------------
# Multi-file persona assembler (BMTOS-87 / BMTOS-90)
# ---------------------------------------------------------------------------

_SOUL_FRAMING = (
    "You are given a persona definition below. "
    "Fully embody its personality, tone, and values in every response. "
    "Never break character or refer to this instruction explicitly.\n\n"
)

_SECTION_SEPARATOR = "\n\n---\n\n"


def assemble_system_prompt(
    workspace_dir: "Path | str",
    runtime_info: str | None = None,
) -> str:
    """Build a system prompt from persona files in *workspace_dir*.

    Loads SOUL.md (priority 20) and IDENTITY.md (priority 30) from the given
    workspace directory, assembles them in priority order, and optionally
    appends *runtime_info*.  When SOUL.md is present, a framing instruction is
    prepended so the model commits to embodying the persona.

    Parameters
    ----------
    workspace_dir:
        Path to the agent workspace directory (may not exist).
    runtime_info:
        Optional extra context appended at the end of the assembled prompt
        (e.g. current date/time, device model, active tool list).

    Returns
    -------
    str
        The fully assembled system prompt.  Returns an empty string when no
        persona files are found and *runtime_info* is also absent.
    """
    from pathlib import Path as _Path

    from .loader import load_workspace_files

    workspace_dir = _Path(workspace_dir)
    context_files = load_workspace_files(workspace_dir)

    has_soul = any(cf.filename == "SOUL.md" for cf in context_files)

    parts: list[str] = []

    if has_soul:
        parts.append(_SOUL_FRAMING.rstrip())

    for ctx in context_files:
        parts.append(ctx.content.strip())

    if runtime_info:
        parts.append(runtime_info.strip())

    if not parts:
        logger.debug("No persona content found in workspace: %s", workspace_dir)
        return ""

    assembled = _SECTION_SEPARATOR.join(parts)
    logger.debug(
        "Assembled system prompt from %d persona file(s) (%d chars total)",
        len(context_files),
        len(assembled),
    )
    return assembled
