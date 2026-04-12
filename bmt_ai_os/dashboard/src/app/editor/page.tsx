"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { listFiles, readFile, writeFile } from "@/lib/api";
import type { FileEntry } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Sparkles, TerminalSquare, History, X } from "lucide-react";
import { useWorkspace } from "@/hooks/use-workspace";
import { useEditorSession } from "@/hooks/use-editor-session";
import { CodeEditor } from "./code-editor";
import { FileTree } from "./file-tree";
import { AiPromptPanel } from "./ai-prompt-panel";
import { EditorTerminal } from "./editor-terminal";

export default function EditorPage() {
  const { workspace, loading: wsLoading } = useWorkspace();
  const { session, update, addRecentFile, addPromptHistory } = useEditorSession();

  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [dirError, setDirError] = useState<string | null>(null);
  const [loadingDir, setLoadingDir] = useState(false);

  const [fileContent, setFileContent] = useState("");
  const [editorContent, setEditorContent] = useState("");
  const [loadingFile, setLoadingFile] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);

  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<"idle" | "ok" | "error">("idle");

  const [pathInput, setPathInput] = useState("");
  const [showRecent, setShowRecent] = useState(false);

  const editorRef = useRef<{ setValue: (v: string) => void } | null>(null);
  const initialLoadDone = useRef(false);

  // Derive from session
  const dirPath = session.dirPath;
  const openFilePath = session.openFilePath;
  const showAi = session.showAi;
  const showTerminal = session.showTerminal;

  // Ctrl+` keyboard shortcut to toggle terminal
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === "`") {
        e.preventDefault();
        update({ showTerminal: !session.showTerminal });
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [session.showTerminal, update]);

  // Load directory
  const loadDir = useCallback(
    async (path: string) => {
      setLoadingDir(true);
      setDirError(null);
      try {
        const data = await listFiles(path);
        setEntries(data.entries);
        update({ dirPath: path });
        setPathInput(path);
      } catch (err) {
        setDirError(
          err instanceof Error ? err.message : "Failed to list directory",
        );
      } finally {
        setLoadingDir(false);
      }
    },
    [update],
  );

  // Initial load: restore session directory or fall back to workspace
  useEffect(() => {
    if (wsLoading || initialLoadDone.current) return;
    initialLoadDone.current = true;
    const initialDir = session.dirPath || workspace;
    setPathInput(initialDir);
    void loadDir(initialDir);
  }, [wsLoading, workspace, session.dirPath, loadDir]);

  // Restore last open file after directory loads
  useEffect(() => {
    if (
      initialLoadDone.current &&
      session.openFilePath &&
      entries.length > 0 &&
      !fileContent &&
      !loadingFile
    ) {
      const entry = entries.find((e) => e.path === session.openFilePath);
      if (entry && !entry.is_dir) {
        void openFileByPath(session.openFilePath);
      }
    }
    // Only run once after entries load
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entries]);

  // Open file
  const openFile = useCallback(
    async (entry: FileEntry) => {
      setLoadingFile(true);
      setFileError(null);
      update({ openFilePath: entry.path });
      addRecentFile(entry.path);
      try {
        const data = await readFile(entry.path);
        setFileContent(data.content);
        setEditorContent(data.content);
      } catch (err) {
        setFileError(
          err instanceof Error ? err.message : "Failed to read file",
        );
        setFileContent("");
        setEditorContent("");
      } finally {
        setLoadingFile(false);
      }
    },
    [update, addRecentFile],
  );

  // Open file by path (for recent files and session restore)
  const openFileByPath = useCallback(
    async (path: string) => {
      setLoadingFile(true);
      setFileError(null);
      update({ openFilePath: path });
      addRecentFile(path);
      try {
        const data = await readFile(path);
        setFileContent(data.content);
        setEditorContent(data.content);
      } catch (err) {
        setFileError(
          err instanceof Error ? err.message : "Failed to read file",
        );
        setFileContent("");
        setEditorContent("");
      } finally {
        setLoadingFile(false);
      }
    },
    [update, addRecentFile],
  );

  // Save file
  const saveFile = useCallback(
    async (content: string) => {
      if (!openFilePath) return;
      setSaving(true);
      setSaveStatus("idle");
      try {
        await writeFile(openFilePath, content);
        setFileContent(content);
        setSaveStatus("ok");
        setTimeout(() => setSaveStatus("idle"), 2000);
      } catch {
        setSaveStatus("error");
      } finally {
        setSaving(false);
      }
    },
    [openFilePath],
  );

  const handleAiApply = useCallback((code: string) => {
    setEditorContent(code);
    editorRef.current?.setValue(code);
  }, []);

  const language = openFilePath
    ? detectLanguageSimple(openFilePath)
    : "plaintext";

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between pb-4">
        <div>
          <h1 className="text-xl font-semibold">Code Editor</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Browse and edit files on the device.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {saveStatus === "ok" && (
            <span className="text-xs text-green-500">Saved</span>
          )}
          {saveStatus === "error" && (
            <span className="text-xs text-red-500">Save failed</span>
          )}

          {/* Recent files */}
          <div className="relative">
            <Button
              size="sm"
              variant={showRecent ? "default" : "outline"}
              onClick={() => setShowRecent(!showRecent)}
              className="h-7 gap-1.5 text-xs"
              title="Recent files"
              disabled={session.recentFiles.length === 0}
            >
              <History className="size-3" />
              Recent
              {session.recentFiles.length > 0 && (
                <Badge variant="secondary" className="ml-1 h-4 px-1 text-[10px]">
                  {session.recentFiles.length}
                </Badge>
              )}
            </Button>
            {showRecent && session.recentFiles.length > 0 && (
              <div className="absolute right-0 top-full z-20 mt-1 w-72 rounded-lg border border-border bg-popover p-1 shadow-lg">
                <div className="flex items-center justify-between px-2 py-1">
                  <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">
                    Recent Files
                  </span>
                  <button
                    onClick={() => setShowRecent(false)}
                    className="rounded p-0.5 text-muted-foreground hover:text-foreground"
                    aria-label="Close recent files"
                  >
                    <X className="size-3" />
                  </button>
                </div>
                <div className="max-h-60 overflow-y-auto">
                  {session.recentFiles.map((path) => {
                    const name = path.split("/").pop() ?? path;
                    const dir = path.substring(0, path.lastIndexOf("/")) || "/";
                    const isActive = path === openFilePath;
                    return (
                      <button
                        key={path}
                        onClick={() => {
                          void openFileByPath(path);
                          setShowRecent(false);
                        }}
                        className={`flex w-full flex-col rounded px-2 py-1.5 text-left transition-colors ${
                          isActive
                            ? "bg-accent text-accent-foreground"
                            : "hover:bg-muted"
                        }`}
                      >
                        <span className="truncate font-mono text-xs font-medium">
                          {name}
                        </span>
                        <span className="truncate text-[10px] text-muted-foreground">
                          {dir}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>

          <Button
            size="sm"
            variant={showTerminal ? "default" : "outline"}
            onClick={() => update({ showTerminal: !showTerminal })}
            className="h-7 gap-1.5 text-xs"
            title="Toggle terminal (Ctrl+`)"
            aria-pressed={showTerminal}
          >
            <TerminalSquare className="size-3" />
            Terminal
          </Button>
          <Button
            size="sm"
            variant={showAi ? "default" : "outline"}
            onClick={() => update({ showAi: !showAi })}
            className="h-7 gap-1.5 text-xs"
            aria-pressed={showAi}
          >
            <Sparkles className="size-3" />
            AI Assist
          </Button>
        </div>
      </div>

      {/* Path bar */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void loadDir(pathInput);
        }}
        className="mb-3 flex gap-2"
      >
        <Input
          value={pathInput}
          onChange={(e) => setPathInput(e.target.value)}
          className="flex-1 font-mono text-xs h-8"
          placeholder="/path/to/directory"
          aria-label="Directory path"
          spellCheck={false}
        />
        <Button type="submit" variant="outline" size="sm" disabled={loadingDir}>
          {loadingDir ? "Loading..." : "Go"}
        </Button>
      </form>

      {/* Main layout */}
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
              onRefresh={() => void loadDir(dirPath)}
              rootPath={dirPath}
            />
          )}
        </aside>

        {/* Editor pane */}
        <div className="flex min-w-0 flex-1 flex-col bg-background">
          <div className="flex min-h-0 flex-1 flex-col">
            {loadingFile ? (
              <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
                Loading file...
              </div>
            ) : fileError ? (
              <div className="flex flex-1 items-center justify-center p-4 text-sm text-red-400">
                {fileError}
              </div>
            ) : openFilePath ? (
              <CodeEditor
                ref={editorRef}
                filePath={openFilePath}
                initialContent={fileContent}
                onSave={saveFile}
                onContentChange={setEditorContent}
                saving={saving}
              />
            ) : (
              <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
                {session.recentFiles.length > 0
                  ? "Select a file or open a recent one."
                  : "Select a file from the sidebar to open it."}
              </div>
            )}
          </div>

          <EditorTerminal
            visible={showTerminal}
            onClose={() => update({ showTerminal: false })}
          />
        </div>

        {/* AI Prompt Panel */}
        {showAi && (
          <div className="w-80 shrink-0">
            <AiPromptPanel
              filePath={openFilePath}
              fileContent={editorContent}
              language={language}
              onApply={handleAiApply}
              onClose={() => update({ showAi: false })}
              promptHistory={session.promptHistory}
              onPromptSubmit={addPromptHistory}
              currentDir={dirPath}
              onFileCreated={() => void loadDir(dirPath)}
            />
          </div>
        )}
      </div>
    </div>
  );
}

function detectLanguageSimple(filePath: string): string {
  const ext = filePath.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, string> = {
    ts: "typescript", tsx: "typescript", js: "javascript", jsx: "javascript",
    py: "python", rs: "rust", go: "go", java: "java", rb: "ruby",
    sh: "shell", yml: "yaml", yaml: "yaml", json: "json", md: "markdown",
    css: "css", html: "html", sql: "sql", c: "c", cpp: "cpp",
  };
  return map[ext] ?? "plaintext";
}
