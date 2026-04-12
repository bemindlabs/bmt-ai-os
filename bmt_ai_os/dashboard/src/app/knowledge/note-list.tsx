"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { FilePlus, FileText } from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface NoteItem {
  /** Filename without .md extension */
  name: string;
  /** Full file path */
  path: string;
  /** Tags parsed from frontmatter */
  tags: string[];
}

interface NoteListProps {
  notes: NoteItem[];
  activePath: string | null;
  onSelect: (note: NoteItem) => void;
  onNewNote: () => void;
  loading?: boolean;
}

// ---------------------------------------------------------------------------
// Tag dot colors — deterministic from tag string
// ---------------------------------------------------------------------------

const DOT_COLORS = [
  "bg-blue-400",
  "bg-emerald-400",
  "bg-violet-400",
  "bg-amber-400",
  "bg-rose-400",
  "bg-cyan-400",
  "bg-orange-400",
  "bg-pink-400",
];

function tagColor(tag: string): string {
  let hash = 0;
  for (let i = 0; i < tag.length; i++) {
    hash = (hash * 31 + tag.charCodeAt(i)) & 0xffff;
  }
  return DOT_COLORS[hash % DOT_COLORS.length];
}

// ---------------------------------------------------------------------------
// NoteList component
// ---------------------------------------------------------------------------

export function NoteList({
  notes,
  activePath,
  onSelect,
  onNewNote,
  loading = false,
}: NoteListProps) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between px-2 py-2">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
          Notes
        </span>
        <Button
          size="icon-xs"
          variant="ghost"
          onClick={onNewNote}
          aria-label="New note"
          title="New note"
        >
          <FilePlus className="size-3.5" />
        </Button>
      </div>

      {/* List */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading ? (
          <div className="px-2 py-4 text-center text-xs text-muted-foreground">
            Loading...
          </div>
        ) : notes.length === 0 ? (
          <div className="flex flex-col items-center gap-2 px-2 py-8 text-center text-xs text-muted-foreground">
            <FileText className="size-6 opacity-40" />
            <p>No notes yet.</p>
            <Button size="xs" variant="outline" onClick={onNewNote}>
              <FilePlus className="mr-1 size-3" />
              New note
            </Button>
          </div>
        ) : (
          <ul className="space-y-px px-1">
            {notes.map((note) => (
              <li key={note.path}>
                <button
                  type="button"
                  className={cn(
                    "group flex w-full items-start gap-1.5 rounded-md px-2 py-1.5 text-left text-sm",
                    "transition-colors hover:bg-muted/70 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
                    activePath === note.path
                      ? "bg-muted font-medium text-foreground"
                      : "text-foreground/80",
                  )}
                  onClick={() => onSelect(note)}
                  aria-current={activePath === note.path ? "page" : undefined}
                >
                  <FileText className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{note.name}</span>
                    {note.tags.length > 0 && (
                      <span className="mt-0.5 flex flex-wrap gap-0.5">
                        {note.tags.slice(0, 4).map((tag) => (
                          <span
                            key={tag}
                            className={cn(
                              "inline-block size-2 rounded-full",
                              tagColor(tag),
                            )}
                            title={tag}
                            aria-label={`Tag: ${tag}`}
                          />
                        ))}
                        {note.tags.length > 4 && (
                          <Badge
                            variant="outline"
                            className="h-3 px-1 text-[10px]"
                          >
                            +{note.tags.length - 4}
                          </Badge>
                        )}
                      </span>
                    )}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
