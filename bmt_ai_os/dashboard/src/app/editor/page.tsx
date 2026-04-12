"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { listFiles, readFile, writeFile } from "@/lib/api";
import type { FileEntry } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Sparkles, TerminalSquare } from "lucide-react";
import { useWorkspace } from "@/hooks/use-workspace";
import { CodeEditor } from "./code-editor";
import { FileTree } from "./file-tree";
import { AiPromptPanel } from "./ai-prompt-panel";
import { EditorTerminal } from "./editor-terminal";

export default function EditorPage() {
  const { workspace, loading: wsLoading } = useWorkspace();

  const [dirPath, setDirPath] = useState("");
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [dirError, setDirError] = useState<string | null>(null);
  const [loadingDir, setLoadingDir] = useState(false);

  const [openFilePath, setOpenFilePath] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState("");
  const [editorContent, setEditorContent] = useState("");
  const [loadingFile, setLoadingFile] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);

  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<"idle" | "ok" | "error">("idle");

  const [pathInput, setPathInput] = useState("");
  const [showAi, setShowAi] = useState(false);
  const [showTerminal, setShowTerminal] = useState(false);

  const editorRef = useRef<{ setValue: (v: string) => void } | null>(null);

  // Ctrl+` keyboard shortcut to toggle the terminal panel
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === "`") {
        e.preventDefault();
        setShowTerminal((prev) => !prev);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const loadDir = useCallback(async (path: string) => {
    setLoadingDir(true);
    setDirError(null);
    try {
      const data = await listFiles(path);
      setEntries(data.entries);
      setDirPath(path);
      setPathInput(path);
    } catch (err) {
      setDirError(err instanceof Error ? err.message : "Failed to list directory");
    } finally {
      setLoadingDir(false);
    }
  }, []);

  useEffect(() => {
    if (!wsLoading) void loadDir(workspace);
  }, [loadDir, workspace, wsLoading]);

  const openFile = useCallback(async (entry: FileEntry) => {
    setLoadingFile(true);
    setFileError(null);
    setOpenFilePath(entry.path);
    try {
      const data = await readFile(entry.path);
      setFileContent(data.content);
      setEditorContent(data.content);
    } catch (err) {
      setFileError(err instanceof Error ? err.message : "Failed to read file");
      setFileContent("");
      setEditorContent("");
    } finally {
      setLoadingFile(false);
    }
  }, []);

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
          <Button
            size="sm"
            variant={showTerminal ? "default" : "outline"}
            onClick={() => setShowTerminal(!showTerminal)}
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
            onClick={() => setShowAi(!showAi)}
            className="h-7 gap-1.5 text-xs"
          >
            <Sparkles className="size-3" />
            AI Assist
          </Button>
        </div>
      </div>

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
        <div className="flex min-w-0 flex-1 flex-col bg-[#1e1e1e]">
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
                Select a file from the sidebar to open it.
              </div>
            )}
          </div>

          <EditorTerminal
            visible={showTerminal}
            onClose={() => setShowTerminal(false)}
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
              onClose={() => setShowAi(false)}
            />
          </div>
        )}
      </div>
    </div>
  );
}

// Simple language detection for AI context
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
