"""Obsidian markdown parser for wiki-links, frontmatter, and tags."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml

    _YAML_AVAILABLE = True
except ImportError:  # pragma: no cover
    _YAML_AVAILABLE = False


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# ![[embed]] must be checked before [[wiki-link]] to avoid partial matches
_EMBED_RE = re.compile(r"!\[\[([^\]]+)\]\]")
_WIKI_LINK_RE = re.compile(r"(?<!!)\[\[([^\]]+)\]\]")
# Tags: word-boundary prefix, # then alphanumeric + allowed chars, not inside code
_TAG_RE = re.compile(r"(?:^|\s)#([a-zA-Z0-9_/-]+)", re.MULTILINE)
# Frontmatter block delimited by --- at start of file
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
# Code fence detector (to strip blocks before tag extraction)
_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ObsidianNote:
    """Parsed representation of an Obsidian markdown note."""

    path: str
    title: str
    content: str
    frontmatter: dict[str, Any] = field(default_factory=dict)
    wiki_links: list[str] = field(default_factory=list)  # [[Target]] references
    tags: list[str] = field(default_factory=list)  # #tag references
    embeds: list[str] = field(default_factory=list)  # ![[embed]] references


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_code_blocks(text: str) -> str:
    """Remove fenced and inline code spans to avoid false tag matches."""
    text = _CODE_FENCE_RE.sub("", text)
    text = _INLINE_CODE_RE.sub("", text)
    return text


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Extract YAML frontmatter and return (metadata_dict, body_without_frontmatter)."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text

    yaml_block = m.group(1)
    body = text[m.end() :]

    if not _YAML_AVAILABLE:
        return {}, body

    try:
        parsed = yaml.safe_load(yaml_block)
        if not isinstance(parsed, dict):
            parsed = {}
    except yaml.YAMLError:
        parsed = {}

    return parsed, body


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_note(file_path: str | Path) -> ObsidianNote:
    """Parse an Obsidian markdown file into structured data.

    Args:
        file_path: Path to the ``.md`` file to parse.

    Returns:
        :class:`ObsidianNote` populated with frontmatter, wiki-links, tags,
        and embed references extracted from the file.

    Raises:
        FileNotFoundError: If *file_path* does not exist.
        OSError: On read errors.
    """
    path = Path(file_path)
    raw_text = path.read_text(encoding="utf-8", errors="replace")

    frontmatter, body = _parse_frontmatter(raw_text)

    # Title: prefer frontmatter "title" key, otherwise use the stem
    title: str = frontmatter.get("title") or path.stem

    # Embeds (![[...]]) — extract before wiki-links so the embed markers
    # are not also captured by the wiki-link pattern.
    embeds: list[str] = _EMBED_RE.findall(body)

    # Wiki-links ([[...]]) — negative lookbehind for '!' is baked into the regex
    wiki_links: list[str] = _WIKI_LINK_RE.findall(body)

    # Tags from frontmatter "tags" field (list or space-separated string)
    fm_tags: list[str] = []
    raw_fm_tags = frontmatter.get("tags")
    if isinstance(raw_fm_tags, list):
        fm_tags = [str(t).lstrip("#") for t in raw_fm_tags]
    elif isinstance(raw_fm_tags, str):
        fm_tags = [t.lstrip("#") for t in raw_fm_tags.split()]

    # Tags from inline #tag syntax (excluding code blocks)
    clean_body = _strip_code_blocks(body)
    inline_tags: list[str] = _TAG_RE.findall(clean_body)

    # Merge, deduplicate, preserve order
    seen: set[str] = set()
    tags: list[str] = []
    for tag in fm_tags + inline_tags:
        if tag not in seen:
            seen.add(tag)
            tags.append(tag)

    # Deduplicate wiki_links and embeds while preserving order
    wiki_links = list(dict.fromkeys(wiki_links))
    embeds = list(dict.fromkeys(embeds))

    return ObsidianNote(
        path=str(path),
        title=title,
        content=body,
        frontmatter=frontmatter,
        wiki_links=wiki_links,
        tags=tags,
        embeds=embeds,
    )


def parse_vault(vault_dir: str | Path) -> list[ObsidianNote]:
    """Parse all ``.md`` files in a vault directory (recursive).

    Args:
        vault_dir: Root directory of the Obsidian vault.

    Returns:
        List of :class:`ObsidianNote` objects, one per markdown file.
        Files that fail to parse are skipped and logged to stderr.
    """
    vault_path = Path(vault_dir)
    notes: list[ObsidianNote] = []

    for md_file in sorted(vault_path.rglob("*.md")):
        try:
            notes.append(parse_note(md_file))
        except OSError:
            import sys

            print(f"[obsidian] Skipping unreadable file: {md_file}", file=sys.stderr)

    return notes


def resolve_wiki_link(link_text: str, vault_dir: str | Path) -> str | None:
    """Resolve ``[[link_text]]`` to an actual file path inside *vault_dir*.

    The resolution strategy mirrors Obsidian's behaviour:

    1. Strip any heading anchor (``Note#Section`` → ``Note``).
    2. Normalise the link text as a case-insensitive stem match.
    3. Prefer exact stem matches; accept a unique partial match otherwise.

    Args:
        link_text: The raw text inside ``[[ ]]``, e.g. ``"My Note#Heading"``.
        vault_dir: Root directory of the vault to search within.

    Returns:
        Absolute file path string when a unique match is found, ``None``
        otherwise.
    """
    vault_path = Path(vault_dir)

    # Strip heading anchor
    stem_text = link_text.split("#")[0].strip().lower()
    if not stem_text:
        return None

    all_md = list(vault_path.rglob("*.md"))

    # Exact stem match (case-insensitive)
    exact = [p for p in all_md if p.stem.lower() == stem_text]
    if len(exact) == 1:
        return str(exact[0])
    if len(exact) > 1:
        # Ambiguous — return None to signal the caller
        return None

    # Partial path match: the link may include subdirectory components
    # e.g. "subfolder/Note" → match files whose path ends with that fragment
    partial = [
        p
        for p in all_md
        if str(p.relative_to(vault_path)).lower().replace("\\", "/").removesuffix(".md")
        == stem_text
    ]
    if len(partial) == 1:
        return str(partial[0])

    return None


def get_backlinks(note_path: str, all_notes: list[ObsidianNote]) -> list[str]:
    """Find all notes that link to the given note.

    A note is considered to link to *note_path* when its
    :attr:`ObsidianNote.wiki_links` or :attr:`ObsidianNote.embeds` list
    contains a reference whose stem matches the target stem.

    Args:
        note_path: File path of the target note (as stored in
            :attr:`ObsidianNote.path`).
        all_notes: Full list of parsed notes to search through.

    Returns:
        List of :attr:`ObsidianNote.path` values that reference *note_path*.
    """
    target_stem = Path(note_path).stem.lower()

    backlinks: list[str] = []
    for note in all_notes:
        if note.path == note_path:
            continue
        all_refs = note.wiki_links + note.embeds
        for ref in all_refs:
            ref_stem = ref.split("#")[0].strip().lower()
            if ref_stem == target_stem:
                backlinks.append(note.path)
                break

    return backlinks
