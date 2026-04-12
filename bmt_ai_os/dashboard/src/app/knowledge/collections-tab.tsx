"use client";

import React, { useState, useEffect, useCallback } from "react";
import { fetchCollections, deleteCollection, type RagCollection } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Database, RefreshCw, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { personaCollection } from "./helpers";

export interface CollectionsTabProps {
  activePersona: string | null;
}

export function CollectionsTab({ activePersona }: CollectionsTabProps) {
  const [collections, setCollections] = useState<RagCollection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingName, setDeletingName] = useState<string | null>(null);

  const personaCol = personaCollection(activePersona);

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
              {collections.map((col) => {
                const isPersonaCol =
                  personaCol !== "" && col.name === personaCol;
                return (
                  <TableRow key={col.name}>
                    <TableCell className="font-medium">
                      <span className="flex items-center gap-2">
                        {col.name}
                        {isPersonaCol && (
                          <Badge variant="default" className="capitalize text-[10px]">
                            {activePersona}
                          </Badge>
                        )}
                      </span>
                    </TableCell>
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
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
