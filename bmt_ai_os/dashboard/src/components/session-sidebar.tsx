"use client";

import { useState } from "react";
import { PlusCircle, Trash2, MessageSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import type { Session } from "@/lib/sessions";

interface SessionSidebarProps {
  sessions: Session[];
  activeSessionId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}

export function SessionSidebar({
  sessions,
  activeSessionId,
  onSelect,
  onNew,
  onDelete,
}: SessionSidebarProps) {
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  function handleDeleteClick(e: React.MouseEvent, id: string) {
    e.stopPropagation();
    setPendingDelete(id);
  }

  function handleConfirmDelete(e: React.MouseEvent, id: string) {
    e.stopPropagation();
    onDelete(id);
    setPendingDelete(null);
  }

  function handleCancelDelete(e: React.MouseEvent) {
    e.stopPropagation();
    setPendingDelete(null);
  }

  return (
    <aside
      className="flex w-52 shrink-0 flex-col border-r border-border bg-sidebar"
      aria-label="Chat sessions"
    >
      {/* Header */}
      <div className="flex h-12 items-center justify-between px-3">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Sessions
        </span>
        <Button
          variant="ghost"
          size="icon"
          className="size-7"
          onClick={onNew}
          aria-label="New session"
          title="New session"
        >
          <PlusCircle className="size-4" />
        </Button>
      </div>

      <Separator />

      {/* Session list */}
      <nav className="flex flex-1 flex-col gap-0.5 overflow-y-auto px-1.5 py-2">
        {sessions.length === 0 && (
          <p className="px-2 py-3 text-xs text-muted-foreground">
            No saved sessions yet.
          </p>
        )}

        {sessions.map((session) => {
          const isActive = session.id === activeSessionId;
          const isConfirming = session.id === pendingDelete;

          return (
            <div
              key={session.id}
              role="button"
              tabIndex={0}
              aria-current={isActive ? "true" : undefined}
              onClick={() => !isConfirming && onSelect(session.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  if (!isConfirming) onSelect(session.id);
                }
              }}
              className={cn(
                "group relative flex cursor-pointer items-start gap-2 rounded-md px-2 py-2 text-sm transition-colors",
                isActive
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground",
              )}
            >
              <MessageSquare className="mt-0.5 size-3.5 shrink-0 opacity-60" />

              <span className="flex-1 truncate leading-snug">
                {session.title}
              </span>

              {/* Delete controls */}
              {!isConfirming ? (
                <button
                  type="button"
                  aria-label={`Delete session: ${session.title}`}
                  onClick={(e) => handleDeleteClick(e, session.id)}
                  className="ml-auto shrink-0 rounded p-0.5 opacity-0 transition-opacity hover:text-destructive group-hover:opacity-60 focus:opacity-100 focus:outline-none"
                  tabIndex={-1}
                >
                  <Trash2 className="size-3" />
                </button>
              ) : (
                <div
                  className="ml-auto flex shrink-0 items-center gap-1"
                  onClick={(e) => e.stopPropagation()}
                >
                  <button
                    type="button"
                    aria-label="Confirm delete"
                    onClick={(e) => handleConfirmDelete(e, session.id)}
                    className="rounded px-1 py-0.5 text-[10px] font-medium text-destructive hover:bg-destructive/10 focus:outline-none"
                  >
                    Delete
                  </button>
                  <button
                    type="button"
                    aria-label="Cancel delete"
                    onClick={handleCancelDelete}
                    className="rounded px-1 py-0.5 text-[10px] font-medium text-muted-foreground hover:bg-muted focus:outline-none"
                  >
                    Cancel
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </nav>
    </aside>
  );
}
