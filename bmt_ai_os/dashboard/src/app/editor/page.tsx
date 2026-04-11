"use client";

import { useCallback, useEffect, useState } from "react";
import { CodeEditor, FileTree, type FileEntry } from "./code-editor";

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

const DEFAULT_ROOT = "/opt/bmt";

function getAuthHeader(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const token = localStorage.getItem("bmt_auth_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function apiListDir(path: string): Promise<FileEntry[]> {
  const res = await fetch(
    `/api/v1/files?path=${encodeURIComponent(path)}`,
    { headers: getAuthHeader() },
  );
  if (!res.ok) throw new Error(`List failed: ${res.status}`);
  const data = (await res.json()) as { entries: FileEntry[] };
  return data.entries;
}

async function apiReadFile(path: string): Promise<string> {
  const res = await fetch(
    `/api/v1/files/read?path=${encodeURIComponent(path)}`,
    { headers: getAuthHeader() },
  );
  if (!res.ok) throw new Error(`Read failed: ${res.status}`);
  const data = (await res.json()) as { content: string };
  return data.content;
}

async function apiWriteFile(path: string, content: string): Promise<void> {
  const res = await fetch("/api/v1/files/write", {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...getAuthHeader() },
    body: JSON.stringify({ path, content }),
  });
  if (!res.ok) throw new Error(`Write failed: ${res.status}`);
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function EditorPage() {
  const [dirPath, setDirPath] = useState(DEFAULT_ROOT);
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [dirError, setDirError] = useState<string | null>(null);
  const [loadingDir, setLoadingDir] = useState(false);

  const [openFilePath, setOpenFilePath] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState("");
  const [loadingFile, setLoadingFile] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);

  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<"idle" | "ok" | "error">("idle");

  // Path bar input
  const [pathInput, setPathInput] = useState(DEFAULT_ROOT);

  // Load directory
  const loadDir = useCallback(async (path: string) => {
    setLoadingDir(true);
    setDirError(null);
    try {
      const list = await apiListDir(path);
      setEntries(list);
      setDirPath(path);
      setPathInput(path);
    } catch (err) {
      setDirError(err instanceof Error ? err.message : "Failed to list directory");
    } finally {
      setLoadingDir(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    void loadDir(DEFAULT_ROOT);
  }, [loadDir]);

  // Open file
  const openFile = useCallback(async (entry: FileEntry) => {
    setLoadingFile(true);
    setFileError(null);
    setOpenFilePath(entry.path);
    try {
      const content = await apiReadFile(entry.path);
      setFileContent(content);
    } catch (err) {
      setFileError(err instanceof Error ? err.message : "Failed to read file");
      setFileContent("");
    } finally {
      setLoadingFile(false);
    }
  }, []);

  // Save file
  const saveFile = useCallback(
    async (content: string) => {
      if (!openFilePath) return;
      setSaving(true);
      setSaveStatus("idle");
      try {
        await apiWriteFile(openFilePath, content);
        setSaveStatus("ok");
        setTimeout(() => setSaveStatus("idle"), 2000);
      } catch (err) {
        setSaveStatus("error");
        console.error("Save error:", err);
      } finally {
        setSaving(false);
      }
    },
    [openFilePath],
  );

  return (
    <div className="flex h-full flex-col">
      {/* Page header */}
      <div className="flex shrink-0 items-center justify-between pb-4">
        <div>
          <h1 className="text-xl font-semibold">Code Editor</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Browse and edit files on the device.
          </p>
        </div>
        {saveStatus === "ok" && (
          <span className="text-xs text-green-500">Saved</span>
        )}
        {saveStatus === "error" && (
          <span className="text-xs text-red-500">Save failed</span>
        )}
      </div>

      {/* Path navigation bar */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void loadDir(pathInput);
        }}
        className="mb-3 flex gap-2"
      >
        <input
          value={pathInput}
          onChange={(e) => setPathInput(e.target.value)}
          className="flex-1 rounded border border-input bg-background px-3 py-1.5 font-mono text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
          placeholder="/path/to/directory"
          aria-label="Directory path"
          spellCheck={false}
        />
        <button
          type="submit"
          disabled={loadingDir}
          className="rounded border border-input bg-muted px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted/80 disabled:opacity-50"
        >
          {loadingDir ? "Loading…" : "Go"}
        </button>
      </form>

      {/* Main editor layout */}
      <div className="flex min-h-0 flex-1 overflow-hidden rounded-lg border border-border">
        {/* File tree sidebar */}
        <aside className="w-56 shrink-0 border-r border-border bg-sidebar">
          {dirError ? (
            <div className="p-3 text-xs text-red-400">{dirError}</div>
          ) : (
            <FileTree
              entries={entries}
              currentPath={openFilePath}
              onSelect={openFile}
              onNavigate={(path) => void loadDir(path)}
              rootPath={dirPath}
            />
          )}
        </aside>

        {/* Editor pane */}
        <div className="flex min-w-0 flex-1 flex-col bg-[#1e1e1e]">
          {loadingFile ? (
            <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
              Loading file…
            </div>
          ) : fileError ? (
            <div className="flex flex-1 items-center justify-center p-4 text-sm text-red-400">
              {fileError}
            </div>
          ) : (
            <CodeEditor
              filePath={openFilePath}
              initialContent={fileContent}
              onSave={saveFile}
              saving={saving}
            />
          )}

          {!openFilePath && !loadingFile && !fileError && (
            <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
              Select a file from the sidebar to open it.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
