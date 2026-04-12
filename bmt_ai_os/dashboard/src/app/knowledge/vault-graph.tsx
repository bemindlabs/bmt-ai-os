"use client";

import {
  useRef,
  useEffect,
  useState,
  useCallback,
  useMemo,
} from "react";
import { forceLayout } from "@/lib/graph-layout";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface GraphNode {
  id: string;      // file path
  label: string;   // file name without .md
  x: number;
  y: number;
  tags?: string[];
}

export interface GraphEdge {
  source: string;  // source node id (file path)
  target: string;  // target node id (file path)
}

export interface VaultGraphProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  onNodeClick: (nodeId: string) => void;
  selectedNode?: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const NODE_RADIUS = 8;
const SELECTED_RING_R = 12;
const CANVAS_W = 900;
const CANVAS_H = 650;

// ---------------------------------------------------------------------------
// VaultGraph
// ---------------------------------------------------------------------------

export function VaultGraph({
  nodes: rawNodes,
  edges,
  onNodeClick,
  selectedNode,
}: VaultGraphProps) {
  // We keep a local mutable copy for layout (run once per data change)
  const [layoutNodes, setLayoutNodes] = useState<GraphNode[]>([]);
  const [layoutReady, setLayoutReady] = useState(false);

  // Pan & zoom state
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [scale, setScale] = useState(1);

  // Dragging background for pan
  const dragging = useRef(false);
  const dragStart = useRef({ x: 0, y: 0, panX: 0, panY: 0 });

  // Tooltip (hover) state
  const [tooltip, setTooltip] = useState<{
    label: string;
    x: number;
    y: number;
  } | null>(null);

  const svgRef = useRef<SVGSVGElement>(null);

  // -------------------------------------------------------------------------
  // Run force layout whenever input data changes
  // -------------------------------------------------------------------------
  useEffect(() => {
    if (rawNodes.length === 0) {
      setLayoutNodes([]);
      setLayoutReady(true);
      return;
    }

    // Clone so we don't mutate props
    const working: GraphNode[] = rawNodes.map((n) => ({
      ...n,
      x: n.x ?? 0,
      y: n.y ?? 0,
    }));

    // Run layout synchronously (fast enough for 100+ nodes)
    forceLayout(working, edges, 150, CANVAS_W, CANVAS_H);

    setLayoutNodes(working);
    setLayoutReady(true);
    // Reset pan/zoom when data changes
    setPan({ x: 0, y: 0 });
    setScale(1);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rawNodes.length, edges.length]);

  // -------------------------------------------------------------------------
  // Build quick lookup: id -> node
  // -------------------------------------------------------------------------
  const nodeMap = useMemo<Map<string, GraphNode>>(
    () => new Map(layoutNodes.map((n) => [n.id, n])),
    [layoutNodes],
  );

  // -------------------------------------------------------------------------
  // Wheel zoom
  // -------------------------------------------------------------------------
  const handleWheel = useCallback((e: React.WheelEvent<SVGSVGElement>) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.1 : 0.9;
    setScale((s) => Math.min(4, Math.max(0.2, s * factor)));
  }, []);

  // -------------------------------------------------------------------------
  // Pan with mouse drag on SVG background
  // -------------------------------------------------------------------------
  const handleMouseDown = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      // Only start pan on SVG background (not on nodes)
      if ((e.target as SVGElement).closest("[data-node]")) return;
      dragging.current = true;
      dragStart.current = {
        x: e.clientX,
        y: e.clientY,
        panX: pan.x,
        panY: pan.y,
      };
    },
    [pan],
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      if (!dragging.current) return;
      setPan({
        x: dragStart.current.panX + (e.clientX - dragStart.current.x),
        y: dragStart.current.panY + (e.clientY - dragStart.current.y),
      });
    },
    [],
  );

  const handleMouseUp = useCallback(() => {
    dragging.current = false;
  }, []);

  // -------------------------------------------------------------------------
  // Node hover tooltip
  // -------------------------------------------------------------------------
  function handleNodeMouseEnter(node: GraphNode, e: React.MouseEvent) {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    setTooltip({
      label: node.id, // full path as tooltip
      x: e.clientX - rect.left + 12,
      y: e.clientY - rect.top - 8,
    });
  }

  function handleNodeMouseLeave() {
    setTooltip(null);
  }

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------
  if (!layoutReady) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Computing layout…
      </div>
    );
  }

  if (layoutNodes.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-muted-foreground">
        <svg
          viewBox="0 0 24 24"
          className="size-12 opacity-25"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.5}
          aria-hidden
        >
          <circle cx="12" cy="12" r="3" />
          <circle cx="4" cy="6" r="2" />
          <circle cx="20" cy="6" r="2" />
          <circle cx="4" cy="18" r="2" />
          <line x1="6" y1="6" x2="9" y2="11" />
          <line x1="18" y1="6" x2="15" y2="11" />
          <line x1="6" y1="18" x2="9" y2="13" />
        </svg>
        <p className="text-sm">No notes found in the active persona vault.</p>
        <p className="text-xs opacity-60">
          Select a persona with a workspace path to browse its notes.
        </p>
      </div>
    );
  }

  const transform = `translate(${pan.x}px, ${pan.y}px) scale(${scale})`;

  return (
    <div className="relative h-full w-full overflow-hidden rounded-lg border border-border bg-background">
      {/* Zoom hint */}
      <p className="pointer-events-none absolute right-3 top-3 z-10 select-none text-xs text-muted-foreground opacity-60">
        Scroll to zoom · Drag to pan
      </p>

      <svg
        ref={svgRef}
        viewBox={`0 0 ${CANVAS_W} ${CANVAS_H}`}
        className="h-full w-full cursor-grab active:cursor-grabbing"
        style={{ touchAction: "none" }}
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        aria-label="Vault knowledge graph"
        role="img"
      >
        <g style={{ transform, transformOrigin: "50% 50%", transition: "none" }}>
          {/* Edges */}
          <g aria-hidden="true">
            {edges.map((edge, i) => {
              const src = nodeMap.get(edge.source);
              const tgt = nodeMap.get(edge.target);
              if (!src || !tgt) return null;
              return (
                <line
                  key={i}
                  x1={src.x}
                  y1={src.y}
                  x2={tgt.x}
                  y2={tgt.y}
                  stroke="currentColor"
                  strokeOpacity={0.18}
                  strokeWidth={1}
                />
              );
            })}
          </g>

          {/* Nodes */}
          {layoutNodes.map((node) => {
            const isSelected = node.id === selectedNode;
            return (
              <g
                key={node.id}
                data-node="true"
                transform={`translate(${node.x},${node.y})`}
                style={{ cursor: "pointer" }}
                onClick={() => onNodeClick(node.id)}
                onMouseEnter={(e) => handleNodeMouseEnter(node, e)}
                onMouseLeave={handleNodeMouseLeave}
                role="button"
                tabIndex={0}
                aria-label={`Open note: ${node.label}`}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onNodeClick(node.id);
                  }
                }}
              >
                {/* Selection ring */}
                {isSelected && (
                  <circle
                    r={SELECTED_RING_R}
                    fill="none"
                    stroke="hsl(var(--primary))"
                    strokeWidth={2}
                    opacity={0.9}
                  />
                )}

                {/* Node circle */}
                <circle
                  r={NODE_RADIUS}
                  fill={
                    isSelected
                      ? "hsl(var(--primary))"
                      : "hsl(var(--muted-foreground))"
                  }
                  fillOpacity={isSelected ? 1 : 0.6}
                  stroke={
                    isSelected
                      ? "hsl(var(--primary))"
                      : "hsl(var(--border))"
                  }
                  strokeWidth={1}
                />

                {/* Label */}
                <text
                  y={NODE_RADIUS + 12}
                  textAnchor="middle"
                  fontSize="10"
                  fill="currentColor"
                  fillOpacity={0.75}
                  style={{ pointerEvents: "none", userSelect: "none" }}
                >
                  {node.label.length > 18
                    ? node.label.slice(0, 16) + "…"
                    : node.label}
                </text>
              </g>
            );
          })}
        </g>
      </svg>

      {/* Tooltip */}
      {tooltip && (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute z-20 max-w-[260px] truncate rounded-md border border-border bg-popover px-2 py-1 text-xs text-popover-foreground shadow-md"
          style={{ left: tooltip.x, top: tooltip.y }}
        >
          {tooltip.label}
        </div>
      )}
    </div>
  );
}
