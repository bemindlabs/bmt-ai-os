"use client";

import React, { useState, useEffect, useCallback } from "react";
import { listFiles, readFile } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Network, RefreshCw } from "lucide-react";
import { VaultGraph, type GraphNode, type GraphEdge } from "./vault-graph";

// ---------------------------------------------------------------------------
// Helpers (Graph-tab-local)
// ---------------------------------------------------------------------------

/** Extract [[wiki-link]] targets from a markdown string. */
function extractWikiLinks(content: string): string[] {
  const results: string[] = [];
  const re = /\[\[([^\]]+)\]\]/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(content)) !== null) {
    results.push(m[1].trim());
  }
  return results;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface GraphTabProps {
  activePersona: string | null;
  workspacePath: string | null;
  /** Called when the user clicks a node — navigates to Notes tab and opens the note. */
  onOpenNote: (notePath: string) => void;
}

export function GraphTab({ activePersona, workspacePath, onOpenNote }: GraphTabProps) {
  const [graphNodes, setGraphNodes] = useState<GraphNode[]>([]);
  const [graphEdges, setGraphEdges] = useState<GraphEdge[]>([]);
  const [selectedNode, setSelectedNode] = useState<string | undefined>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** Derive the notes directory from active persona / workspace path. */
  function notesDir(): string {
    if (!activePersona) return "";
    if (workspacePath) {
      return `${workspacePath.replace(/\/$/, "")}/notes`;
    }
    return `workspace/agents/${activePersona}/notes`;
  }

  const loadGraph = useCallback(async () => {
    const dir = notesDir();
    if (!dir) {
      setGraphNodes([]);
      setGraphEdges([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      // 1. List all .md files
      const res = await listFiles(dir);
      const mdFiles = res.entries.filter(
        (e) => !e.is_dir && e.name.endsWith(".md"),
      );

      // 2. Read content for each file (for wiki-link extraction)
      const contentMap: Record<string, string> = {};
      await Promise.all(
        mdFiles.map(async (f) => {
          try {
            const r = await readFile(f.path);
            contentMap[f.path] = r.content;
          } catch {
            contentMap[f.path] = "";
          }
        }),
      );

      // 3. Build a name->path lookup (label = filename without .md)
      const nameToPath = new Map<string, string>();
      for (const f of mdFiles) {
        nameToPath.set(f.name.replace(/\.md$/, "").toLowerCase(), f.path);
      }

      // 4. Build nodes
      const nodes: GraphNode[] = mdFiles.map((f) => ({
        id: f.path,
        label: f.name.replace(/\.md$/, ""),
        x: 0,
        y: 0,
      }));

      // 5. Build edges from [[wiki-links]]
      const edgeSet = new Set<string>();
      const edges: GraphEdge[] = [];
      for (const f of mdFiles) {
        const content = contentMap[f.path] ?? "";
        const links = extractWikiLinks(content);
        for (const link of links) {
          const targetPath = nameToPath.get(link.toLowerCase());
          if (!targetPath || targetPath === f.path) continue;
          const key = [f.path, targetPath].sort().join("||");
          if (!edgeSet.has(key)) {
            edgeSet.add(key);
            edges.push({ source: f.path, target: targetPath });
          }
        }
      }

      setGraphNodes(nodes);
      setGraphEdges(edges);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not build graph",
      );
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activePersona, workspacePath]);

  useEffect(() => {
    void loadGraph();
  }, [loadGraph]);

  function handleNodeClick(nodeId: string) {
    setSelectedNode(nodeId);
    onOpenNote(nodeId);
  }

  if (!activePersona) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-3 text-muted-foreground">
        <Network className="size-10 opacity-30" />
        <p className="text-sm">Select a persona to view its knowledge graph.</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center gap-2 text-sm text-muted-foreground">
        <RefreshCw className="size-4 animate-spin" />
        Building graph…
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-3">
        <p className="rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </p>
        <Button variant="outline" size="sm" onClick={loadGraph}>
          <RefreshCw className="mr-2 size-4" />
          Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      {/* Toolbar */}
      <div className="flex shrink-0 items-center justify-between">
        <p className="text-xs text-muted-foreground">
          {graphNodes.length} note{graphNodes.length !== 1 ? "s" : ""},&nbsp;
          {graphEdges.length} link{graphEdges.length !== 1 ? "s" : ""}
          {selectedNode && (
            <span className="ml-2 text-foreground">
              &mdash; selected:{" "}
              <span className="font-medium">
                {graphNodes.find((n) => n.id === selectedNode)?.label ?? selectedNode}
              </span>
            </span>
          )}
        </p>
        <Button variant="outline" size="sm" onClick={loadGraph} aria-label="Refresh graph">
          <RefreshCw className="mr-1.5 size-3.5" />
          Refresh
        </Button>
      </div>

      {/* Graph canvas */}
      <div className="min-h-0 flex-1">
        <VaultGraph
          nodes={graphNodes}
          edges={graphEdges}
          onNodeClick={handleNodeClick}
          selectedNode={selectedNode}
        />
      </div>
    </div>
  );
}
