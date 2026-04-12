"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ScrollText, Search, RefreshCw } from "lucide-react";
import { fetchLogs, type LogEntry } from "@/lib/api";

function statusVariant(
  status: number,
): "default" | "secondary" | "destructive" | "outline" {
  if (status >= 500) return "destructive";
  if (status >= 400) return "outline";
  return "secondary";
}

function statusClass(status: number): string {
  if (status >= 500) return "text-red-500";
  if (status >= 400) return "text-yellow-500";
  return "text-green-500";
}

function methodVariant(
  method: string,
): "default" | "secondary" | "outline" | "destructive" {
  switch (method) {
    case "GET":
      return "secondary";
    case "POST":
      return "default";
    case "PUT":
      return "outline";
    case "DELETE":
      return "destructive";
    default:
      return "outline";
  }
}

function latencyClass(ms: number): string {
  if (ms >= 1000) return "text-red-500";
  if (ms >= 300) return "text-yellow-500";
  return "text-muted-foreground";
}

export function LogViewer() {
  const [allLogs, setAllLogs] = useState<LogEntry[]>([]);
  const [visibleLogs, setVisibleLogs] = useState<LogEntry[]>([]);
  const [filter, setFilter] = useState("");
  const [cleared, setCleared] = useState<number>(0);
  const [paused, setPaused] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const autoScrollRef = useRef(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchLogs();
      setAllLogs(data.logs ?? []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch logs");
    } finally {
      setLoading(false);
    }
  }, []);

  // Poll every 5 s while not paused
  useEffect(() => {
    if (paused) return;
    load();
    const interval = setInterval(load, 5_000);
    return () => clearInterval(interval);
  }, [paused, load]);

  // Apply search filter and cleared watermark
  useEffect(() => {
    const term = filter.trim().toLowerCase();
    const filtered = allLogs.slice(cleared).filter((entry) => {
      if (!term) return true;
      return (
        entry.path.toLowerCase().includes(term) ||
        entry.method.toLowerCase().includes(term) ||
        String(entry.status).includes(term)
      );
    });
    setVisibleLogs(filtered);
  }, [allLogs, filter, cleared]);

  // Auto-scroll to bottom when new logs arrive (unless manually scrolled up)
  useEffect(() => {
    if (autoScrollRef.current && !paused) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [visibleLogs, paused]);

  function handleClear() {
    setCleared(allLogs.length);
  }

  function handleScroll(e: React.UIEvent<HTMLDivElement>) {
    const el = e.currentTarget;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    autoScrollRef.current = atBottom;
  }

  return (
    <Card className="flex flex-1 flex-col overflow-hidden">
      <CardHeader className="shrink-0 border-b">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-2">
            <ScrollText className="size-4 text-muted-foreground" />
            <div>
              <CardTitle>Request Log</CardTitle>
              <CardDescription>
                {visibleLogs.length} entr{visibleLogs.length !== 1 ? "ies" : "y"}
                {filter ? " matching filter" : " (last 200)"}
              </CardDescription>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            {/* Live indicator */}
            <span
              className={`size-2 rounded-full ${
                paused
                  ? "bg-yellow-500"
                  : loading
                    ? "bg-blue-500 animate-pulse"
                    : "bg-green-500 animate-pulse"
              }`}
              role="status"
              aria-label={paused ? "Log stream paused" : "Log stream live"}
            />

            <Button
              variant="outline"
              size="sm"
              onClick={load}
              disabled={loading}
              aria-label="Refresh logs"
            >
              <RefreshCw
                className={`size-3.5 ${loading ? "animate-spin" : ""}`}
              />
            </Button>

            <Button
              variant="outline"
              size="sm"
              onClick={() => setPaused((p) => !p)}
            >
              {paused ? "Resume" : "Pause"}
            </Button>

            <Button
              variant="ghost"
              size="sm"
              onClick={handleClear}
              disabled={visibleLogs.length === 0}
              title="Clear visible entries (visual only)"
            >
              Clear
            </Button>
          </div>
        </div>

        {/* Search / filter */}
        <div className="relative mt-2">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="pl-8"
            placeholder="Filter by path, method or status…"
            aria-label="Filter logs"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>
      </CardHeader>

      <CardContent
        className="flex-1 overflow-y-auto p-0"
        onScroll={handleScroll}
      >
        {error && (
          <p className="px-4 py-3 text-sm text-destructive">{error}</p>
        )}

        {visibleLogs.length === 0 && !error && (
          <p className="px-4 py-8 text-center text-sm text-muted-foreground">
            {filter
              ? "No entries match your filter."
              : "No log entries yet. Make some API requests to see them here."}
          </p>
        )}

        {visibleLogs.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-24">Time</TableHead>
                <TableHead className="w-16">Method</TableHead>
                <TableHead>Path</TableHead>
                <TableHead className="w-16 text-right">Status</TableHead>
                <TableHead className="w-20 text-right">Latency</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visibleLogs.map((entry, i) => (
                <TableRow
                  key={`${entry.timestamp}-${i}`}
                  className="font-mono text-xs"
                >
                  <TableCell className="text-muted-foreground">
                    {new Date(entry.timestamp * 1000).toLocaleTimeString()}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={methodVariant(entry.method)}
                      className="text-[10px] px-1.5 py-0"
                    >
                      {entry.method}
                    </Badge>
                  </TableCell>
                  <TableCell className="max-w-xs truncate text-foreground">
                    {entry.path}
                  </TableCell>
                  <TableCell
                    className={`text-right font-semibold ${statusClass(entry.status)}`}
                  >
                    {entry.status}
                  </TableCell>
                  <TableCell
                    className={`text-right ${latencyClass(entry.elapsed_ms)}`}
                  >
                    {entry.elapsed_ms}ms
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}

        <div ref={bottomRef} />
      </CardContent>
    </Card>
  );
}
