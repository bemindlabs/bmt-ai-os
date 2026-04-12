"use client";

import { useState, useEffect } from "react";
import {
  Download,
  Database,
  X,
  FileText,
  FileImage,
  File,
  AlertCircle,
  Loader2,
} from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  type FileEntry,
  readFile,
  downloadFileUrl,
  ingestPath,
} from "@/lib/api";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
import { MarkdownPreview } from "@/components/markdown-preview";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function extensionLanguage(filename: string): string {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, string> = {
    ts: "typescript",
    tsx: "tsx",
    js: "javascript",
    jsx: "jsx",
    py: "python",
    go: "go",
    rs: "rust",
    c: "c",
    cpp: "cpp",
    h: "c",
    java: "java",
    rb: "ruby",
    sh: "bash",
    bash: "bash",
    zsh: "bash",
    json: "json",
    yaml: "yaml",
    yml: "yaml",
    toml: "toml",
    md: "markdown",
    mdx: "markdown",
    html: "html",
    css: "css",
    scss: "scss",
    sql: "sql",
    xml: "xml",
    dockerfile: "dockerfile",
  };
  return map[ext] ?? "text";
}

function formatSize(bytes: number | null): string {
  if (bytes === null) return "";
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface FilePreviewProps {
  entry: FileEntry | null;
  onClose?: () => void;
}

// ---------------------------------------------------------------------------
// FilePreview
// ---------------------------------------------------------------------------

export function FilePreview({ entry, onClose }: FilePreviewProps) {
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ingestStatus, setIngestStatus] = useState<
    "idle" | "loading" | "done" | "error"
  >("idle");

  useEffect(() => {
    if (!entry || entry.is_dir) {
      setContent(null);
      setError(null);
      return;
    }

    // Images are rendered via <img> — no need to fetch content
    if (entry.mime?.startsWith("image/")) {
      setContent(null);
      setError(null);
      return;
    }

    setLoading(true);
    setContent(null);
    setError(null);

    readFile(entry.path)
      .then((res) => {
        setContent(res.content);
        setLoading(false);
      })
      .catch((err: unknown) => {
        const msg =
          err instanceof Error ? err.message : "Failed to load file content";
        setError(msg);
        setLoading(false);
      });
  }, [entry]);

  async function handleIngest() {
    if (!entry) return;
    setIngestStatus("loading");
    try {
      await ingestPath(entry.path);
      setIngestStatus("done");
      setTimeout(() => setIngestStatus("idle"), 3000);
    } catch {
      setIngestStatus("error");
      setTimeout(() => setIngestStatus("idle"), 3000);
    }
  }

  // ----- Empty state -----
  if (!entry) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 text-muted-foreground">
        <FileText className="size-10 opacity-30" />
        <p className="text-sm">Select a file to preview</p>
      </div>
    );
  }

  const isImage = entry.mime?.startsWith("image/");
  const isMarkdown = entry.name.match(/\.(md|mdx)$/i);
  const lang = extensionLanguage(entry.name);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border px-4 py-2">
        <div className="flex min-w-0 items-center gap-2">
          {isImage ? (
            <FileImage className="size-4 shrink-0 text-muted-foreground" />
          ) : (
            <File className="size-4 shrink-0 text-muted-foreground" />
          )}
          <span className="truncate font-mono text-sm font-medium">
            {entry.name}
          </span>
          {entry.mime && (
            <Badge variant="secondary" className="shrink-0 text-[10px] py-0 px-1.5">
              {entry.mime}
            </Badge>
          )}
          {entry.size !== null && (
            <span className="shrink-0 text-xs text-muted-foreground">
              {formatSize(entry.size)}
            </span>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-1">
          {/* Ingest to RAG */}
          <Button
            variant="outline"
            size="sm"
            onClick={handleIngest}
            disabled={ingestStatus === "loading"}
            aria-label="Ingest to RAG"
          >
            {ingestStatus === "loading" ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Database className="size-3.5" />
            )}
            {ingestStatus === "done"
              ? "Ingested"
              : ingestStatus === "error"
                ? "Failed"
                : "Ingest to RAG"}
          </Button>

          {/* Download */}
          <a
            href={downloadFileUrl(entry.path)}
            download={entry.name}
            target="_blank"
            rel="noopener noreferrer"
            aria-label="Download file"
            className={cn(buttonVariants({ variant: "ghost", size: "icon-sm" }))}
          >
            <Download className="size-4" />
          </a>

          {/* Close */}
          {onClose && (
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={onClose}
              aria-label="Close preview"
            >
              <X className="size-4" />
            </Button>
          )}
        </div>
      </div>

      {/* Content area */}
      <div className="flex-1 overflow-auto">
        {loading && (
          <div className="flex h-full items-center justify-center gap-2 text-muted-foreground">
            <Loader2 className="size-5 animate-spin" />
            <span className="text-sm">Loading…</span>
          </div>
        )}

        {error && (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-destructive">
            <AlertCircle className="size-8 opacity-60" />
            <p className="text-sm">{error}</p>
            <a
              href={downloadFileUrl(entry.path)}
              download={entry.name}
              target="_blank"
              rel="noopener noreferrer"
              className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
            >
              <Download className="size-3.5" />
              Download instead
            </a>
          </div>
        )}

        {/* Image preview */}
        {!loading && !error && isImage && (
          <div className="flex items-center justify-center p-4">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={downloadFileUrl(entry.path)}
              alt={entry.name}
              className="max-h-[70vh] max-w-full rounded-lg object-contain"
            />
          </div>
        )}

        {/* Markdown preview */}
        {!loading && !error && content !== null && isMarkdown && (
          <div className="p-6">
            <MarkdownPreview>{content}</MarkdownPreview>
          </div>
        )}

        {/* Code / text preview */}
        {!loading && !error && content !== null && !isMarkdown && (
          <div className="h-full">
            <SyntaxHighlighter
              language={lang}
              style={vscDarkPlus}
              customStyle={{
                margin: 0,
                borderRadius: 0,
                background: "transparent",
                fontSize: "0.75rem",
                lineHeight: "1.5",
                height: "100%",
              }}
              showLineNumbers
              wrapLongLines={false}
            >
              {content}
            </SyntaxHighlighter>
          </div>
        )}
      </div>
    </div>
  );
}
