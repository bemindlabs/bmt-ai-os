"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, FileText } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { type RagSource } from "@/lib/api";

interface SourceCardProps {
  source: RagSource;
  index: number;
}

export function SourceCard({ source, index }: SourceCardProps) {
  const [expanded, setExpanded] = useState(false);

  const scorePercent = Math.round(source.score * 100);
  const scoreVariant =
    source.score >= 0.8
      ? "default"
      : source.score >= 0.5
        ? "secondary"
        : "outline";

  return (
    <button
      type="button"
      onClick={() => setExpanded((prev) => !prev)}
      aria-expanded={expanded}
      className="w-full text-left rounded-lg border border-border bg-muted/40 px-3 py-2 text-xs transition-colors hover:bg-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
    >
      <div className="flex items-center gap-2">
        <FileText className="size-3 shrink-0 text-muted-foreground" aria-hidden="true" />
        <span className="flex-1 truncate font-medium text-foreground">
          {index + 1}. {source.filename}
        </span>
        <Badge variant={scoreVariant} aria-label={`Relevance ${scorePercent}%`}>
          {scorePercent}%
        </Badge>
        {expanded ? (
          <ChevronUp className="size-3 shrink-0 text-muted-foreground" aria-hidden="true" />
        ) : (
          <ChevronDown className="size-3 shrink-0 text-muted-foreground" aria-hidden="true" />
        )}
      </div>

      {expanded && (
        <p className="mt-2 whitespace-pre-wrap text-muted-foreground leading-relaxed border-t border-border pt-2">
          {source.chunk}
        </p>
      )}
    </button>
  );
}

interface SourceListProps {
  sources: RagSource[];
}

export function SourceList({ sources }: SourceListProps) {
  if (sources.length === 0) return null;

  return (
    <div className="mt-2 flex flex-col gap-1.5">
      <p className="text-xs font-medium text-muted-foreground">Sources</p>
      {sources.map((source, i) => (
        <SourceCard key={`${source.filename}-${source.position}`} source={source} index={i} />
      ))}
    </div>
  );
}
