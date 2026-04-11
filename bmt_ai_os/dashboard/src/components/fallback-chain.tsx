"use client";

import { useState, useRef } from "react";
import { GripVertical, ArrowDown } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { setFallbackOrder } from "@/lib/api";
import type { Provider } from "@/lib/api";

interface FallbackChainProps {
  providers: Provider[];
}

export function FallbackChain({ providers }: FallbackChainProps) {
  const [items, setItems] = useState<Provider[]>([...providers]);
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<"idle" | "success" | "error">("idle");

  const dragIndex = useRef<number | null>(null);
  const dragOverIndex = useRef<number | null>(null);

  function handleDragStart(index: number) {
    dragIndex.current = index;
  }

  function handleDragEnter(index: number) {
    dragOverIndex.current = index;
    if (dragIndex.current === null || dragIndex.current === index) return;

    setItems((prev) => {
      const next = [...prev];
      const [moved] = next.splice(dragIndex.current!, 1);
      next.splice(index, 0, moved);
      dragIndex.current = index;
      return next;
    });
  }

  function handleDragEnd() {
    dragIndex.current = null;
    dragOverIndex.current = null;
  }

  function handleDragOver(e: React.DragEvent) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }

  async function handleSave() {
    setSaving(true);
    setSaveStatus("idle");
    try {
      await setFallbackOrder(items.map((p) => p.name));
      setSaveStatus("success");
    } catch {
      setSaveStatus("error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold">Fallback Chain</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Drag to reorder priority. The first healthy provider is used.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {saveStatus === "success" && (
            <span className="text-xs text-muted-foreground">Saved.</span>
          )}
          {saveStatus === "error" && (
            <span className="text-xs text-destructive">Failed to save.</span>
          )}
          <Button size="sm" onClick={handleSave} disabled={saving}>
            {saving ? "Saving…" : "Save Order"}
          </Button>
        </div>
      </div>

      <ol className="space-y-1">
        {items.map((provider, index) => (
          <li key={provider.name}>
            <div
              draggable
              onDragStart={() => handleDragStart(index)}
              onDragEnter={() => handleDragEnter(index)}
              onDragEnd={handleDragEnd}
              onDragOver={handleDragOver}
              className="flex items-center gap-3 rounded-lg border border-border bg-card px-3 py-2 cursor-grab active:cursor-grabbing select-none"
            >
              <GripVertical
                className="size-4 shrink-0 text-muted-foreground"
                aria-hidden="true"
              />
              <span className="text-xs font-mono text-muted-foreground w-4 shrink-0">
                {index + 1}
              </span>
              <span className="flex-1 text-sm font-medium capitalize">
                {provider.name}
              </span>
              <Badge variant={provider.healthy ? "default" : "destructive"}>
                {provider.healthy ? "healthy" : "offline"}
              </Badge>
            </div>

            {index < items.length - 1 && (
              <div className="flex justify-center py-0.5" aria-hidden="true">
                <ArrowDown className="size-3 text-muted-foreground/50" />
              </div>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
