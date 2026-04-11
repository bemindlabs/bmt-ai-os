"use client";

import { useState } from "react";
import {
  BookOpen,
  Brain,
  FileText,
  ChevronDown,
  ChevronRight,
  ExternalLink,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface RagSource {
  id: string;
  title: string;
  excerpt: string;
  score: number;
  url?: string;
}

export interface MemoryEntry {
  id: string;
  content: string;
  timestamp: number;
}

interface ContextPanelProps {
  ragSources?: RagSource[];
  memories?: MemoryEntry[];
  className?: string;
}

// ─── Section wrapper ──────────────────────────────────────────────────────────

interface SectionProps {
  title: string;
  count?: number;
  icon: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
}

function Section({ title, count, icon, defaultOpen = true, children }: SectionProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div>
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:bg-muted/40"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span className="text-muted-foreground">{icon}</span>
        <span className="flex-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          {title}
        </span>
        {count !== undefined && (
          <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
            {count}
          </Badge>
        )}
        {open ? (
          <ChevronDown className="size-3.5 text-muted-foreground/60" />
        ) : (
          <ChevronRight className="size-3.5 text-muted-foreground/60" />
        )}
      </button>

      {open && (
        <div className="pb-2">
          {children}
        </div>
      )}
    </div>
  );
}

// ─── RAG source card ──────────────────────────────────────────────────────────

function RagSourceCard({ source }: { source: RagSource }) {
  const scorePercent = Math.round(source.score * 100);
  const scoreColor =
    scorePercent >= 80
      ? "text-emerald-500"
      : scorePercent >= 60
        ? "text-amber-500"
        : "text-muted-foreground";

  return (
    <div className="mx-2 mb-1.5 rounded-md border border-border/50 bg-card p-2.5 text-xs">
      <div className="flex items-start justify-between gap-2 mb-1">
        <span className="font-medium text-foreground leading-snug line-clamp-1">
          {source.title}
        </span>
        <span className={cn("tabular-nums shrink-0 font-medium", scoreColor)}>
          {scorePercent}%
        </span>
      </div>

      <p className="text-muted-foreground leading-relaxed line-clamp-2">
        {source.excerpt}
      </p>

      {source.url && (
        <a
          href={source.url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-1.5 flex items-center gap-1 text-[10px] text-primary hover:underline"
        >
          <ExternalLink className="size-3" />
          Open source
        </a>
      )}
    </div>
  );
}

// ─── Memory entry ─────────────────────────────────────────────────────────────

function MemoryCard({ entry }: { entry: MemoryEntry }) {
  const date = new Date(entry.timestamp);
  const timeStr = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const dateStr = date.toLocaleDateString([], { month: "short", day: "numeric" });

  return (
    <div className="mx-2 mb-1.5 rounded-md border border-border/50 bg-card p-2.5 text-xs">
      <p className="text-muted-foreground leading-relaxed line-clamp-3">
        {entry.content}
      </p>
      <span className="mt-1 block text-[10px] text-muted-foreground/60">
        {dateStr} {timeStr}
      </span>
    </div>
  );
}

// ─── Empty placeholder ────────────────────────────────────────────────────────

function EmptyNote({ text }: { text: string }) {
  return (
    <p className="px-3 py-2 text-xs text-muted-foreground/60 italic">{text}</p>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function ContextPanel({
  ragSources = [],
  memories = [],
  className,
}: ContextPanelProps) {
  return (
    <div className={cn("flex flex-col overflow-y-auto", className)}>
      <Section
        title="RAG Sources"
        icon={<BookOpen className="size-3.5" />}
        count={ragSources.length}
        defaultOpen={true}
      >
        {ragSources.length === 0 ? (
          <EmptyNote text="No sources retrieved yet. Sources appear here when the RAG pipeline is active." />
        ) : (
          ragSources.map((s) => <RagSourceCard key={s.id} source={s} />)
        )}
      </Section>

      <Separator />

      <Section
        title="Memory"
        icon={<Brain className="size-3.5" />}
        count={memories.length}
        defaultOpen={true}
      >
        {memories.length === 0 ? (
          <EmptyNote text="No memory entries for this session." />
        ) : (
          memories.map((m) => <MemoryCard key={m.id} entry={m} />)
        )}
      </Section>

      <Separator />

      <Section
        title="Documents"
        icon={<FileText className="size-3.5" />}
        defaultOpen={false}
      >
        <EmptyNote text="Drag and drop files here to ingest them into the RAG pipeline." />
      </Section>
    </div>
  );
}
