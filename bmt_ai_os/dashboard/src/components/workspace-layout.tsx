"use client";

import {
  useState,
  useRef,
  useCallback,
  useEffect,
  type ReactNode,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { cn } from "@/lib/utils";
import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from "lucide-react";
import { Button } from "@/components/ui/button";

// ─── Constants ────────────────────────────────────────────────────────────────

const STORAGE_KEY = "bmt_workspace_panel_sizes";

const LEFT_DEFAULT = 240;
const RIGHT_DEFAULT = 320;
const LEFT_MIN = 160;
const LEFT_MAX = 400;
const RIGHT_MIN = 200;
const RIGHT_MAX = 480;
const CENTER_MIN = 300;

// ─── Types ────────────────────────────────────────────────────────────────────

interface PanelSizes {
  leftWidth: number;
  rightWidth: number;
  leftCollapsed: boolean;
  rightCollapsed: boolean;
}

interface WorkspaceLayoutProps {
  leftPanel: ReactNode;
  centerPanel: ReactNode;
  rightPanel: ReactNode;
  className?: string;
}

// ─── Persistence helpers ──────────────────────────────────────────────────────

function loadSizes(): PanelSizes {
  if (typeof window === "undefined") {
    return {
      leftWidth: LEFT_DEFAULT,
      rightWidth: RIGHT_DEFAULT,
      leftCollapsed: false,
      rightCollapsed: false,
    };
  }
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<PanelSizes>;
      return {
        leftWidth: parsed.leftWidth ?? LEFT_DEFAULT,
        rightWidth: parsed.rightWidth ?? RIGHT_DEFAULT,
        leftCollapsed: parsed.leftCollapsed ?? false,
        rightCollapsed: parsed.rightCollapsed ?? false,
      };
    }
  } catch {
    // ignore
  }
  return {
    leftWidth: LEFT_DEFAULT,
    rightWidth: RIGHT_DEFAULT,
    leftCollapsed: false,
    rightCollapsed: false,
  };
}

function saveSizes(sizes: PanelSizes): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sizes));
  } catch {
    // ignore
  }
}

// ─── Resize handle ────────────────────────────────────────────────────────────

interface ResizeHandleProps {
  onDelta: (delta: number) => void;
  orientation?: "vertical";
  className?: string;
}

function ResizeHandle({ onDelta, className }: ResizeHandleProps) {
  const dragging = useRef(false);
  const lastX = useRef(0);

  const onPointerDown = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>) => {
      e.preventDefault();
      dragging.current = true;
      lastX.current = e.clientX;
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
    },
    []
  );

  const onPointerMove = useCallback(
    (e: ReactPointerEvent<HTMLDivElement>) => {
      if (!dragging.current) return;
      const delta = e.clientX - lastX.current;
      lastX.current = e.clientX;
      onDelta(delta);
    },
    [onDelta]
  );

  const onPointerUp = useCallback(() => {
    dragging.current = false;
  }, []);

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize panel"
      tabIndex={0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onKeyDown={(e) => {
        if (e.key === "ArrowLeft") onDelta(-8);
        if (e.key === "ArrowRight") onDelta(8);
      }}
      className={cn(
        "group relative z-10 flex w-1 shrink-0 cursor-col-resize select-none items-center justify-center",
        "bg-border/40 transition-colors hover:bg-border focus-visible:outline-none focus-visible:bg-primary/40",
        "active:bg-primary/60",
        className
      )}
    >
      {/* Visual grip dots */}
      <div className="flex flex-col gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
        {Array.from({ length: 3 }).map((_, i) => (
          <span key={i} className="size-1 rounded-full bg-muted-foreground/60" />
        ))}
      </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function WorkspaceLayout({
  leftPanel,
  centerPanel,
  rightPanel,
  className,
}: WorkspaceLayoutProps) {
  const [sizes, setSizes] = useState<PanelSizes>(loadSizes);
  const containerRef = useRef<HTMLDivElement>(null);

  // Persist on every change
  useEffect(() => {
    saveSizes(sizes);
  }, [sizes]);

  // Clamp a value between min and max
  const clamp = (val: number, min: number, max: number) =>
    Math.max(min, Math.min(max, val));

  // Available container width for dynamic clamping
  const containerWidth = () =>
    containerRef.current?.getBoundingClientRect().width ?? 1200;

  const handleLeftDelta = useCallback((delta: number) => {
    setSizes((prev) => {
      const totalWidth = containerWidth();
      const rightActual = prev.rightCollapsed ? 0 : prev.rightWidth;
      const maxLeft = totalWidth - rightActual - CENTER_MIN;
      const nextLeft = clamp(prev.leftWidth + delta, LEFT_MIN, Math.min(LEFT_MAX, maxLeft));
      return { ...prev, leftWidth: nextLeft };
    });
  }, []);

  const handleRightDelta = useCallback((delta: number) => {
    setSizes((prev) => {
      const totalWidth = containerWidth();
      const leftActual = prev.leftCollapsed ? 0 : prev.leftWidth;
      const maxRight = totalWidth - leftActual - CENTER_MIN;
      const nextRight = clamp(prev.rightWidth - delta, RIGHT_MIN, Math.min(RIGHT_MAX, maxRight));
      return { ...prev, rightWidth: nextRight };
    });
  }, []);

  const toggleLeft = useCallback(() => {
    setSizes((prev) => ({ ...prev, leftCollapsed: !prev.leftCollapsed }));
  }, []);

  const toggleRight = useCallback(() => {
    setSizes((prev) => ({ ...prev, rightCollapsed: !prev.rightCollapsed }));
  }, []);

  return (
    <div
      ref={containerRef}
      className={cn("flex h-full min-h-0 overflow-hidden", className)}
    >
      {/* ── Left panel ─────────────────────────────────────────────────────── */}
      <aside
        aria-label="Agent and session browser"
        style={{
          width: sizes.leftCollapsed ? 0 : sizes.leftWidth,
          minWidth: sizes.leftCollapsed ? 0 : LEFT_MIN,
        }}
        className={cn(
          "relative flex shrink-0 flex-col overflow-hidden border-r border-sidebar-border bg-sidebar transition-[width] duration-200",
          sizes.leftCollapsed && "border-r-0"
        )}
      >
        {/* Collapse toggle — floated on inner edge */}
        <div className="flex h-10 shrink-0 items-center justify-between px-3">
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground truncate">
            {!sizes.leftCollapsed && "Sessions"}
          </span>
          <Button
            variant="ghost"
            size="icon"
            className="size-7 shrink-0"
            onClick={toggleLeft}
            aria-label={sizes.leftCollapsed ? "Expand left panel" : "Collapse left panel"}
            title={sizes.leftCollapsed ? "Expand" : "Collapse"}
          >
            {sizes.leftCollapsed ? (
              <PanelLeftOpen className="size-4" />
            ) : (
              <PanelLeftClose className="size-4" />
            )}
          </Button>
        </div>

        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          {leftPanel}
        </div>
      </aside>

      {/* Left resize handle — hidden when collapsed */}
      {!sizes.leftCollapsed && (
        <ResizeHandle onDelta={handleLeftDelta} />
      )}

      {/* Expand button when left is collapsed */}
      {sizes.leftCollapsed && (
        <div className="flex shrink-0 flex-col items-center pt-2 border-r border-sidebar-border bg-sidebar">
          <Button
            variant="ghost"
            size="icon"
            className="size-7"
            onClick={toggleLeft}
            aria-label="Expand left panel"
            title="Expand sessions"
          >
            <PanelLeftOpen className="size-4" />
          </Button>
        </div>
      )}

      {/* ── Center panel ───────────────────────────────────────────────────── */}
      <main
        aria-label="Main work area"
        className="flex min-w-0 flex-1 flex-col overflow-hidden"
      >
        {centerPanel}
      </main>

      {/* Right resize handle — hidden when collapsed */}
      {!sizes.rightCollapsed && (
        <ResizeHandle onDelta={handleRightDelta} />
      )}

      {/* Expand button when right is collapsed */}
      {sizes.rightCollapsed && (
        <div className="flex shrink-0 flex-col items-center pt-2 border-l border-sidebar-border bg-sidebar">
          <Button
            variant="ghost"
            size="icon"
            className="size-7"
            onClick={toggleRight}
            aria-label="Expand right panel"
            title="Expand context panel"
          >
            <PanelRightOpen className="size-4" />
          </Button>
        </div>
      )}

      {/* ── Right panel ────────────────────────────────────────────────────── */}
      <aside
        aria-label="Context panel"
        style={{
          width: sizes.rightCollapsed ? 0 : sizes.rightWidth,
          minWidth: sizes.rightCollapsed ? 0 : RIGHT_MIN,
        }}
        className={cn(
          "relative flex shrink-0 flex-col overflow-hidden border-l border-sidebar-border bg-sidebar transition-[width] duration-200",
          sizes.rightCollapsed && "border-l-0"
        )}
      >
        <div className="flex h-10 shrink-0 items-center justify-between px-3">
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground truncate">
            {!sizes.rightCollapsed && "Context"}
          </span>
          <Button
            variant="ghost"
            size="icon"
            className="size-7 shrink-0"
            onClick={toggleRight}
            aria-label={sizes.rightCollapsed ? "Expand right panel" : "Collapse right panel"}
            title={sizes.rightCollapsed ? "Expand" : "Collapse"}
          >
            {sizes.rightCollapsed ? (
              <PanelRightOpen className="size-4" />
            ) : (
              <PanelRightClose className="size-4" />
            )}
          </Button>
        </div>

        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
          {rightPanel}
        </div>
      </aside>
    </div>
  );
}
