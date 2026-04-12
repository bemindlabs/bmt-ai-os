"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import { X, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTerminal } from "@/hooks/use-terminal";
import { ConnectionStatus } from "@/components/terminal/connection-status";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/**
 * Build the WebSocket URL for the terminal.
 * In the browser, we derive it from the current page URL so it works
 * regardless of Docker internal hostnames (NEXT_PUBLIC_API_URL may be
 * "http://controller:8080" which isn't resolvable from the browser).
 * Falls back to localhost:8080 during SSR.
 */
function getTerminalWsUrl(): string {
  if (typeof window === "undefined") return "ws://localhost:8080/ws/terminal";
  const loc = window.location;
  const proto = loc.protocol === "https:" ? "wss:" : "ws:";
  // Dashboard runs on port 9090, controller on 8080 — same host, different port
  const host = loc.hostname;
  return `${proto}//${host}:8080/ws/terminal`;
}

const HEIGHT_STORAGE_KEY = "bmt_editor_terminal_height";
const DEFAULT_HEIGHT = 200;
const MIN_HEIGHT = 80;
// Max height is computed at drag-time as 60% of the container height.

const MAX_RECONNECT_ATTEMPTS = 3;
// Backoff delays in ms: attempt 1 → 1 s, 2 → 2 s, 3 → 4 s
const BACKOFF_MS = [1000, 2000, 4000];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function loadStoredHeight(): number {
  if (typeof window === "undefined") return DEFAULT_HEIGHT;
  const raw = localStorage.getItem(HEIGHT_STORAGE_KEY);
  const parsed = raw ? parseInt(raw, 10) : NaN;
  return Number.isFinite(parsed) && parsed >= MIN_HEIGHT ? parsed : DEFAULT_HEIGHT;
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface EditorTerminalProps {
  visible: boolean;
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function EditorTerminal({ visible, onClose }: EditorTerminalProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  // Track whether we have ever connected (to gate reconnect logic)
  const hasConnectedRef = useRef(false);
  // Reconnect attempt counter
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { connect, disconnect, status, dispose } = useTerminal({
    containerRef,
    wsUrl: getTerminalWsUrl(),
  });

  // ------------------------------------------------------------------
  // Panel height — persisted in localStorage (BMTOS-146)
  // ------------------------------------------------------------------
  const [panelHeight, setPanelHeight] = useState<number>(DEFAULT_HEIGHT);

  // Load persisted height on mount (must be in effect so SSR is safe)
  useEffect(() => {
    setPanelHeight(loadStoredHeight());
  }, []);

  // Persist height changes
  useEffect(() => {
    if (typeof window !== "undefined") {
      localStorage.setItem(HEIGHT_STORAGE_KEY, String(panelHeight));
    }
  }, [panelHeight]);

  // ------------------------------------------------------------------
  // Auto-connect on first visibility (BMTOS-145)
  // ------------------------------------------------------------------
  useEffect(() => {
    if (visible && !hasConnectedRef.current) {
      hasConnectedRef.current = true;
      reconnectAttemptsRef.current = 0;
      void connect();
    }
  }, [visible, connect]);

  // ------------------------------------------------------------------
  // Exponential backoff reconnect (BMTOS-145)
  // ------------------------------------------------------------------
  useEffect(() => {
    // Only trigger after we have connected at least once and the panel is visible
    if (!hasConnectedRef.current || !visible) return;

    if (status === "disconnected" || status === "error") {
      const attempt = reconnectAttemptsRef.current;
      if (attempt >= MAX_RECONNECT_ATTEMPTS) return;

      const delay = BACKOFF_MS[attempt] ?? BACKOFF_MS[BACKOFF_MS.length - 1];
      reconnectTimerRef.current = setTimeout(() => {
        reconnectAttemptsRef.current = attempt + 1;
        void connect();
      }, delay);
    } else if (status === "connected") {
      // Reset counter on successful connection
      reconnectAttemptsRef.current = 0;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    }

    return () => {
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };
  }, [status, visible, connect]);

  // Cancel pending reconnect when panel is hidden
  useEffect(() => {
    if (!visible && reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, [visible]);

  // Dispose xterm on unmount
  useEffect(() => {
    return () => {
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      dispose();
    };
  }, [dispose]);

  // Manual reconnect (resets backoff)
  const handleReconnect = useCallback(() => {
    reconnectAttemptsRef.current = 0;
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    disconnect();
    setTimeout(() => void connect(), 100);
  }, [disconnect, connect]);

  // ------------------------------------------------------------------
  // Drag-to-resize handle (BMTOS-146)
  // ------------------------------------------------------------------
  const dragStateRef = useRef<{
    startY: number;
    startHeight: number;
    maxHeight: number;
  } | null>(null);

  const onDragMove = useCallback((e: MouseEvent) => {
    const drag = dragStateRef.current;
    if (!drag) return;
    // Moving the pointer up increases the panel height
    const delta = drag.startY - e.clientY;
    const clamped = Math.max(MIN_HEIGHT, Math.min(drag.maxHeight, drag.startHeight + delta));
    setPanelHeight(clamped);
  }, []);

  const onDragEnd = useCallback(() => {
    dragStateRef.current = null;
    document.removeEventListener("mousemove", onDragMove);
    document.removeEventListener("mouseup", onDragEnd);
    document.body.style.userSelect = "";
    document.body.style.cursor = "";
  }, [onDragMove]);

  const onDragStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      const container = panelRef.current?.parentElement;
      const maxHeight = container
        ? Math.floor(container.getBoundingClientRect().height * 0.6)
        : window.innerHeight * 0.6;

      dragStateRef.current = {
        startY: e.clientY,
        startHeight: panelHeight,
        maxHeight,
      };

      document.addEventListener("mousemove", onDragMove);
      document.addEventListener("mouseup", onDragEnd);
      document.body.style.userSelect = "none";
      document.body.style.cursor = "row-resize";
    },
    [panelHeight, onDragMove, onDragEnd],
  );

  // Double-click: toggle terminal open/closed (BMTOS-146)
  const onHandleDoubleClick = useCallback(() => {
    onClose();
  }, [onClose]);

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------

  // Keep element mounted but hidden so xterm state is preserved
  return (
    <div
      ref={panelRef}
      className="flex flex-col border-t border-border bg-zinc-950"
      style={{ height: panelHeight, display: visible ? "flex" : "none" }}
      aria-hidden={!visible}
    >
      {/* Drag handle (BMTOS-146) */}
      <div
        role="separator"
        aria-orientation="horizontal"
        aria-label="Resize terminal panel — drag to resize, double-click to close"
        tabIndex={0}
        className="group relative z-10 flex h-1.5 w-full shrink-0 cursor-row-resize items-center justify-center bg-transparent hover:bg-primary/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        onMouseDown={onDragStart}
        onDoubleClick={onHandleDoubleClick}
        onKeyDown={(e) => {
          // Arrow keys nudge height for keyboard accessibility
          if (e.key === "ArrowUp") {
            e.preventDefault();
            setPanelHeight((h) => Math.min(h + 20, window.innerHeight * 0.6));
          } else if (e.key === "ArrowDown") {
            e.preventDefault();
            setPanelHeight((h) => Math.max(h - 20, MIN_HEIGHT));
          } else if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onClose();
          }
        }}
      >
        {/* Visual grip line */}
        <div className="h-px w-12 rounded-full bg-border transition-colors group-hover:bg-primary/50" />
      </div>

      {/* Toolbar */}
      <div className="flex shrink-0 items-center border-b border-border bg-muted/10 px-3 py-1">
        <span className="text-xs font-medium text-muted-foreground">Terminal</span>
        <ConnectionStatus status={status} />
        {(status === "error" || status === "disconnected") && (
          <Button
            variant="ghost"
            size="sm"
            onClick={handleReconnect}
            className="ml-1 h-6 gap-1 text-xs text-muted-foreground hover:text-foreground"
          >
            <RefreshCw className="size-3" />
            Reconnect
          </Button>
        )}
        <Button
          variant="ghost"
          size="sm"
          onClick={onClose}
          className="ml-2 h-6 w-6 shrink-0 p-0 text-muted-foreground hover:text-foreground"
          aria-label="Close terminal panel"
        >
          <X className="size-3" />
        </Button>
      </div>

      {/* xterm.js mount point */}
      <div
        ref={containerRef}
        className="min-h-0 flex-1 overflow-hidden"
        style={{ background: "#09090b" }}
        aria-label="Embedded terminal emulator"
        role="region"
      />
    </div>
  );
}
