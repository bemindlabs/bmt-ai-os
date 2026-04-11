"""Persona file loader.

Discovers and reads SOUL.md / IDENTITY.md from an agent workspace directory.
Files are validated against per-file and total budget constraints before being
returned to the assembler.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Budget limits (characters)
_MAX_FILE_CHARS: int = 20_000
_MAX_TOTAL_CHARS: int = 150_000

# Known persona files and their priority slots.
# Lower number = inserted earlier in the assembled prompt.
_PERSONA_FILES: dict[str, int] = {
    "SOUL.md": 20,
    "IDENTITY.md": 30,
}


@dataclass
class ContextFile:
    """A single persona context file loaded from disk."""

    path: Path
    content: str
    priority: int

    @property
    def filename(self) -> str:
        return self.path.name

    def __lt__(self, other: "ContextFile") -> bool:
        return self.priority < other.priority


def load_context_file(workspace_dir: Path | str, filename: str) -> str | None:
    """Read *filename* from *workspace_dir*, enforcing the per-file char budget.

    Parameters
    ----------
    workspace_dir:
        Directory containing agent workspace files.
    filename:
        Bare filename to load (e.g. ``"SOUL.md"``).

    Returns
    -------
    str | None
        File contents (truncated to ``_MAX_FILE_CHARS`` if needed),
        or *None* if the file does not exist or cannot be read.
    """
    path = Path(workspace_dir) / filename
    if not path.is_file():
        logger.debug("Persona file not found: %s", path)
        return None

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not read persona file %s: %s", path, exc)
        return None

    if len(content) > _MAX_FILE_CHARS:
        logger.warning(
            "Persona file %s exceeds %d-char limit; truncating.",
            filename,
            _MAX_FILE_CHARS,
        )
        content = content[:_MAX_FILE_CHARS]

    return content


def load_workspace_files(workspace_dir: Path | str) -> list[ContextFile]:
    """Load all recognised persona files from *workspace_dir*.

    Files are returned sorted by priority (ascending).  The combined content
    is capped at ``_MAX_TOTAL_CHARS``; files that would exceed the budget are
    skipped with a warning.

    Parameters
    ----------
    workspace_dir:
        Path to the agent workspace directory.

    Returns
    -------
    list[ContextFile]
        Loaded context files, sorted by priority.
    """
    workspace_dir = Path(workspace_dir)
    loaded: list[ContextFile] = []
    total_chars = 0

    for filename, priority in sorted(_PERSONA_FILES.items(), key=lambda kv: kv[1]):
        content = load_context_file(workspace_dir, filename)
        if content is None:
            continue

        if total_chars + len(content) > _MAX_TOTAL_CHARS:
            logger.warning(
                "Total persona budget (%d chars) exceeded; skipping %s.",
                _MAX_TOTAL_CHARS,
                filename,
            )
            continue

        loaded.append(
            ContextFile(path=workspace_dir / filename, content=content, priority=priority)
        )
        total_chars += len(content)
        logger.debug(
            "Loaded persona file %s (%d chars, priority=%d)", filename, len(content), priority
        )

    return sorted(loaded)
