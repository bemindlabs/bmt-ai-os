"use client";

import { useState, useCallback, useRef } from "react";
import {
  ChevronRight,
  RefreshCw,
  Upload,
  Loader2,
  AlertCircle,
  Home,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { FileTree } from "@/components/file-tree";
import { FilePreview } from "@/components/file-preview";
import {
  listFiles,
  uploadFile,
  type FileEntry,
  type Breadcrumb,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Upload drop zone (self-contained within this page)
// ---------------------------------------------------------------------------

function UploadZone({
  currentPath,
  onUploaded,
}: {
  currentPath: string;
  onUploaded: () => void;
}) {
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const dragCounter = useRef(0);

  async function handleFiles(files: FileList | File[]) {
    const arr = Array.from(files);
    if (arr.length === 0) return;
    setUploading(true);
    setError(null);
    try {
      await Promise.all(arr.map((f) => uploadFile(currentPath, f)));
      onUploaded();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  function handleDragEnter(e: React.DragEvent) {
    e.preventDefault();
    dragCounter.current += 1;
    if (dragCounter.current === 1) setIsDragging(true);
  }

  function handleDragLeave(e: React.DragEvent) {
    e.preventDefault();
    dragCounter.current -= 1;
    if (dragCounter.current === 0) setIsDragging(false);
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    dragCounter.current = 0;
    setIsDragging(false);
    handleFiles(e.dataTransfer.files);
  }

  return (
    <div
      className={cn(
        "relative flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-4 transition-colors",
        isDragging
          ? "border-primary bg-primary/10"
          : "border-border hover:border-primary/50 hover:bg-muted/30",
      )}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={(e) => e.preventDefault()}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
      role="button"
      tabIndex={0}
      aria-label="Upload files — click or drag and drop"
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          inputRef.current?.click();
        }
      }}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        className="sr-only"
        onChange={(e) => e.target.files && handleFiles(e.target.files)}
        aria-hidden="true"
      />

      {uploading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          Uploading…
        </div>
      ) : (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Upload className="size-4" />
          <span>Drop files here or click to upload</span>
        </div>
      )}

      {error && (
        <p className="mt-1 flex items-center gap-1 text-xs text-destructive">
          <AlertCircle className="size-3" />
          {error}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// FileManagerClient
// ---------------------------------------------------------------------------

export function FileManagerClient() {
  // Current browsed directory
  const [currentPath, setCurrentPath] = useState("");
  const [rootEntries, setRootEntries] = useState<FileEntry[]>([]);
  const [breadcrumbs, setBreadcrumbs] = useState<Breadcrumb[]>([
    { name: "Files", path: "" },
  ]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Tree expansion state
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set());
  const [childrenCache, setChildrenCache] = useState<
    Record<string, FileEntry[]>
  >({});

  // Selected file for preview
  const [selectedEntry, setSelectedEntry] = useState<FileEntry | null>(null);

  // ---------------------------------------------------------------------------
  // Load root directory
  // ---------------------------------------------------------------------------
  const loadRoot = useCallback(async (path = "") => {
    setLoading(true);
    setError(null);
    try {
      const data = await listFiles(path);
      setRootEntries(data.entries);
      setBreadcrumbs(data.breadcrumbs);
      setCurrentPath(path);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load files");
    } finally {
      setLoading(false);
    }
  }, []);

  // Load root on first render
  const [initialised, setInitialised] = useState(false);
  if (!initialised) {
    setInitialised(true);
    loadRoot("");
  }

  // ---------------------------------------------------------------------------
  // Load children for tree expansion
  // ---------------------------------------------------------------------------
  const loadChildren = useCallback(async (path: string) => {
    try {
      const data = await listFiles(path);
      setChildrenCache((prev) => ({ ...prev, [path]: data.entries }));
    } catch {
      setChildrenCache((prev) => ({ ...prev, [path]: [] }));
    }
  }, []);

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------
  function handleToggleDir(path: string) {
    setExpandedDirs((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  }

  function handleNavigate(path: string) {
    loadRoot(path);
  }

  function handleBreadcrumb(path: string) {
    loadRoot(path);
    // Collapse everything deeper than this path
    setExpandedDirs((prev) => {
      const next = new Set<string>();
      for (const p of prev) {
        if (p === path || path === "" || p.startsWith(path + "/")) {
          next.add(p);
        }
      }
      return next;
    });
    setSelectedEntry(null);
  }

  return (
    <div className="flex flex-1 gap-4 overflow-hidden">
      {/* Left panel — tree + upload */}
      <Card className="flex w-64 shrink-0 flex-col overflow-hidden gap-0 py-0">
        {/* Breadcrumb header */}
        <div className="flex shrink-0 items-center gap-1 overflow-x-auto border-b border-border px-3 py-2">
          {breadcrumbs.map((crumb, i) => (
            <span key={crumb.path} className="flex items-center gap-1">
              {i > 0 && (
                <ChevronRight className="size-3 shrink-0 text-muted-foreground" />
              )}
              <button
                type="button"
                onClick={() => handleBreadcrumb(crumb.path)}
                className={cn(
                  "max-w-[80px] truncate rounded px-1 py-0.5 text-xs transition-colors hover:bg-muted",
                  i === breadcrumbs.length - 1
                    ? "font-medium text-foreground"
                    : "text-muted-foreground",
                )}
                aria-current={i === breadcrumbs.length - 1 ? "page" : undefined}
              >
                {i === 0 ? <Home className="inline size-3" /> : crumb.name}
              </button>
            </span>
          ))}

          <Button
            variant="ghost"
            size="icon-xs"
            className="ml-auto shrink-0"
            onClick={() => loadRoot(currentPath)}
            aria-label="Refresh"
            disabled={loading}
          >
            <RefreshCw
              className={cn("size-3", loading && "animate-spin")}
            />
          </Button>
        </div>

        {/* Tree */}
        <div className="flex-1 overflow-y-auto">
          {error ? (
            <div className="flex flex-col items-center gap-2 p-4 text-center text-sm text-destructive">
              <AlertCircle className="size-5 opacity-60" />
              <p>{error}</p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => loadRoot(currentPath)}
              >
                Retry
              </Button>
            </div>
          ) : (
            <FileTree
              entries={rootEntries}
              currentPath={currentPath}
              selectedPath={selectedEntry?.path ?? null}
              onNavigate={handleNavigate}
              onSelect={setSelectedEntry}
              expandedDirs={expandedDirs}
              onToggleDir={handleToggleDir}
              childrenCache={childrenCache}
              loadChildren={loadChildren}
            />
          )}
        </div>

        <Separator />

        {/* Upload zone */}
        <div className="shrink-0 p-2">
          <UploadZone
            currentPath={currentPath}
            onUploaded={() => {
              loadRoot(currentPath);
              // Refresh cached children for current dir
              if (currentPath) {
                loadChildren(currentPath).then(() => {
                  setChildrenCache((prev) => ({ ...prev }));
                });
              }
            }}
          />
        </div>
      </Card>

      {/* Right panel — preview */}
      <Card className="flex flex-1 overflow-hidden gap-0 py-0">
        <FilePreview
          entry={selectedEntry}
          onClose={() => setSelectedEntry(null)}
        />
      </Card>
    </div>
  );
}
