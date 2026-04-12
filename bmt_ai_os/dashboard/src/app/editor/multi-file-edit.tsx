"use client";

import { useCallback, useState } from "react";
import { writeFile } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  FolderEdit,
  Check,
  FileText,
  ChevronRight,
  Loader2,
  X,
  AlertTriangle,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface FileEdit {
  path: string;
  content: string;
  language: string;
}

type FileStatus = "pending" | "applying" | "applied" | "error";

interface MultiFileEditProps {
  response: string;
  currentDir: string;
  onApplyFile: (path: string, content: string) => void;
  onApplyAll: () => void;
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Language detection from file extension
// ---------------------------------------------------------------------------

const EXT_LANGUAGE: Record<string, string> = {
  ts: "typescript",
  tsx: "typescript",
  js: "javascript",
  jsx: "javascript",
  mjs: "javascript",
  cjs: "javascript",
  py: "python",
  rb: "ruby",
  go: "go",
  rs: "rust",
  java: "java",
  kt: "kotlin",
  swift: "swift",
  c: "c",
  cpp: "cpp",
  cc: "cpp",
  h: "c",
  hpp: "cpp",
  cs: "csharp",
  php: "php",
  html: "html",
  htm: "html",
  css: "css",
  scss: "scss",
  less: "less",
  json: "json",
  yaml: "yaml",
  yml: "yaml",
  toml: "toml",
  md: "markdown",
  mdx: "markdown",
  sh: "bash",
  bash: "bash",
  zsh: "bash",
  sql: "sql",
  graphql: "graphql",
  gql: "graphql",
  xml: "xml",
  svg: "xml",
  txt: "plaintext",
};

function detectLanguage(filePath: string): string {
  const ext = filePath.split(".").pop()?.toLowerCase() ?? "";
  return EXT_LANGUAGE[ext] ?? "plaintext";
}

// ---------------------------------------------------------------------------
// Parser
// ---------------------------------------------------------------------------

export function parseMultiFileResponse(response: string): FileEdit[] {
  // Split on "### FILE:" markers (case-sensitive, leading whitespace allowed)
  const FILE_MARKER = /^[ \t]*###[ \t]+FILE:[ \t]*(.+)$/m;
  const parts = response.split(/^[ \t]*###[ \t]+FILE:[ \t]*/m);

  const results: FileEdit[] = [];

  for (let i = 1; i < parts.length; i++) {
    const part = parts[i];
    // First line is the file path (trim trailing whitespace / carriage returns)
    const newlineIdx = part.indexOf("\n");
    if (newlineIdx === -1) continue;

    const rawPath = part.slice(0, newlineIdx).trim();
    if (!rawPath) continue;

    const rest = part.slice(newlineIdx + 1);

    // Extract content from a fenced code block (``` or ~~~), if present
    const fenceMatch = rest.match(/^[ \t]*(`{3,}|~{3,})([\w+-]*)[^\n]*\n([\s\S]*?)^\1[ \t]*$/m);
    const content = fenceMatch ? fenceMatch[3] : rest.trimEnd();

    // Remove trailing newline added by the fence
    const trimmedContent = content.replace(/\n$/, "");

    results.push({
      path: rawPath,
      content: trimmedContent,
      language: detectLanguage(rawPath),
    });
  }

  // Silence unused import warning — FILE_MARKER is referenced for documentation.
  void FILE_MARKER;

  return results;
}

// ---------------------------------------------------------------------------
// File tree item
// ---------------------------------------------------------------------------

interface FileTreeItemProps {
  file: FileEdit;
  selected: boolean;
  status: FileStatus;
  onSelect: () => void;
}

function statusColor(s: FileStatus): string {
  switch (s) {
    case "applied":
      return "text-green-500";
    case "error":
      return "text-red-500";
    case "applying":
      return "text-blue-400";
    default:
      return "text-muted-foreground";
  }
}

function FileTreeItem({ file, selected, status, onSelect }: FileTreeItemProps) {
  const segments = file.path.split("/");
  const fileName = segments.pop() ?? file.path;
  const dir = segments.join("/");

  return (
    <button
      type="button"
      onClick={onSelect}
      className={[
        "w-full flex items-center gap-2 px-2 py-1.5 text-left rounded transition-colors",
        selected
          ? "bg-primary/10 text-primary"
          : "hover:bg-muted/50 text-foreground",
      ].join(" ")}
    >
      {status === "applying" ? (
        <Loader2 className="size-3 shrink-0 animate-spin text-blue-400" />
      ) : status === "applied" ? (
        <Check className="size-3 shrink-0 text-green-500" />
      ) : status === "error" ? (
        <AlertTriangle className="size-3 shrink-0 text-red-500" />
      ) : (
        <FileText className={`size-3 shrink-0 ${statusColor(status)}`} />
      )}
      <span className="flex-1 min-w-0">
        <span className="block truncate text-xs font-medium">{fileName}</span>
        {dir && (
          <span className="block truncate text-[10px] text-muted-foreground">
            {dir}
          </span>
        )}
      </span>
      {selected && <ChevronRight className="size-3 shrink-0 text-primary" />}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Total line count helper
// ---------------------------------------------------------------------------

function totalLines(files: FileEdit[]): number {
  return files.reduce((sum, f) => sum + f.content.split("\n").length, 0);
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function MultiFileEdit({
  response,
  currentDir,
  onApplyFile,
  onApplyAll: onApplyAllProp,
  onClose,
}: MultiFileEditProps) {
  const files = parseMultiFileResponse(response);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [statuses, setStatuses] = useState<Record<string, FileStatus>>(() =>
    Object.fromEntries(files.map((f) => [f.path, "pending" as FileStatus])),
  );

  const setStatus = useCallback((path: string, status: FileStatus) => {
    setStatuses((prev) => ({ ...prev, [path]: status }));
  }, []);

  const resolvePath = useCallback(
    (filePath: string): string => {
      if (filePath.startsWith("/")) return filePath;
      if (currentDir) return `${currentDir}/${filePath}`;
      return filePath;
    },
    [currentDir],
  );

  const handleApplyFile = useCallback(
    async (file: FileEdit) => {
      setStatus(file.path, "applying");
      try {
        await writeFile(resolvePath(file.path), file.content);
        setStatus(file.path, "applied");
        onApplyFile(file.path, file.content);
      } catch {
        setStatus(file.path, "error");
      }
    },
    [resolvePath, onApplyFile, setStatus],
  );

  const handleApplyAll = useCallback(async () => {
    for (const file of files) {
      if (statuses[file.path] === "applied") continue;
      await handleApplyFile(file);
    }
    onApplyAllProp();
  }, [files, statuses, handleApplyFile, onApplyAllProp]);

  const selectedFile = files[selectedIndex];

  const appliedCount = Object.values(statuses).filter((s) => s === "applied").length;
  const errorCount = Object.values(statuses).filter((s) => s === "error").length;
  const allApplied = appliedCount === files.length;

  if (files.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center p-4">
        <p className="text-xs text-muted-foreground text-center">
          No file blocks found in the AI response.
          <br />
          Make sure the response uses the{" "}
          <code className="font-mono text-[10px] bg-muted px-1 rounded">### FILE:</code> format.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Header */}
      <div className="flex items-center justify-between gap-2 border-b border-border bg-muted/30 px-3 py-2 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <FolderEdit className="size-3.5 text-purple-400 shrink-0" />
          <span className="text-xs font-medium truncate">Multi-file edit</span>
          <Badge variant="secondary" className="text-[10px] px-1.5 py-0 shrink-0">
            {files.length} {files.length === 1 ? "file" : "files"}
          </Badge>
          <span className="text-[10px] text-muted-foreground shrink-0">
            {totalLines(files).toLocaleString()} lines
          </span>
          {appliedCount > 0 && (
            <Badge className="text-[10px] px-1.5 py-0 bg-green-500/10 text-green-600 border-green-500/20 shrink-0">
              {appliedCount}/{files.length} applied
            </Badge>
          )}
          {errorCount > 0 && (
            <Badge className="text-[10px] px-1.5 py-0 bg-red-500/10 text-red-600 border-red-500/20 shrink-0">
              {errorCount} error{errorCount > 1 ? "s" : ""}
            </Badge>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded p-0.5 text-muted-foreground hover:text-foreground shrink-0"
          aria-label="Close multi-file edit"
        >
          <X className="size-3.5" />
        </button>
      </div>

      {/* Body: file tree + preview */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Left: file tree */}
        <div className="w-44 shrink-0 flex flex-col border-r border-border overflow-y-auto bg-muted/10">
          <div className="px-2 pt-2 pb-1">
            <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
              Files
            </span>
          </div>
          <div className="flex-1 px-1 pb-2 space-y-0.5">
            {files.map((file, idx) => (
              <FileTreeItem
                key={file.path}
                file={file}
                selected={selectedIndex === idx}
                status={statuses[file.path] ?? "pending"}
                onSelect={() => setSelectedIndex(idx)}
              />
            ))}
          </div>
        </div>

        {/* Right: preview pane */}
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {selectedFile ? (
            <>
              {/* File header */}
              <div className="flex items-center justify-between gap-2 border-b border-border bg-muted/20 px-3 py-1.5 shrink-0">
                <div className="flex items-center gap-1.5 min-w-0">
                  <FileText className="size-3 shrink-0 text-muted-foreground" />
                  <span className="text-xs font-mono truncate">{selectedFile.path}</span>
                  <Badge variant="outline" className="text-[10px] px-1.5 py-0 shrink-0">
                    {selectedFile.language}
                  </Badge>
                  <span className="text-[10px] text-muted-foreground shrink-0">
                    {selectedFile.content.split("\n").length} lines
                  </span>
                </div>
                <Button
                  size="sm"
                  variant={statuses[selectedFile.path] === "applied" ? "outline" : "default"}
                  onClick={() => void handleApplyFile(selectedFile)}
                  disabled={statuses[selectedFile.path] === "applying"}
                  className="h-6 gap-1 text-[11px] shrink-0"
                >
                  {statuses[selectedFile.path] === "applying" ? (
                    <>
                      <Loader2 className="size-3 animate-spin" />
                      Applying...
                    </>
                  ) : statuses[selectedFile.path] === "applied" ? (
                    <>
                      <Check className="size-3" />
                      Applied
                    </>
                  ) : statuses[selectedFile.path] === "error" ? (
                    <>
                      <AlertTriangle className="size-3" />
                      Retry
                    </>
                  ) : (
                    <>
                      <Check className="size-3" />
                      Apply
                    </>
                  )}
                </Button>
              </div>

              {/* Code preview */}
              <div className="flex-1 overflow-auto p-3">
                <pre className="text-xs font-mono text-foreground whitespace-pre-wrap break-words leading-relaxed">
                  {selectedFile.content}
                </pre>
              </div>
            </>
          ) : (
            <div className="flex flex-1 items-center justify-center">
              <p className="text-xs text-muted-foreground">Select a file to preview</p>
            </div>
          )}
        </div>
      </div>

      {/* Footer: Apply All */}
      <div className="shrink-0 border-t border-border px-3 py-2 flex items-center gap-2 bg-muted/10">
        <Button
          size="sm"
          onClick={() => void handleApplyAll()}
          disabled={allApplied || files.some((f) => statuses[f.path] === "applying")}
          className="h-7 gap-1.5 text-xs"
        >
          {allApplied ? (
            <>
              <Check className="size-3" />
              All Applied
            </>
          ) : (
            <>
              <FolderEdit className="size-3" />
              Apply All ({files.length - appliedCount} remaining)
            </>
          )}
        </Button>
        <span className="text-[10px] text-muted-foreground">
          {allApplied
            ? "All files have been written to disk."
            : "Apply all files to disk at once, or apply each individually."}
        </span>
      </div>
    </div>
  );
}
