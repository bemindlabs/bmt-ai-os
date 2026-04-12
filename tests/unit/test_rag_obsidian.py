"""Unit tests for bmt_ai_os.rag.obsidian and ObsidianChunker."""

from __future__ import annotations

from pathlib import Path

from bmt_ai_os.rag.obsidian import (
    ObsidianNote,
    get_backlinks,
    parse_note,
    parse_vault,
    resolve_wiki_link,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_note(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# _parse_frontmatter (indirect via parse_note)
# ---------------------------------------------------------------------------


class TestFrontmatter:
    def test_no_frontmatter_returns_empty_dict(self, tmp_path):
        p = _write_note(tmp_path, "plain.md", "Just some text.\n")
        note = parse_note(p)
        assert note.frontmatter == {}

    def test_extracts_string_field(self, tmp_path):
        content = "---\ntitle: My Note\n---\nBody text.\n"
        p = _write_note(tmp_path, "note.md", content)
        note = parse_note(p)
        assert note.frontmatter["title"] == "My Note"

    def test_title_from_frontmatter(self, tmp_path):
        content = "---\ntitle: Custom Title\n---\n"
        p = _write_note(tmp_path, "note.md", content)
        note = parse_note(p)
        assert note.title == "Custom Title"

    def test_title_falls_back_to_stem(self, tmp_path):
        p = _write_note(tmp_path, "my-note.md", "No frontmatter.\n")
        note = parse_note(p)
        assert note.title == "my-note"

    def test_extracts_list_tags(self, tmp_path):
        content = "---\ntags:\n  - python\n  - ai\n---\n"
        p = _write_note(tmp_path, "note.md", content)
        note = parse_note(p)
        assert "python" in note.tags
        assert "ai" in note.tags

    def test_extracts_string_tags(self, tmp_path):
        content = "---\ntags: python ai\n---\n"
        p = _write_note(tmp_path, "note.md", content)
        note = parse_note(p)
        assert "python" in note.tags
        assert "ai" in note.tags

    def test_extra_frontmatter_fields(self, tmp_path):
        content = "---\nauthor: Alice\ndate: 2026-04-12\n---\n"
        p = _write_note(tmp_path, "note.md", content)
        note = parse_note(p)
        assert note.frontmatter["author"] == "Alice"


# ---------------------------------------------------------------------------
# Wiki-links
# ---------------------------------------------------------------------------


class TestWikiLinks:
    def test_extracts_single_wiki_link(self, tmp_path):
        p = _write_note(tmp_path, "note.md", "See [[Other Note]] for details.\n")
        note = parse_note(p)
        assert "Other Note" in note.wiki_links

    def test_extracts_multiple_wiki_links(self, tmp_path):
        p = _write_note(tmp_path, "note.md", "See [[Alpha]] and [[Beta]].\n")
        note = parse_note(p)
        assert "Alpha" in note.wiki_links
        assert "Beta" in note.wiki_links

    def test_deduplicates_wiki_links(self, tmp_path):
        p = _write_note(tmp_path, "note.md", "[[Alpha]] and [[Alpha]] again.\n")
        note = parse_note(p)
        assert note.wiki_links.count("Alpha") == 1

    def test_embed_not_in_wiki_links(self, tmp_path):
        p = _write_note(tmp_path, "note.md", "![[image.png]] is an embed.\n")
        note = parse_note(p)
        assert "image.png" not in note.wiki_links

    def test_empty_body_has_no_wiki_links(self, tmp_path):
        p = _write_note(tmp_path, "note.md", "No links here.\n")
        note = parse_note(p)
        assert note.wiki_links == []

    def test_wiki_link_with_heading_anchor(self, tmp_path):
        p = _write_note(tmp_path, "note.md", "See [[Note#Section]].\n")
        note = parse_note(p)
        assert "Note#Section" in note.wiki_links


# ---------------------------------------------------------------------------
# Embeds
# ---------------------------------------------------------------------------


class TestEmbeds:
    def test_extracts_embed(self, tmp_path):
        p = _write_note(tmp_path, "note.md", "![[diagram.png]]\n")
        note = parse_note(p)
        assert "diagram.png" in note.embeds

    def test_embed_not_mixed_with_wiki_links(self, tmp_path):
        content = "![[img.png]] and [[Link]].\n"
        p = _write_note(tmp_path, "note.md", content)
        note = parse_note(p)
        assert "img.png" in note.embeds
        assert "Link" in note.wiki_links
        assert "Link" not in note.embeds
        assert "img.png" not in note.wiki_links

    def test_deduplicates_embeds(self, tmp_path):
        p = _write_note(tmp_path, "note.md", "![[a.png]] and ![[a.png]].\n")
        note = parse_note(p)
        assert note.embeds.count("a.png") == 1


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------


class TestTags:
    def test_extracts_inline_tag(self, tmp_path):
        p = _write_note(tmp_path, "note.md", "This is #python code.\n")
        note = parse_note(p)
        assert "python" in note.tags

    def test_ignores_tag_in_code_block(self, tmp_path):
        content = "```\n#not-a-tag\n```\n"
        p = _write_note(tmp_path, "note.md", content)
        note = parse_note(p)
        assert "not-a-tag" not in note.tags

    def test_ignores_tag_in_inline_code(self, tmp_path):
        p = _write_note(tmp_path, "note.md", "Use `#not-a-tag` here.\n")
        note = parse_note(p)
        assert "not-a-tag" not in note.tags

    def test_merges_frontmatter_and_inline_tags(self, tmp_path):
        content = "---\ntags:\n  - ai\n---\nSome #python content.\n"
        p = _write_note(tmp_path, "note.md", content)
        note = parse_note(p)
        assert "ai" in note.tags
        assert "python" in note.tags

    def test_deduplicates_tags(self, tmp_path):
        content = "---\ntags:\n  - python\n---\n#python content.\n"
        p = _write_note(tmp_path, "note.md", content)
        note = parse_note(p)
        assert note.tags.count("python") == 1

    def test_tag_with_slash(self, tmp_path):
        p = _write_note(tmp_path, "note.md", "Categorised as #area/project.\n")
        note = parse_note(p)
        assert "area/project" in note.tags


# ---------------------------------------------------------------------------
# parse_vault
# ---------------------------------------------------------------------------


class TestParseVault:
    def test_parses_all_md_files(self, tmp_path):
        _write_note(tmp_path, "a.md", "Note A")
        _write_note(tmp_path, "b.md", "Note B")
        notes = parse_vault(tmp_path)
        paths = {Path(n.path).name for n in notes}
        assert {"a.md", "b.md"} == paths

    def test_ignores_non_md_files(self, tmp_path):
        _write_note(tmp_path, "a.md", "Note A")
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        notes = parse_vault(tmp_path)
        assert len(notes) == 1

    def test_recursive_subdirectory(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        _write_note(tmp_path, "top.md", "Top note")
        _write_note(sub, "nested.md", "Nested note")
        notes = parse_vault(tmp_path)
        assert len(notes) == 2

    def test_empty_vault_returns_empty_list(self, tmp_path):
        assert parse_vault(tmp_path) == []


# ---------------------------------------------------------------------------
# resolve_wiki_link
# ---------------------------------------------------------------------------


class TestResolveWikiLink:
    def test_resolves_exact_stem(self, tmp_path):
        p = _write_note(tmp_path, "My Note.md", "content")
        result = resolve_wiki_link("My Note", tmp_path)
        assert result == str(p)

    def test_case_insensitive(self, tmp_path):
        p = _write_note(tmp_path, "MyNote.md", "content")
        result = resolve_wiki_link("mynote", tmp_path)
        assert result == str(p)

    def test_returns_none_for_missing(self, tmp_path):
        result = resolve_wiki_link("DoesNotExist", tmp_path)
        assert result is None

    def test_returns_none_for_ambiguous(self, tmp_path):
        sub1 = tmp_path / "a"
        sub2 = tmp_path / "b"
        sub1.mkdir()
        sub2.mkdir()
        _write_note(sub1, "Note.md", "A")
        _write_note(sub2, "Note.md", "B")
        result = resolve_wiki_link("Note", tmp_path)
        assert result is None

    def test_strips_heading_anchor(self, tmp_path):
        p = _write_note(tmp_path, "Guide.md", "content")
        result = resolve_wiki_link("Guide#Introduction", tmp_path)
        assert result == str(p)

    def test_resolves_subdirectory_path(self, tmp_path):
        sub = tmp_path / "docs"
        sub.mkdir()
        p = _write_note(sub, "API.md", "content")
        result = resolve_wiki_link("docs/API", tmp_path)
        assert result == str(p)


# ---------------------------------------------------------------------------
# get_backlinks
# ---------------------------------------------------------------------------


class TestGetBacklinks:
    def _make_notes(self, specs: list[tuple[str, str]]) -> list[ObsidianNote]:
        return [
            ObsidianNote(path=path, title=path, content=content, wiki_links=wiki_links)
            for path, content, wiki_links in [
                (s[0], s[1], s[2] if len(s) > 2 else []) for s in specs
            ]
        ]

    def test_finds_backlink(self):
        notes = [
            ObsidianNote(
                path="a.md",
                title="A",
                content="See [[B]]",
                wiki_links=["B"],
            ),
            ObsidianNote(
                path="b.md",
                title="B",
                content="Standalone",
                wiki_links=[],
            ),
        ]
        bl = get_backlinks("b.md", notes)
        assert "a.md" in bl

    def test_excludes_self(self):
        notes = [
            ObsidianNote(
                path="a.md",
                title="A",
                content="[[A]]",
                wiki_links=["A"],
            ),
        ]
        bl = get_backlinks("a.md", notes)
        assert "a.md" not in bl

    def test_no_backlinks_returns_empty(self):
        notes = [
            ObsidianNote(path="a.md", title="A", content="nothing", wiki_links=[]),
            ObsidianNote(path="b.md", title="B", content="nothing", wiki_links=[]),
        ]
        assert get_backlinks("b.md", notes) == []

    def test_embed_counts_as_backlink(self):
        notes = [
            ObsidianNote(
                path="a.md",
                title="A",
                content="![[B]]",
                wiki_links=[],
                embeds=["B"],
            ),
            ObsidianNote(path="b.md", title="B", content="", wiki_links=[]),
        ]
        bl = get_backlinks("b.md", notes)
        assert "a.md" in bl

    def test_case_insensitive_match(self):
        notes = [
            ObsidianNote(
                path="a.md",
                title="A",
                content="[[my note]]",
                wiki_links=["my note"],
            ),
            ObsidianNote(path="My Note.md", title="My Note", content="", wiki_links=[]),
        ]
        bl = get_backlinks("My Note.md", notes)
        assert "a.md" in bl


# ---------------------------------------------------------------------------
# ObsidianChunker
# ---------------------------------------------------------------------------


class TestObsidianChunker:
    def test_chunk_produces_chunks(self, tmp_path):
        from bmt_ai_os.rag.chunker import ObsidianChunker

        text = "---\ntitle: Test\ntags:\n  - ai\n---\n# Intro\n\nSome content here.\n"
        chunker = ObsidianChunker()
        chunks = chunker.chunk(text, source="test.md")
        assert len(chunks) > 0

    def test_chunk_metadata_contains_source_file(self, tmp_path):
        from bmt_ai_os.rag.chunker import ObsidianChunker

        text = "# Section\n\nHello world.\n"
        chunker = ObsidianChunker()
        chunks = chunker.chunk(text, source="/vault/note.md")
        assert all(c.metadata.get("source_file") == "/vault/note.md" for c in chunks)

    def test_chunk_metadata_contains_title(self, tmp_path):
        from bmt_ai_os.rag.chunker import ObsidianChunker

        text = "---\ntitle: My Note\n---\n# Section\n\nContent.\n"
        chunker = ObsidianChunker()
        chunks = chunker.chunk(text, source="note.md")
        assert all(c.metadata.get("title") == "My Note" for c in chunks)

    def test_chunk_metadata_contains_tags(self, tmp_path):
        from bmt_ai_os.rag.chunker import ObsidianChunker

        text = "---\ntags:\n  - ai\n  - rag\n---\n# Section\n\nContent.\n"
        chunker = ObsidianChunker()
        chunks = chunker.chunk(text, source="note.md")
        for chunk in chunks:
            assert "ai" in chunk.metadata.get("tags", "")
            assert "rag" in chunk.metadata.get("tags", "")

    def test_chunk_metadata_contains_wiki_links(self, tmp_path):
        from bmt_ai_os.rag.chunker import ObsidianChunker

        text = "# Section\n\nSee [[Other Note]] for details.\n"
        chunker = ObsidianChunker()
        chunks = chunker.chunk(text, source="note.md")
        assert all("Other Note" in c.metadata.get("wiki_links", "") for c in chunks)

    def test_chunk_metadata_contains_section_heading(self, tmp_path):
        from bmt_ai_os.rag.chunker import ObsidianChunker

        text = "# Introduction\n\nContent here.\n\n## Details\n\nMore content.\n"
        chunker = ObsidianChunker()
        chunks = chunker.chunk(text, source="note.md")
        headings = {c.metadata.get("section_heading") for c in chunks}
        assert any("Introduction" in h for h in headings if h)

    def test_chunk_note_method(self, tmp_path):
        from bmt_ai_os.rag.chunker import ObsidianChunker
        from bmt_ai_os.rag.obsidian import ObsidianNote

        note = ObsidianNote(
            path="/vault/note.md",
            title="Test Note",
            content="# Heading\n\nBody text.\n",
            frontmatter={"title": "Test Note"},
            wiki_links=["Other"],
            tags=["ai"],
        )
        chunker = ObsidianChunker()
        chunks = chunker.chunk_note(note)
        assert len(chunks) > 0
        assert chunks[0].metadata["source_file"] == "/vault/note.md"
        assert chunks[0].metadata["title"] == "Test Note"

    def test_large_section_is_split(self, tmp_path):
        from bmt_ai_os.rag.chunker import ObsidianChunker

        # Build multiple paragraphs (blank-line separated) so that the
        # paragraph splitter produces multiple pieces that _merge_splits
        # can pack into more than one chunk.
        paragraphs = [" ".join(f"word{i + j * 30}" for i in range(30)) for j in range(10)]
        big_body = "\n\n".join(paragraphs)  # 10 paragraphs of 30 words each = 300 words
        text = f"# BigSection\n\n{big_body}\n"
        chunker = ObsidianChunker(chunk_size=60, overlap=5)
        chunks = chunker.chunk(text, source="big.md")
        assert len(chunks) > 1
