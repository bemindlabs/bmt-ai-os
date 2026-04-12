# Knowledge Vaults

Each AI persona gets its own knowledge base and Obsidian-compatible markdown vault with automatic RAG integration.

## Workspace Structure

```
workspace/agents/
├── coding/
│   ├── SOUL.md          # Persona definition
│   ├── notes/           # Obsidian vault
│   └── files/           # Working files
├── general/
│   ├── SOUL.md
│   ├── notes/
│   └── files/
└── creative/
    ├── SOUL.md
    ├── notes/
    └── files/
```

## Obsidian Compatibility

The vault parser supports standard Obsidian features:

- **Wiki-links** — `[[page-name]]` links rendered as navigable links
- **Frontmatter** — YAML metadata in `---` blocks
- **Tags** — `#tag` inline tags for organization
- **Embeds** — `![[note]]` for embedding other notes or images
- **Backlinks** — panel showing which notes link to the current note

## Auto-Ingest RAG

When files are created, edited, or deleted in a persona workspace, they are automatically re-ingested into that persona's RAG collection. A debounce mechanism prevents excessive re-indexing.

## Persona-Scoped Context

During chat, RAG queries automatically use the active persona's collection. The system prompt includes the persona's `SOUL.md` plus relevant vault context. If no persona-specific results exist, the system falls back to the default collection.

## Graph View

An interactive graph visualization shows connections between notes via wiki-links:

- Nodes represent notes
- Edges represent `[[wiki-link]]` connections
- Click a node to navigate to that note
- Zoom and pan to explore the knowledge graph

## Dashboard Integration

The Knowledge page in the dashboard shows:

- Persona selector dropdown to filter by active persona
- File browser defaulting to persona workspace
- RAG search scoped to persona collection
- Collection management (create, delete, re-index)
- Note editor with split view (edit + preview)
