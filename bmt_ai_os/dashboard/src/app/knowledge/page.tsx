"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import {
  fetchCollections,
  ingestDocuments,
  searchKnowledge,
  deleteCollection,
  type RagCollection,
  type RagSource,
  listFiles,
  readFile,
  writeFile,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Database,
  FolderOpen,
  Search,
  Trash2,
  RefreshCw,
  FileText,
  NotebookPen,
  Network,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { FileManagerClient } from "../files/file-manager-client";
import {
  PersonaSelector,
  useActivePersona,
} from "./persona-selector";
import { NoteEditor, newNoteTemplate } from "./note-editor";
import { NoteList, type NoteItem } from "./note-list";
import {
  VaultGraph,
  type GraphNode,
  type GraphEdge,
} from "./vault-graph";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Returns the persona-scoped collection name.
 * When no persona is active the empty string is treated as "default" by callers.
 */
function personaCollection(activePersona: string | null): string {
  return activePersona ? `persona_${activePersona}` : "";
}

/**
 * Returns the persona-scoped workspace files path.
 * Falls back to the server-provided workspace_path when available.
 */
function personaFilesPath(
  activePersona: string | null,
  workspacePath: string | null,
): string {
  if (!activePersona) return "";
  if (workspacePath) return workspacePath;
  return `workspace/agents/${activePersona}/files`;
}

// ---------------------------------------------------------------------------
// Collections tab
// ---------------------------------------------------------------------------

interface CollectionsTabProps {
  activePersona: string | null;
}

function CollectionsTab({ activePersona }: CollectionsTabProps) {
  const [collections, setCollections] = useState<RagCollection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingName, setDeletingName] = useState<string | null>(null);

  const personaCol = personaCollection(activePersona);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchCollections();
      setCollections(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load collections");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleDelete(name: string) {
    if (!confirm(`Delete collection "${name}"? This cannot be undone.`)) return;
    setDeletingName(name);
    try {
      await deleteCollection(name);
      setCollections((prev) => prev.filter((c) => c.name !== name));
    } catch (err) {
      alert(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setDeletingName(null);
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <div>
          <CardTitle>Collections</CardTitle>
          <CardDescription>
            {error
              ? "Could not reach the RAG API."
              : loading
                ? "Loading..."
                : `${collections.length} collection${collections.length !== 1 ? "s" : ""}`}
          </CardDescription>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading} aria-label="Refresh collections">
          <RefreshCw className={cn("size-4", loading && "animate-spin")} />
          <span className="ml-2">Refresh</span>
        </Button>
      </CardHeader>

      <CardContent className="p-0">
        {!loading && collections.length === 0 ? (
          <div className="flex flex-col items-center gap-4 py-16 text-muted-foreground">
            <Database className="size-12 opacity-30" />
            <p className="text-sm">
              {error
                ? "RAG API is unreachable. Check controller logs."
                : "No collections yet. Ingest documents to create one."}
            </p>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Documents</TableHead>
                <TableHead className="w-[80px]" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {collections.map((col) => {
                const isPersonaCol =
                  personaCol !== "" && col.name === personaCol;
                return (
                  <TableRow key={col.name}>
                    <TableCell className="font-medium">
                      <span className="flex items-center gap-2">
                        {col.name}
                        {isPersonaCol && (
                          <Badge variant="default" className="capitalize text-[10px]">
                            {activePersona}
                          </Badge>
                        )}
                      </span>
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary">{col.count}</Badge>
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Delete collection ${col.name}`}
                        disabled={deletingName === col.name}
                        onClick={() => handleDelete(col.name)}
                        className="text-destructive hover:text-destructive"
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Ingest tab
// ---------------------------------------------------------------------------

type IngestState = "idle" | "loading" | "success" | "error";

interface IngestTabProps {
  activePersona: string | null;
  personaWorkspacePath: string | null;
}

function IngestTab({ activePersona, personaWorkspacePath }: IngestTabProps) {
  const defaultPath = personaFilesPath(activePersona, personaWorkspacePath);
  const defaultCollection = personaCollection(activePersona);

  const [folderPath, setFolderPath] = useState(defaultPath);
  const [collection, setCollection] = useState(
    defaultCollection || "default",
  );
  const [state, setState] = useState<IngestState>("idle");
  const [message, setMessage] = useState<string | null>(null);

  // Sync field defaults when persona changes
  useEffect(() => {
    setFolderPath(personaFilesPath(activePersona, personaWorkspacePath));
    setCollection(personaCollection(activePersona) || "default");
    setState("idle");
    setMessage(null);
  }, [activePersona, personaWorkspacePath]);

  async function handleIngest() {
    if (!folderPath.trim()) return;
    setState("loading");
    setMessage(null);
    try {
      const res = await ingestDocuments({
        path: folderPath.trim(),
        collection: collection.trim() || "default",
        recursive: true,
      });
      setState("success");
      setMessage(
        `Accepted: "${res.path}" into collection "${res.collection}". Ingestion runs in the background.`,
      );
    } catch (err) {
      setState("error");
      setMessage(err instanceof Error ? err.message : "Ingest request failed");
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Ingest Documents</CardTitle>
        <CardDescription>
          Provide an absolute folder path on the device. The controller will
          chunk and embed all files recursively.
          {activePersona && (
            <span className="ml-1 text-primary">
              Pre-filled for the <span className="font-medium capitalize">{activePersona}</span> persona workspace.
            </span>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="ingest-path">
              Folder path
            </label>
            <Input
              id="ingest-path"
              placeholder="/data/documents"
              value={folderPath}
              onChange={(e) => setFolderPath(e.target.value)}
              disabled={state === "loading"}
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="ingest-collection">
              Collection name
            </label>
            <Input
              id="ingest-collection"
              placeholder="default"
              value={collection}
              onChange={(e) => setCollection(e.target.value)}
              disabled={state === "loading"}
            />
          </div>
        </div>

        <Button
          onClick={handleIngest}
          disabled={!folderPath.trim() || state === "loading"}
        >
          {state === "loading" ? (
            <>
              <RefreshCw className="mr-2 size-4 animate-spin" />
              Submitting...
            </>
          ) : (
            <>
              <FolderOpen className="mr-2 size-4" />
              Ingest
            </>
          )}
        </Button>

        {message && (
          <p
            className={cn(
              "rounded-md border px-3 py-2 text-sm",
              state === "success"
                ? "border-green-500/30 bg-green-500/10 text-green-700 dark:text-green-400"
                : "border-destructive/30 bg-destructive/10 text-destructive",
            )}
          >
            {message}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Search tab
// ---------------------------------------------------------------------------

interface SearchTabProps {
  activePersona: string | null;
}

function SearchTab({ activePersona }: SearchTabProps) {
  const defaultCollection = personaCollection(activePersona);

  const [query, setQuery] = useState("");
  const [collection, setCollection] = useState(
    defaultCollection || "default",
  );
  const [topK, setTopK] = useState("5");
  const [loading, setLoading] = useState(false);
  const [answer, setAnswer] = useState<string | null>(null);
  const [sources, setSources] = useState<RagSource[]>([]);
  const [latency, setLatency] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Update collection default when persona changes (only when unmodified from persona default)
  useEffect(() => {
    setCollection(personaCollection(activePersona) || "default");
  }, [activePersona]);

  async function handleSearch() {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    setAnswer(null);
    setSources([]);
    setLatency(null);
    try {
      const res = await searchKnowledge({
        question: query.trim(),
        collection: collection.trim() || "default",
        top_k: Math.max(1, Math.min(50, Number(topK) || 5)),
      });
      setAnswer(res.answer);
      setSources(res.sources ?? []);
      setLatency(res.latency_ms);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") void handleSearch();
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Search Knowledge Base</CardTitle>
          <CardDescription>
            Ask a question; the RAG engine retrieves relevant chunks and
            generates an answer.
            {activePersona && (
              <span className="ml-1 text-primary">
                Searching the <span className="font-medium capitalize">{activePersona}</span> persona collection.
              </span>
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-[1fr_180px_80px]">
            <Input
              placeholder="Ask a question..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={loading}
            />
            <Input
              placeholder="Collection: default"
              value={collection}
              onChange={(e) => setCollection(e.target.value)}
              disabled={loading}
            />
            <Input
              type="number"
              min={1}
              max={50}
              placeholder="Top-K"
              value={topK}
              onChange={(e) => setTopK(e.target.value)}
              disabled={loading}
            />
          </div>
          <Button
            onClick={handleSearch}
            disabled={!query.trim() || loading}
          >
            {loading ? (
              <>
                <RefreshCw className="mr-2 size-4 animate-spin" />
                Searching...
              </>
            ) : (
              <>
                <Search className="mr-2 size-4" />
                Search
              </>
            )}
          </Button>

          {error && (
            <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {error}
            </p>
          )}
        </CardContent>
      </Card>

      {answer !== null && (
        <>
          <Card>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base">Answer</CardTitle>
                {latency !== null && (
                  <span className="text-xs text-muted-foreground">
                    {latency.toFixed(0)} ms
                  </span>
                )}
              </div>
            </CardHeader>
            <CardContent>
              <p className="whitespace-pre-wrap text-sm leading-relaxed">
                {answer}
              </p>
            </CardContent>
          </Card>

          {sources.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">
                  Sources ({sources.length})
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>File</TableHead>
                      <TableHead>Score</TableHead>
                      <TableHead>Chunk</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {sources.map((src, i) => (
                      <TableRow key={i}>
                        <TableCell className="font-mono text-xs">
                          <span className="flex items-center gap-1.5">
                            <FileText className="size-3 shrink-0 text-muted-foreground" />
                            {src.filename}
                          </span>
                        </TableCell>
                        <TableCell className="text-xs">
                          {src.score.toFixed(3)}
                        </TableCell>
                        <TableCell className="max-w-[400px] truncate text-xs text-muted-foreground">
                          {src.chunk}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Notes tab
// ---------------------------------------------------------------------------

/**
 * Minimal frontmatter tag extractor — avoids pulling in a YAML library.
 * Reads the `tags: [a, b, c]` line from the raw markdown string.
 */
function extractTagsFromRaw(raw: string): string[] {
  const match = raw.match(/^tags:\s*\[([^\]]*)\]/m);
  if (!match) return [];
  return match[1]
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

/**
 * Compute backlinks: notes that contain [[TargetName]] pointing to `targetName`.
 */
function computeBacklinks(
  targetName: string,
  allNotes: { name: string; content: string }[],
): string[] {
  const pattern = new RegExp(`\\[\\[${escapeRegex(targetName)}\\]\\]`, "i");
  return allNotes
    .filter((n) => n.name !== targetName && pattern.test(n.content))
    .map((n) => n.name);
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

interface NotesTabProps {
  activePersona: string | null;
  workspacePath: string | null;
  /** When set, the tab should open this note path on mount/update (from graph navigation). */
  pendingNotePathRef?: React.MutableRefObject<string | null>;
}

function NotesTab({ activePersona, workspacePath, pendingNotePathRef }: NotesTabProps) {
  const [notes, setNotes] = useState<NoteItem[]>([]);
  const [noteContents, setNoteContents] = useState<Record<string, string>>({});
  const [activePath, setActivePath] = useState<string | null>(null);
  const [activeContent, setActiveContent] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** Derive the notes directory from active persona / workspace path. */
  const notesDir = useCallback((): string => {
    if (!activePersona) return "";
    if (workspacePath) {
      // Strip trailing slash, append /notes
      return `${workspacePath.replace(/\/$/, "")}/notes`;
    }
    return `workspace/agents/${activePersona}/notes`;
  }, [activePersona, workspacePath]);

  const loadNotes = useCallback(async () => {
    const dir = notesDir();
    if (!dir) {
      setNotes([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await listFiles(dir);
      const mdFiles = res.entries.filter(
        (e) => !e.is_dir && e.name.endsWith(".md"),
      );

      // Load all file contents for backlink computation
      const contents: Record<string, string> = {};
      await Promise.all(
        mdFiles.map(async (f) => {
          try {
            const r = await readFile(f.path);
            contents[f.path] = r.content;
          } catch {
            contents[f.path] = "";
          }
        }),
      );
      setNoteContents(contents);

      const items: NoteItem[] = mdFiles.map((f) => ({
        name: f.name.replace(/\.md$/, ""),
        path: f.path,
        tags: extractTagsFromRaw(contents[f.path] ?? ""),
      }));
      setNotes(items);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not load notes directory",
      );
    } finally {
      setLoading(false);
    }
  }, [notesDir]);

  // Reload whenever persona changes
  useEffect(() => {
    void loadNotes();
  }, [loadNotes]);

  // When navigating from the graph, open the pending note path once notes load
  useEffect(() => {
    if (!pendingNotePathRef || !pendingNotePathRef.current) return;
    const targetPath = pendingNotePathRef.current;
    const found = notes.find((n) => n.path === targetPath);
    if (found) {
      pendingNotePathRef.current = null;
      void handleSelect(found);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notes, pendingNotePathRef]);

  async function handleSelect(note: NoteItem) {
    setActivePath(note.path);
    // Use cached content if available; otherwise fetch
    if (noteContents[note.path] !== undefined) {
      setActiveContent(noteContents[note.path]);
    } else {
      try {
        const res = await readFile(note.path);
        setActiveContent(res.content);
        setNoteContents((prev) => ({ ...prev, [note.path]: res.content }));
      } catch {
        setActiveContent("");
      }
    }
  }

  async function handleSave(content: string) {
    if (!activePath) return;
    await writeFile(activePath, content);
    // Update cache and refresh tags
    setNoteContents((prev) => ({ ...prev, [activePath]: content }));
    setNotes((prev) =>
      prev.map((n) =>
        n.path === activePath
          ? { ...n, tags: extractTagsFromRaw(content) }
          : n,
      ),
    );
  }

  async function handleNewNote() {
    const dir = notesDir();
    if (!dir) return;
    const title = `Note ${new Date().toISOString().replace("T", " ").slice(0, 16)}`;
    const safeName = title.replace(/[^a-zA-Z0-9 _-]/g, "").replace(/\s+/g, "-");
    const path = `${dir}/${safeName}.md`;
    const content = newNoteTemplate(title);
    try {
      await writeFile(path, content);
      const newNote: NoteItem = {
        name: safeName,
        path,
        tags: [],
      };
      setNotes((prev) => [newNote, ...prev]);
      setNoteContents((prev) => ({ ...prev, [path]: content }));
      setActivePath(path);
      setActiveContent(content);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to create note");
    }
  }

  function handleNavigate(target: string) {
    const found = notes.find(
      (n) => n.name.toLowerCase() === target.toLowerCase(),
    );
    if (found) {
      void handleSelect(found);
    }
  }

  // Compute backlinks for the active note
  const activeNoteName =
    activePath
      ? notes.find((n) => n.path === activePath)?.name ?? null
      : null;

  const allNoteContentsForBacklinks = notes.map((n) => ({
    name: n.name,
    content: noteContents[n.path] ?? "",
  }));

  const backlinks = activeNoteName
    ? computeBacklinks(activeNoteName, allNoteContentsForBacklinks)
    : [];

  if (!activePersona) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-3 text-muted-foreground">
        <NotebookPen className="size-10 opacity-30" />
        <p className="text-sm">Select a persona to access its notes vault.</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
        {error}
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 gap-3">
      {/* Sidebar */}
      <div className="w-48 shrink-0 overflow-hidden rounded-xl ring-1 ring-foreground/10">
        <NoteList
          notes={notes}
          activePath={activePath}
          onSelect={(n) => void handleSelect(n)}
          onNewNote={() => void handleNewNote()}
          loading={loading}
        />
      </div>

      {/* Editor */}
      <div className="flex min-h-0 min-w-0 flex-1">
        <NoteEditor
          filePath={activePath}
          content={activeContent}
          backlinks={backlinks}
          onSave={handleSave}
          onNavigate={handleNavigate}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Graph tab
// ---------------------------------------------------------------------------

/** Extract [[wiki-link]] targets from a markdown string. */
function extractWikiLinks(content: string): string[] {
  const results: string[] = [];
  const re = /\[\[([^\]]+)\]\]/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(content)) !== null) {
    results.push(m[1].trim());
  }
  return results;
}

interface GraphTabProps {
  activePersona: string | null;
  workspacePath: string | null;
  /** Called when the user clicks a node — navigates to Notes tab and opens the note. */
  onOpenNote: (notePath: string) => void;
}

function GraphTab({ activePersona, workspacePath, onOpenNote }: GraphTabProps) {
  const [graphNodes, setGraphNodes] = useState<GraphNode[]>([]);
  const [graphEdges, setGraphEdges] = useState<GraphEdge[]>([]);
  const [selectedNode, setSelectedNode] = useState<string | undefined>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** Derive the notes directory from active persona / workspace path. */
  function notesDir(): string {
    if (!activePersona) return "";
    if (workspacePath) {
      return `${workspacePath.replace(/\/$/, "")}/notes`;
    }
    return `workspace/agents/${activePersona}/notes`;
  }

  const loadGraph = useCallback(async () => {
    const dir = notesDir();
    if (!dir) {
      setGraphNodes([]);
      setGraphEdges([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      // 1. List all .md files
      const res = await listFiles(dir);
      const mdFiles = res.entries.filter(
        (e) => !e.is_dir && e.name.endsWith(".md"),
      );

      // 2. Read content for each file (for wiki-link extraction)
      const contentMap: Record<string, string> = {};
      await Promise.all(
        mdFiles.map(async (f) => {
          try {
            const r = await readFile(f.path);
            contentMap[f.path] = r.content;
          } catch {
            contentMap[f.path] = "";
          }
        }),
      );

      // 3. Build a name->path lookup (label = filename without .md)
      const nameToPath = new Map<string, string>();
      for (const f of mdFiles) {
        nameToPath.set(f.name.replace(/\.md$/, "").toLowerCase(), f.path);
      }

      // 4. Build nodes
      const nodes: GraphNode[] = mdFiles.map((f) => ({
        id: f.path,
        label: f.name.replace(/\.md$/, ""),
        x: 0,
        y: 0,
      }));

      // 5. Build edges from [[wiki-links]]
      const edgeSet = new Set<string>();
      const edges: GraphEdge[] = [];
      for (const f of mdFiles) {
        const content = contentMap[f.path] ?? "";
        const links = extractWikiLinks(content);
        for (const link of links) {
          const targetPath = nameToPath.get(link.toLowerCase());
          if (!targetPath || targetPath === f.path) continue;
          const key = [f.path, targetPath].sort().join("||");
          if (!edgeSet.has(key)) {
            edgeSet.add(key);
            edges.push({ source: f.path, target: targetPath });
          }
        }
      }

      setGraphNodes(nodes);
      setGraphEdges(edges);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not build graph",
      );
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activePersona, workspacePath]);

  useEffect(() => {
    void loadGraph();
  }, [loadGraph]);

  function handleNodeClick(nodeId: string) {
    setSelectedNode(nodeId);
    onOpenNote(nodeId);
  }

  if (!activePersona) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-3 text-muted-foreground">
        <Network className="size-10 opacity-30" />
        <p className="text-sm">Select a persona to view its knowledge graph.</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center gap-2 text-sm text-muted-foreground">
        <RefreshCw className="size-4 animate-spin" />
        Building graph…
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-3">
        <p className="rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </p>
        <Button variant="outline" size="sm" onClick={loadGraph}>
          <RefreshCw className="mr-2 size-4" />
          Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      {/* Toolbar */}
      <div className="flex shrink-0 items-center justify-between">
        <p className="text-xs text-muted-foreground">
          {graphNodes.length} note{graphNodes.length !== 1 ? "s" : ""},&nbsp;
          {graphEdges.length} link{graphEdges.length !== 1 ? "s" : ""}
          {selectedNode && (
            <span className="ml-2 text-foreground">
              &mdash; selected:{" "}
              <span className="font-medium">
                {graphNodes.find((n) => n.id === selectedNode)?.label ?? selectedNode}
              </span>
            </span>
          )}
        </p>
        <Button variant="outline" size="sm" onClick={loadGraph} aria-label="Refresh graph">
          <RefreshCw className="mr-1.5 size-3.5" />
          Refresh
        </Button>
      </div>

      {/* Graph canvas */}
      <div className="min-h-0 flex-1">
        <VaultGraph
          nodes={graphNodes}
          edges={graphEdges}
          onNodeClick={handleNodeClick}
          selectedNode={selectedNode}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function KnowledgePage() {
  const { activePersona, workspacePath, setPersona } = useActivePersona();

  // Controlled tab state — needed so GraphTab can navigate to Notes tab
  const [activeTab, setActiveTab] = useState("files");

  // Path pre-selected from graph navigation (passed to NotesTab)
  const pendingNotePathRef = useRef<string | null>(null);

  function handleOpenNoteFromGraph(notePath: string) {
    pendingNotePathRef.current = notePath;
    setActiveTab("notes");
  }

  return (
    <div className="flex h-full flex-col space-y-6">
      {/* Header */}
      <div className="space-y-3">
        <div>
          <h1 className="text-xl font-semibold">Knowledge & Files</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Browse device files, manage RAG collections, ingest documents, and search the vector store.
          </p>
        </div>

        {/* Persona selector row */}
        <PersonaSelector
          activePersona={activePersona}
          onPersonaChange={setPersona}
        />
      </div>

      <Tabs
        value={activeTab}
        onValueChange={(v) => setActiveTab(v as string)}
        className="flex flex-1 flex-col min-h-0"
      >
        <TabsList>
          <TabsTrigger value="files">
            <FolderOpen className="mr-1.5 size-4" />
            Files
          </TabsTrigger>
          <TabsTrigger value="collections">
            <Database className="mr-1.5 size-4" />
            Collections
          </TabsTrigger>
          <TabsTrigger value="ingest">
            <FolderOpen className="mr-1.5 size-4" />
            Ingest
          </TabsTrigger>
          <TabsTrigger value="search">
            <Search className="mr-1.5 size-4" />
            Search
          </TabsTrigger>
          <TabsTrigger value="notes">
            <NotebookPen className="mr-1.5 size-4" />
            Notes
          </TabsTrigger>
          <TabsTrigger value="graph">
            <Network className="mr-1.5 size-4" />
            Graph
          </TabsTrigger>
        </TabsList>

        <TabsContent value="files" className="mt-4 flex flex-1 min-h-0">
          <FileManagerClient
            initialPath={
              activePersona
                ? personaFilesPath(activePersona, workspacePath)
                : undefined
            }
          />
        </TabsContent>

        <TabsContent value="collections" className="mt-4">
          <CollectionsTab activePersona={activePersona} />
        </TabsContent>

        <TabsContent value="ingest" className="mt-4">
          <IngestTab
            activePersona={activePersona}
            personaWorkspacePath={workspacePath}
          />
        </TabsContent>

        <TabsContent value="search" className="mt-4">
          <SearchTab activePersona={activePersona} />
        </TabsContent>

        <TabsContent value="notes" className="mt-4 flex flex-1 min-h-0">
          <NotesTab
            activePersona={activePersona}
            workspacePath={workspacePath}
            pendingNotePathRef={pendingNotePathRef}
          />
        </TabsContent>

        <TabsContent value="graph" className="mt-4 flex flex-1 min-h-0">
          <GraphTab
            activePersona={activePersona}
            workspacePath={workspacePath}
            onOpenNote={handleOpenNoteFromGraph}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
