"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fetchProviderModels } from "@/lib/api";

interface ProviderModelsProps {
  providerName: string;
  isHealthy: boolean;
}

interface ModelEntry {
  id: string;
  name?: string;
  [key: string]: unknown;
}

export function ProviderModels({ providerName, isHealthy }: ProviderModelsProps) {
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [models, setModels] = useState<ModelEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleToggle() {
    const next = !expanded;
    setExpanded(next);

    if (next && models === null && !loading) {
      setLoading(true);
      setError(null);
      try {
        const res = await fetchProviderModels(providerName);
        setModels(res.models);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load models.");
        setModels([]);
      } finally {
        setLoading(false);
      }
    }
  }

  const label = expanded ? "Hide Models" : "Show Models";
  const Icon = expanded ? ChevronDown : ChevronRight;

  return (
    <div className="space-y-2 pt-1">
      <Button
        variant="ghost"
        size="sm"
        onClick={handleToggle}
        disabled={!isHealthy && models === null}
        className="gap-1 px-1 text-xs text-muted-foreground hover:text-foreground"
        aria-expanded={expanded}
      >
        <Icon className="size-3.5" aria-hidden="true" />
        {label}
      </Button>

      {expanded && (
        <div className="pl-1">
          {loading && (
            <p className="text-xs text-muted-foreground">Loading models…</p>
          )}

          {!loading && error && (
            <p className="text-xs text-destructive">{error}</p>
          )}

          {!loading && !error && models !== null && models.length === 0 && (
            <p className="text-xs text-muted-foreground">No models available.</p>
          )}

          {!loading && !error && models !== null && models.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {models.map((m, i) => (
                <Badge key={m.id ?? m.name ?? i} variant="outline" className="font-mono text-xs">
                  {m.name ?? m.id ?? `model-${i}`}
                </Badge>
              ))}
            </div>
          )}

          {!isHealthy && models === null && !loading && (
            <p className="text-xs text-muted-foreground">No models available.</p>
          )}
        </div>
      )}
    </div>
  );
}
