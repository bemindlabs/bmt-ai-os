"use client";

import { useState } from "react";
import {
  Folder,
  FileText,
  ChevronUp,
  Plus,
  FolderPlus,
  Pencil,
  Trash2,
  MoreHorizontal,
} from "lucide-react";
import type { FileEntry } from "@/lib/api";
import { createDirectory, renameFile, deleteFile, writeFile } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface FileTreeProps {
  entries: FileEntry[];
  currentPath: string | null;
  onSelect: (entry: FileEntry) => void;
  onNavigate: (path: string) => void;
  onRefresh: () => void;
  rootPath: string;
}

export function FileTree({
  entries,
  currentPath,
  onSelect,
  onNavigate,
  onRefresh,
  rootPath,
}: FileTreeProps) {
  const parentPath = rootPath.includes("/")
    ? rootPath.substring(0, rootPath.lastIndexOf("/")) || ""
    : null;

  const [creating, setCreating] = useState<"file" | "folder" | null>(null);
  const [newName, setNewName] = useState("");
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameName, setRenameName] = useState("");
  const [contextEntry, setContextEntry] = useState<string | null>(null);

  async function handleCreate() {
    if (!newName.trim()) return;
    const path = rootPath ? `${rootPath}/${newName.trim()}` : newName.trim();
    try {
      if (creating === "folder") {
        await createDirectory(path);
      } else {
        await writeFile(path, "");
      }
      onRefresh();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Create failed");
    }
    setCreating(null);
    setNewName("");
  }

  async function handleRename(entry: FileEntry) {
    if (!renameName.trim() || renameName.trim() === entry.name) {
      setRenaming(null);
      return;
    }
    const dir = entry.path.substring(0, entry.path.lastIndexOf("/"));
    const newPath = dir ? `${dir}/${renameName.trim()}` : renameName.trim();
    try {
      await renameFile(entry.path, newPath);
      onRefresh();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Rename failed");
    }
    setRenaming(null);
  }

  async function handleDelete(entry: FileEntry) {
    const kind = entry.is_dir ? "directory" : "file";
    if (!confirm(`Delete ${kind} "${entry.name}"?`)) return;
    try {
      await deleteFile(entry.path);
      onRefresh();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Delete failed");
    }
  }

  return (
    <div className="flex h-full flex-col overflow-y-auto text-xs">
      {/* Header with actions */}
      <div className="sticky top-0 flex items-center justify-between border-b border-border bg-muted/50 px-3 py-2">
        <span className="block truncate font-mono font-medium text-muted-foreground" title={rootPath || "/"}>
          {rootPath.split("/").pop() || "/"}
        </span>
        <div className="flex items-center gap-0.5">
          <button
            onClick={() => { setCreating("file"); setNewName(""); }}
            className="rounded p-1 text-muted-foreground hover:bg-sidebar-accent hover:text-foreground"
            title="New File"
          >
            <Plus className="size-3" />
          </button>
          <button
            onClick={() => { setCreating("folder"); setNewName(""); }}
            className="rounded p-1 text-muted-foreground hover:bg-sidebar-accent hover:text-foreground"
            title="New Folder"
          >
            <FolderPlus className="size-3" />
          </button>
        </div>
      </div>

      <div className="flex flex-col gap-px p-1">
        {/* Parent directory */}
        {parentPath !== null && (
          <button
            onClick={() => onNavigate(parentPath)}
            className="flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-sidebar-foreground/80 transition-colors hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
          >
            <ChevronUp className="size-3 shrink-0 text-muted-foreground" />
            <span className="font-mono">..</span>
          </button>
        )}

        {/* Create new item inline */}
        {creating && (
          <form
            onSubmit={(e) => { e.preventDefault(); void handleCreate(); }}
            className="flex items-center gap-1 px-1 py-0.5"
          >
            {creating === "folder" ? (
              <Folder className="size-3 shrink-0 text-blue-400" />
            ) : (
              <FileText className="size-3 shrink-0 text-muted-foreground" />
            )}
            <Input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              className="h-5 flex-1 px-1 text-xs font-mono"
              placeholder={creating === "folder" ? "folder name" : "file name"}
              autoFocus
              onBlur={() => { if (!newName.trim()) setCreating(null); }}
              onKeyDown={(e) => { if (e.key === "Escape") setCreating(null); }}
            />
          </form>
        )}

        {/* File entries */}
        {entries.map((entry) => {
          const isActive = !entry.is_dir && entry.path === currentPath;
          const Icon = entry.is_dir ? Folder : FileText;
          const isRenaming = renaming === entry.path;
          const showContext = contextEntry === entry.path;

          if (isRenaming) {
            return (
              <form
                key={entry.path}
                onSubmit={(e) => { e.preventDefault(); void handleRename(entry); }}
                className="flex items-center gap-1 px-1 py-0.5"
              >
                <Icon className={`size-3 shrink-0 ${entry.is_dir ? "text-blue-400" : "text-muted-foreground"}`} />
                <Input
                  value={renameName}
                  onChange={(e) => setRenameName(e.target.value)}
                  className="h-5 flex-1 px-1 text-xs font-mono"
                  autoFocus
                  onBlur={() => void handleRename(entry)}
                  onKeyDown={(e) => { if (e.key === "Escape") setRenaming(null); }}
                />
              </form>
            );
          }

          return (
            <div key={entry.path} className="group relative flex items-center">
              <button
                onClick={() => (entry.is_dir ? onNavigate(entry.path) : onSelect(entry))}
                title={entry.path}
                className={[
                  "flex w-full items-center gap-1.5 rounded px-2 py-1 text-left transition-colors",
                  isActive
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "text-sidebar-foreground/80 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground",
                ].join(" ")}
                aria-current={isActive ? "page" : undefined}
              >
                <Icon className={`size-3 shrink-0 ${entry.is_dir ? "text-blue-400" : "text-muted-foreground"}`} />
                <span className="truncate font-mono">{entry.name}</span>
                {entry.size != null && entry.size > 0 && !entry.is_dir && (
                  <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">
                    {entry.size < 1024
                      ? `${entry.size}B`
                      : `${(entry.size / 1024).toFixed(0)}K`}
                  </span>
                )}
              </button>

              {/* Context menu trigger */}
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setContextEntry(showContext ? null : entry.path);
                }}
                className="absolute right-1 top-1/2 -translate-y-1/2 rounded p-0.5 opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-foreground"
              >
                <MoreHorizontal className="size-3" />
              </button>

              {/* Context actions */}
              {showContext && (
                <div className="absolute right-0 top-full z-10 mt-0.5 rounded border border-border bg-popover p-1 shadow-md">
                  <button
                    onClick={() => {
                      setRenaming(entry.path);
                      setRenameName(entry.name);
                      setContextEntry(null);
                    }}
                    className="flex w-full items-center gap-1.5 rounded px-2 py-1 text-xs hover:bg-accent"
                  >
                    <Pencil className="size-3" />
                    Rename
                  </button>
                  <button
                    onClick={() => {
                      setContextEntry(null);
                      void handleDelete(entry);
                    }}
                    className="flex w-full items-center gap-1.5 rounded px-2 py-1 text-xs text-destructive hover:bg-accent"
                  >
                    <Trash2 className="size-3" />
                    Delete
                  </button>
                </div>
              )}
            </div>
          );
        })}

        {entries.length === 0 && !creating && (
          <p className="px-2 py-2 italic text-muted-foreground">
            Empty directory
          </p>
        )}
      </div>
    </div>
  );
}
