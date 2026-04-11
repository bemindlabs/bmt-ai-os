"use client";

import { useState, useEffect, useRef } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

interface LogEntry {
  timestamp: number;
  method: string;
  path: string;
  status: number;
  elapsed_ms: number;
  trace_id: string | null;
}

export function LogViewer() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [paused, setPaused] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (paused) return;

    async function fetchLogs() {
      try {
        const res = await fetch("/api/v1/logs");
        if (!res.ok) throw new Error(`${res.status}`);
        const data = await res.json();
        setLogs(data.logs ?? []);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to fetch logs");
      }
    }

    fetchLogs();
    const interval = setInterval(fetchLogs, 5000);
    return () => clearInterval(interval);
  }, [paused]);

  useEffect(() => {
    if (!paused) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs, paused]);

  function statusColor(status: number) {
    if (status < 300) return "text-green-500";
    if (status < 400) return "text-yellow-500";
    return "text-red-500";
  }

  function methodColor(method: string) {
    switch (method) {
      case "GET": return "default" as const;
      case "POST": return "secondary" as const;
      case "PUT": return "outline" as const;
      case "DELETE": return "destructive" as const;
      default: return "outline" as const;
    }
  }

  return (
    <Card className="flex flex-1 flex-col overflow-hidden">
      <CardHeader className="shrink-0">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Request Log</CardTitle>
            <CardDescription>
              {logs.length} entries (last 200)
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <span className={`size-2 rounded-full ${paused ? "bg-yellow-500" : "bg-green-500 animate-pulse"}`} />
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPaused(!paused)}
            >
              {paused ? "Resume" : "Pause"}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex-1 overflow-y-auto p-0">
        {error && (
          <p className="px-4 py-3 text-sm text-destructive">{error}</p>
        )}

        {logs.length === 0 && !error && (
          <p className="px-4 py-6 text-sm text-muted-foreground text-center">
            No log entries yet. Make some API requests to see them here.
          </p>
        )}

        <div className="divide-y divide-border">
          {logs.map((entry, i) => (
            <div
              key={`${entry.timestamp}-${i}`}
              className="flex items-center gap-3 px-4 py-1.5 text-xs font-mono hover:bg-muted/50"
            >
              <span className="shrink-0 text-muted-foreground w-20">
                {new Date(entry.timestamp * 1000).toLocaleTimeString()}
              </span>
              <Badge variant={methodColor(entry.method)} className="shrink-0 text-[10px] px-1.5 py-0">
                {entry.method}
              </Badge>
              <span className="flex-1 truncate text-foreground">
                {entry.path}
              </span>
              <span className={`shrink-0 w-8 text-right ${statusColor(entry.status)}`}>
                {entry.status}
              </span>
              <span className="shrink-0 w-16 text-right text-muted-foreground">
                {entry.elapsed_ms}ms
              </span>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      </CardContent>
    </Card>
  );
}
