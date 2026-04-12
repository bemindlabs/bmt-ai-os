"use client";

import React, { useState, useEffect, useCallback } from "react";
import { listFiles, readFile, writeFile } from "@/lib/api";
import { NotebookPen } from "lucide-react";
import { NoteEditor, newNoteTemplate } from "./note-editor";
import { NoteList, type NoteItem } from "./note-list";

// ---------------------------------------------------------------------------
// Helpers (Notes-tab-local)
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

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface NotesTabProps {
  activePersona: string | null;
  workspacePath: string | null;
  /** When set, the tab should open this note path on mount/update (from graph navigation). */
  pendingNotePathRef?: React.MutableRefObject<string | null>;
}

export function NotesTab({ activePersona, workspacePath, pendingNotePathRef }: NotesTabProps) {
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
