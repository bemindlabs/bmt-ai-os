"use client";

import React, { useState, useEffect } from "react";
import { searchKnowledge, type RagSource } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { FileText, RefreshCw, Search } from "lucide-react";
import { personaCollection } from "./helpers";

export interface SearchTabProps {
  activePersona: string | null;
}

export function SearchTab({ activePersona }: SearchTabProps) {
  const defaultCollection = personaCollection(activePersona);

  const [query, setQuery] = useState("");
  const [collection, setCollection] = useState(
    defaultCollection || "default",
  );
  const [topK, setTopK] = useState("5");
  const [loading, setLoading] = useState(false);
  const [answer, setAnswer] = useState<string | null>(null);
  const [sources, setSources] = useState<RagSource[]>([]);
  const [latency, setLatency] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [userEditedCollection, setUserEditedCollection] = useState(false);

  // Reset the user-edited flag whenever the active persona changes
  useEffect(() => {
    setUserEditedCollection(false);
  }, [activePersona]);

  // Update collection default when persona changes (only when unmodified by user)
  useEffect(() => {
    if (!userEditedCollection) {
      setCollection(personaCollection(activePersona) || "default");
    }
  }, [activePersona, userEditedCollection]);

  async function handleSearch() {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    setAnswer(null);
    setSources([]);
    setLatency(null);
    try {
      const res = await searchKnowledge({
        question: query.trim(),
        collection: collection.trim() || "default",
        top_k: Math.max(1, Math.min(50, Number(topK) || 5)),
      });
      setAnswer(res.answer);
      setSources(res.sources ?? []);
      setLatency(res.latency_ms);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") void handleSearch();
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Search Knowledge Base</CardTitle>
          <CardDescription>
            Ask a question; the RAG engine retrieves relevant chunks and
            generates an answer.
            {activePersona && (
              <span className="ml-1 text-primary">
                Searching the <span className="font-medium capitalize">{activePersona}</span> persona collection.
              </span>
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-[1fr_180px_80px]">
            <Input
              placeholder="Ask a question..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={loading}
            />
            <Input
              placeholder="Collection: default"
              value={collection}
              onChange={(e) => {
                setCollection(e.target.value);
                setUserEditedCollection(true);
              }}
              disabled={loading}
            />
            <Input
              type="number"
              min={1}
              max={50}
              placeholder="Top-K"
              value={topK}
              onChange={(e) => setTopK(e.target.value)}
              disabled={loading}
            />
          </div>
          <Button
            onClick={handleSearch}
            disabled={!query.trim() || loading}
          >
            {loading ? (
              <>
                <RefreshCw className="mr-2 size-4 animate-spin" />
                Searching...
              </>
            ) : (
              <>
                <Search className="mr-2 size-4" />
                Search
              </>
            )}
          </Button>

          {error && (
            <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {error}
            </p>
          )}
        </CardContent>
      </Card>

      {answer !== null && (
        <>
          <Card>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base">Answer</CardTitle>
                {latency !== null && (
                  <span className="text-xs text-muted-foreground">
                    {latency.toFixed(0)} ms
                  </span>
                )}
              </div>
            </CardHeader>
            <CardContent>
              <p className="whitespace-pre-wrap text-sm leading-relaxed">
                {answer}
              </p>
            </CardContent>
          </Card>

          {sources.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">
                  Sources ({sources.length})
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>File</TableHead>
                      <TableHead>Score</TableHead>
                      <TableHead>Chunk</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {sources.map((src, i) => (
                      <TableRow key={i}>
                        <TableCell className="font-mono text-xs">
                          <span className="flex items-center gap-1.5">
                            <FileText className="size-3 shrink-0 text-muted-foreground" />
                            {src.filename}
                          </span>
                        </TableCell>
                        <TableCell className="text-xs">
                          {src.score.toFixed(3)}
                        </TableCell>
                        <TableCell className="max-w-[400px] truncate text-xs text-muted-foreground">
                          {src.chunk}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
