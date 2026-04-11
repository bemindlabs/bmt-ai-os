"use client";

import { useState, useCallback } from "react";
import {
  Folder,
  FolderOpen,
  File,
  FileText,
  FileCode,
  FileImage,
  ChevronRight,
  ChevronDown,
  Download,
  Database,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { type FileEntry, downloadFileUrl, ingestPath } from "@/lib/api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fileIcon(entry: FileEntry) {
  if (entry.is_dir) return null; // handled separately
  const mime = entry.mime ?? "";
  if (mime.startsWith("image/")) return FileImage;
  if (
    mime.startsWith("text/") ||
    mime.includes("json") ||
    mime.includes("xml")
  )
    return FileText;
  if (
    mime.includes("javascript") ||
    mime.includes("typescript") ||
    entry.name.match(/\.(py|ts|tsx|js|jsx|sh|go|rs|c|cpp|h|java|rb|php)$/)
  )
    return FileCode;
  return File;
}

function formatSize(bytes: number | null): string {
  if (bytes === null) return "";
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface FileTreeProps {
  entries: FileEntry[];
  currentPath: string;
  selectedPath: string | null;
  onNavigate: (path: string) => void;
  onSelect: (entry: FileEntry) => void;
  expandedDirs: Set<string>;
  onToggleDir: (path: string) => void;
  childrenCache: Record<string, FileEntry[]>;
  loadChildren: (path: string) => Promise<void>;
}

// ---------------------------------------------------------------------------
// Single tree node
// ---------------------------------------------------------------------------

function TreeNode({
  entry,
  depth,
  selectedPath,
  onNavigate,
  onSelect,
  expandedDirs,
  onToggleDir,
  childrenCache,
  loadChildren,
}: {
  entry: FileEntry;
  depth: number;
  selectedPath: string | null;
  onNavigate: (path: string) => void;
  onSelect: (entry: FileEntry) => void;
  expandedDirs: Set<string>;
  onToggleDir: (path: string) => void;
  childrenCache: Record<string, FileEntry[]>;
  loadChildren: (path: string) => Promise<void>;
}) {
  const isExpanded = expandedDirs.has(entry.path);
  const isSelected = selectedPath === entry.path;
  const children = childrenCache[entry.path];

  const Icon = entry.is_dir
    ? isExpanded
      ? FolderOpen
      : Folder
    : (fileIcon(entry) ?? File);

  async function handleClick() {
    if (entry.is_dir) {
      if (!isExpanded && !children) {
        await loadChildren(entry.path);
      }
      onToggleDir(entry.path);
      onNavigate(entry.path);
    } else {
      onSelect(entry);
    }
  }

  function handleDownload(e: React.MouseEvent) {
    e.stopPropagation();
    window.open(downloadFileUrl(entry.path), "_blank");
  }

  async function handleIngest(e: React.MouseEvent) {
    e.stopPropagation();
    try {
      await ingestPath(entry.path);
    } catch {
      // Silent — the parent page can handle toast notifications
    }
  }

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        aria-selected={isSelected}
        aria-expanded={entry.is_dir ? isExpanded : undefined}
        onClick={handleClick}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            handleClick();
          }
        }}
        className={cn(
          "group flex items-center gap-1.5 rounded-md px-2 py-1 text-sm cursor-pointer select-none",
          "hover:bg-muted/60 transition-colors",
          isSelected && "bg-muted text-foreground",
          !isSelected && "text-foreground/80",
        )}
        style={{ paddingLeft: `${(depth + 1) * 12}px` }}
      >
        {/* Expand chevron for directories */}
        {entry.is_dir ? (
          <span className="size-4 shrink-0 text-muted-foreground">
            {isExpanded ? (
              <ChevronDown className="size-3.5" />
            ) : (
              <ChevronRight className="size-3.5" />
            )}
          </span>
        ) : (
          <span className="size-4 shrink-0" />
        )}

        <Icon
          className={cn(
            "size-4 shrink-0",
            entry.is_dir ? "text-yellow-500" : "text-muted-foreground",
          )}
        />

        <span className="flex-1 truncate font-mono text-xs">{entry.name}</span>

        {/* Size (files only) */}
        {!entry.is_dir && entry.size !== null && (
          <span className="hidden shrink-0 text-[10px] text-muted-foreground group-hover:inline">
            {formatSize(entry.size)}
          </span>
        )}

        {/* Action buttons — appear on hover */}
        <span className="hidden items-center gap-0.5 group-hover:flex">
          {!entry.is_dir && (
            <Button
              variant="ghost"
              size="icon-xs"
              onClick={handleDownload}
              aria-label={`Download ${entry.name}`}
              title="Download"
            >
              <Download className="size-3" />
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon-xs"
            onClick={handleIngest}
            aria-label={`Ingest ${entry.name} to RAG`}
            title="Ingest to RAG"
          >
            <Database className="size-3" />
          </Button>
        </span>
      </div>

      {/* Children */}
      {entry.is_dir && isExpanded && children && (
        <div role="group">
          {children.length === 0 ? (
            <p
              className="py-1 text-[11px] text-muted-foreground/60"
              style={{ paddingLeft: `${(depth + 2) * 12 + 20}px` }}
            >
              Empty
            </p>
          ) : (
            children.map((child) => (
              <TreeNode
                key={child.path}
                entry={child}
                depth={depth + 1}
                selectedPath={selectedPath}
                onNavigate={onNavigate}
                onSelect={onSelect}
                expandedDirs={expandedDirs}
                onToggleDir={onToggleDir}
                childrenCache={childrenCache}
                loadChildren={loadChildren}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// FileTree — top-level component
// ---------------------------------------------------------------------------

export function FileTree({
  entries,
  currentPath,
  selectedPath,
  onNavigate,
  onSelect,
  expandedDirs,
  onToggleDir,
  childrenCache,
  loadChildren,
}: FileTreeProps) {
  return (
    <nav
      aria-label="File tree"
      className="flex flex-col gap-0.5 overflow-y-auto py-2"
    >
      {entries.length === 0 ? (
        <p className="px-4 py-6 text-center text-sm text-muted-foreground">
          No files yet. Upload files to get started.
        </p>
      ) : (
        entries.map((entry) => (
          <TreeNode
            key={entry.path}
            entry={entry}
            depth={0}
            selectedPath={selectedPath}
            onNavigate={onNavigate}
            onSelect={onSelect}
            expandedDirs={expandedDirs}
            onToggleDir={onToggleDir}
            childrenCache={childrenCache}
            loadChildren={loadChildren}
          />
        ))
      )}
    </nav>
  );
}
