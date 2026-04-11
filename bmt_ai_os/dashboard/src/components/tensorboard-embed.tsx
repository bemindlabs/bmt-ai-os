"use client";

import { useState, useEffect } from "react";

interface TensorBoardEmbedProps {
  /** TensorBoard host URL, e.g. "http://localhost:6006" */
  url?: string;
  className?: string;
}

const DEFAULT_URL = "http://localhost:6006";

export function TensorBoardEmbed({
  url = DEFAULT_URL,
  className,
}: TensorBoardEmbedProps) {
  const [available, setAvailable] = useState<boolean | null>(null);

  // Probe availability with a HEAD/no-cors fetch — we can only detect
  // complete failures (network error), not 200 vs 4xx in no-cors mode.
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    fetch(url, { method: "HEAD", mode: "no-cors", signal: controller.signal })
      .then(() => {
        if (!cancelled) setAvailable(true);
      })
      .catch(() => {
        if (!cancelled) setAvailable(false);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [url]);

  if (available === null) {
    return (
      <div
        className={`flex items-center justify-center rounded-lg border border-border bg-muted/30 text-xs text-muted-foreground ${className ?? ""}`}
        style={{ minHeight: 240 }}
      >
        Checking TensorBoard availability…
      </div>
    );
  }

  if (!available) {
    return (
      <div
        className={`flex flex-col items-center justify-center gap-2 rounded-lg border border-border bg-muted/30 text-xs text-muted-foreground ${className ?? ""}`}
        style={{ minHeight: 240 }}
      >
        <span className="font-medium">TensorBoard not reachable</span>
        <span className="opacity-70">
          Start TensorBoard on{" "}
          <code className="font-mono">{url}</code> to view training graphs.
        </span>
      </div>
    );
  }

  return (
    <iframe
      src={url}
      title="TensorBoard"
      className={`w-full rounded-lg border border-border bg-background ${className ?? ""}`}
      style={{ minHeight: 480 }}
      sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
      loading="lazy"
    />
  );
}
