"use client";

import { useState, useEffect } from "react";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";

const STORAGE_KEY = "bmt-feature-flags";

const FLAGS = [
  {
    id: "rag",
    label: "RAG Pipeline",
    description: "Enable retrieval-augmented generation via ChromaDB.",
    defaultOn: false,
  },
  {
    id: "training",
    label: "On-Device Training",
    description: "Allow LoRA/QLoRA fine-tuning jobs to be triggered.",
    defaultOn: false,
  },
  {
    id: "streaming",
    label: "Streaming Responses",
    description: "Stream chat completions token-by-token (experimental).",
    defaultOn: false,
  },
  {
    id: "metrics_polling",
    label: "Auto-Refresh Metrics",
    description: "Poll /api/v1/metrics every 30 seconds on the Overview page.",
    defaultOn: false,
  },
];

function loadFlags(): Record<string, boolean> {
  if (typeof window === "undefined") {
    return Object.fromEntries(FLAGS.map((f) => [f.id, f.defaultOn]));
  }
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);
      return Object.fromEntries(
        FLAGS.map((f) => [f.id, parsed[f.id] ?? f.defaultOn]),
      );
    }
  } catch {
    // ignore corrupt storage
  }
  return Object.fromEntries(FLAGS.map((f) => [f.id, f.defaultOn]));
}

export function FeatureFlags() {
  const [flags, setFlags] = useState<Record<string, boolean>>(() => loadFlags());
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setFlags(loadFlags());
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (hydrated) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(flags));
    }
  }, [flags, hydrated]);

  function toggle(id: string) {
    setFlags((prev) => ({ ...prev, [id]: !prev[id] }));
  }

  return (
    <div className="space-y-1">
      {FLAGS.map((flag, i) => (
        <div key={flag.id}>
          {i > 0 && <Separator className="my-2" />}
          <div className="flex items-start justify-between gap-4 py-1">
            <div className="space-y-0.5">
              <p className="text-sm font-medium">{flag.label}</p>
              <p className="text-xs text-muted-foreground">
                {flag.description}
              </p>
            </div>
            <Switch
              checked={flags[flag.id]}
              onCheckedChange={() => toggle(flag.id)}
              aria-label={`Toggle ${flag.label}`}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
