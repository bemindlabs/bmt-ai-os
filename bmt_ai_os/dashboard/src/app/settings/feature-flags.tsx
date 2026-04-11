"use client";

import { useState } from "react";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";

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

export function FeatureFlags() {
  const [flags, setFlags] = useState<Record<string, boolean>>(
    Object.fromEntries(FLAGS.map((f) => [f.id, f.defaultOn]))
  );

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
