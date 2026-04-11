"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Editor, { type OnMount } from "@monaco-editor/react";

// ---------------------------------------------------------------------------
// Language detection from file extension
// ---------------------------------------------------------------------------

const EXT_TO_LANGUAGE: Record<string, string> = {
  ts: "typescript",
  tsx: "typescript",
  js: "javascript",
  jsx: "javascript",
  mjs: "javascript",
  cjs: "javascript",
  py: "python",
  sh: "shell",
  bash: "shell",
  zsh: "shell",
  yml: "yaml",
  yaml: "yaml",
  json: "json",
  md: "markdown",
  mdx: "markdown",
  css: "css",
  scss: "scss",
  html: "html",
  htm: "html",
  xml: "xml",
  sql: "sql",
  rs: "rust",
  go: "go",
  java: "java",
  kt: "kotlin",
  swift: "swift",
  c: "c",
  cpp: "cpp",
  cc: "cpp",
  h: "cpp",
  cs: "csharp",
  rb: "ruby",
  php: "php",
  toml: "ini",
  ini: "ini",
  cfg: "ini",
  conf: "ini",
  dockerfile: "dockerfile",
  makefile: "makefile",
  txt: "plaintext",
};

function detectLanguage(filePath: string): string {
  const name = filePath.split("/").pop() ?? "";
  const lower = name.toLowerCase();

  // Special filenames
  if (lower === "dockerfile") return "dockerfile";
  if (lower === "makefile" || lower === "gnumakefile") return "makefile";
  if (lower === ".env" || lower.startsWith(".env.")) return "shell";

  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  return EXT_TO_LANGUAGE[ext] ?? "plaintext";
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface FileEntry {
  name: string;
  path: string;
  is_dir: boolean;
  size: number | null;
  extension: string | null;
}

interface CodeEditorProps {
  filePath: string | null;
  initialContent: string;
  onSave: (content: string) => Promise<void>;
  saving: boolean;
}

// ---------------------------------------------------------------------------
// CodeEditor component
// ---------------------------------------------------------------------------

export function CodeEditor({
  filePath,
  initialContent,
  onSave,
  saving,
}: CodeEditorProps) {
  const [value, setValue] = useState(initialContent);
  const [isDirty, setIsDirty] = useState(false);
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);

  // Sync when a new file is opened
  useEffect(() => {
    setValue(initialContent);
    setIsDirty(false);
  }, [initialContent, filePath]);

  const handleMount: OnMount = (editor) => {
    editorRef.current = editor;
    editor.focus();
  };

  const handleChange = useCallback((val: string | undefined) => {
    setValue(val ?? "");
    setIsDirty(true);
  }, []);

  const handleSave = useCallback(async () => {
    if (!filePath || saving) return;
    await onSave(value);
    setIsDirty(false);
  }, [filePath, saving, onSave, value]);

  // Ctrl+S / Cmd+S keybinding
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        void handleSave();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [handleSave]);

  const language = filePath ? detectLanguage(filePath) : "plaintext";

  return (
    <div className="flex h-full flex-col">
      {/* Toolbar */}
      <div className="flex h-9 shrink-0 items-center justify-between border-b border-border bg-muted/30 px-3">
        <span className="truncate font-mono text-xs text-muted-foreground">
          {filePath ?? "No file open"}
        </span>
        <div className="flex items-center gap-2">
          {isDirty && (
            <span className="text-xs text-amber-500">unsaved</span>
          )}
          <span className="text-xs text-muted-foreground">{language}</span>
          <button
            onClick={() => void handleSave()}
            disabled={!filePath || saving || !isDirty}
            className="rounded px-2.5 py-0.5 text-xs font-medium transition-colors disabled:pointer-events-none disabled:opacity-40 bg-primary text-primary-foreground hover:bg-primary/90"
            aria-label="Save file (Ctrl+S)"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      {/* Monaco editor */}
      <div className="flex-1 overflow-hidden">
        <Editor
          height="100%"
          language={language}
          value={value}
          theme="vs-dark"
          onChange={handleChange}
          onMount={handleMount}
          options={{
            fontSize: 13,
            fontFamily: '"JetBrains Mono", "Fira Code", Consolas, monospace',
            fontLigatures: true,
            lineNumbers: "on",
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            wordWrap: "on",
            tabSize: 2,
            renderWhitespace: "selection",
            bracketPairColorization: { enabled: true },
            padding: { top: 12, bottom: 12 },
            smoothScrolling: true,
          }}
          loading={
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
              Loading editor…
            </div>
          }
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// FileTree component
// ---------------------------------------------------------------------------

interface FileTreeProps {
  entries: FileEntry[];
  currentPath: string | null;
  onSelect: (entry: FileEntry) => void;
  onNavigate: (path: string) => void;
  rootPath: string;
}

export function FileTree({
  entries,
  currentPath,
  onSelect,
  onNavigate,
  rootPath,
}: FileTreeProps) {
  return (
    <div className="flex h-full flex-col overflow-y-auto text-xs">
      <div className="sticky top-0 border-b border-border bg-muted/50 px-3 py-2 font-medium text-muted-foreground">
        <span className="block truncate font-mono" title={rootPath}>
          {rootPath.split("/").pop() || rootPath}
        </span>
      </div>
      <div className="flex flex-col gap-px p-1">
        {entries.map((entry) => {
          const isActive = !entry.is_dir && entry.path === currentPath;
          return (
            <button
              key={entry.path}
              onClick={() => {
                if (entry.is_dir) {
                  onNavigate(entry.path);
                } else {
                  onSelect(entry);
                }
              }}
              title={entry.path}
              className={[
                "flex w-full items-center gap-1.5 rounded px-2 py-1 text-left transition-colors",
                isActive
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-sidebar-foreground/80 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground",
              ].join(" ")}
              aria-current={isActive ? "page" : undefined}
            >
              <span className="shrink-0 text-[10px] text-muted-foreground">
                {entry.is_dir ? "D" : "F"}
              </span>
              <span className="truncate font-mono">{entry.name}</span>
              {entry.size !== null && !entry.is_dir && (
                <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">
                  {entry.size < 1024
                    ? `${entry.size}B`
                    : `${(entry.size / 1024).toFixed(0)}K`}
                </span>
              )}
            </button>
          );
        })}
        {entries.length === 0 && (
          <p className="px-2 py-2 italic text-muted-foreground">
            Empty directory
          </p>
        )}
      </div>
    </div>
  );
}
