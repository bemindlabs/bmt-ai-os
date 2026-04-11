"use client";

import { useState, useEffect, useCallback } from "react";
import {
  fetchCollections,
  ingestDocuments,
  searchKnowledge,
  deleteCollection,
  type RagCollection,
  type RagSource,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Database,
  FolderOpen,
  Search,
  Trash2,
  RefreshCw,
  FileText,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Collections tab
// ---------------------------------------------------------------------------

function CollectionsTab() {
  const [collections, setCollections] = useState<RagCollection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingName, setDeletingName] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchCollections();
      setCollections(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load collections");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleDelete(name: string) {
    if (!confirm(`Delete collection "${name}"? This cannot be undone.`)) return;
    setDeletingName(name);
    try {
      await deleteCollection(name);
      setCollections((prev) => prev.filter((c) => c.name !== name));
    } catch (err) {
      alert(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setDeletingName(null);
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <div>
          <CardTitle>Collections</CardTitle>
          <CardDescription>
            {error
              ? "Could not reach the RAG API."
              : loading
                ? "Loading..."
                : `${collections.length} collection${collections.length !== 1 ? "s" : ""}`}
          </CardDescription>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading} aria-label="Refresh collections">
          <RefreshCw className={cn("size-4", loading && "animate-spin")} />
          <span className="ml-2">Refresh</span>
        </Button>
      </CardHeader>

      <CardContent className="p-0">
        {!loading && collections.length === 0 ? (
          <div className="flex flex-col items-center gap-4 py-16 text-muted-foreground">
            <Database className="size-12 opacity-30" />
            <p className="text-sm">
              {error
                ? "RAG API is unreachable. Check controller logs."
                : "No collections yet. Ingest documents to create one."}
            </p>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Documents</TableHead>
                <TableHead className="w-[80px]" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {collections.map((col) => (
                <TableRow key={col.name}>
                  <TableCell className="font-medium">{col.name}</TableCell>
                  <TableCell>
                    <Badge variant="secondary">{col.count}</Badge>
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`Delete collection ${col.name}`}
                      disabled={deletingName === col.name}
                      onClick={() => handleDelete(col.name)}
                      className="text-destructive hover:text-destructive"
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Ingest tab
// ---------------------------------------------------------------------------

type IngestState = "idle" | "loading" | "success" | "error";

function IngestTab() {
  const [folderPath, setFolderPath] = useState("");
  const [collection, setCollection] = useState("default");
  const [state, setState] = useState<IngestState>("idle");
  const [message, setMessage] = useState<string | null>(null);

  async function handleIngest() {
    if (!folderPath.trim()) return;
    setState("loading");
    setMessage(null);
    try {
      const res = await ingestDocuments({
        path: folderPath.trim(),
        collection: collection.trim() || "default",
        recursive: true,
      });
      setState("success");
      setMessage(
        `Accepted: "${res.path}" into collection "${res.collection}". Ingestion runs in the background.`,
      );
    } catch (err) {
      setState("error");
      setMessage(err instanceof Error ? err.message : "Ingest request failed");
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Ingest Documents</CardTitle>
        <CardDescription>
          Provide an absolute folder path on the device. The controller will
          chunk and embed all files recursively.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="ingest-path">
              Folder path
            </label>
            <Input
              id="ingest-path"
              placeholder="/data/documents"
              value={folderPath}
              onChange={(e) => setFolderPath(e.target.value)}
              disabled={state === "loading"}
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium" htmlFor="ingest-collection">
              Collection name
            </label>
            <Input
              id="ingest-collection"
              placeholder="default"
              value={collection}
              onChange={(e) => setCollection(e.target.value)}
              disabled={state === "loading"}
            />
          </div>
        </div>

        <Button
          onClick={handleIngest}
          disabled={!folderPath.trim() || state === "loading"}
        >
          {state === "loading" ? (
            <>
              <RefreshCw className="mr-2 size-4 animate-spin" />
              Submitting...
            </>
          ) : (
            <>
              <FolderOpen className="mr-2 size-4" />
              Ingest
            </>
          )}
        </Button>

        {message && (
          <p
            className={cn(
              "rounded-md border px-3 py-2 text-sm",
              state === "success"
                ? "border-green-500/30 bg-green-500/10 text-green-700 dark:text-green-400"
                : "border-destructive/30 bg-destructive/10 text-destructive",
            )}
          >
            {message}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Search tab
// ---------------------------------------------------------------------------

function SearchTab() {
  const [query, setQuery] = useState("");
  const [collection, setCollection] = useState("default");
  const [topK, setTopK] = useState("5");
  const [loading, setLoading] = useState(false);
  const [answer, setAnswer] = useState<string | null>(null);
  const [sources, setSources] = useState<RagSource[]>([]);
  const [latency, setLatency] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

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
              onChange={(e) => setCollection(e.target.value)}
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

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function KnowledgePage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Knowledge Base</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Manage RAG collections, ingest documents, and search the vector store.
        </p>
      </div>

      <Tabs defaultValue="collections">
        <TabsList>
          <TabsTrigger value="collections">
            <Database className="mr-1.5 size-4" />
            Collections
          </TabsTrigger>
          <TabsTrigger value="ingest">
            <FolderOpen className="mr-1.5 size-4" />
            Ingest
          </TabsTrigger>
          <TabsTrigger value="search">
            <Search className="mr-1.5 size-4" />
            Search
          </TabsTrigger>
        </TabsList>

        <TabsContent value="collections" className="mt-4">
          <CollectionsTab />
        </TabsContent>

        <TabsContent value="ingest" className="mt-4">
          <IngestTab />
        </TabsContent>

        <TabsContent value="search" className="mt-4">
          <SearchTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
