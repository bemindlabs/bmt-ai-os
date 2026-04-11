"use client";

import { useEffect, useRef, useCallback } from "react";

// xterm.js is ESM-only and uses browser APIs — dynamic import is required.
// Types are imported statically so TypeScript can type-check call sites.
import type { Terminal } from "@xterm/xterm";
import type { FitAddon } from "@xterm/addon-fit";

const API_ORIGIN =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

/** Convert an HTTP(S) origin to a WS(S) URL. */
function wsUrl(origin: string, path: string): string {
  const url = new URL(origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = path;
  return url.toString();
}

export function TerminalView() {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const cleanedUp = useRef(false);

  const connect = useCallback(async () => {
    if (!containerRef.current || cleanedUp.current) return;

    // Dynamic imports keep xterm out of the server bundle.
    const { Terminal: XTerm } = await import("@xterm/xterm");
    const { FitAddon } = await import("@xterm/addon-fit");

    // Guard against double-init (StrictMode double-invoke).
    if (termRef.current || cleanedUp.current) return;

    const term = new XTerm({
      cursorBlink: true,
      fontFamily: "var(--font-geist-mono, 'Fira Mono', 'Cascadia Code', monospace)",
      fontSize: 13,
      lineHeight: 1.4,
      theme: {
        background: "#09090b",        // zinc-950
        foreground: "#e4e4e7",        // zinc-200
        cursor:     "#a1a1aa",        // zinc-400
        selectionBackground: "#3f3f46", // zinc-700
        black:   "#18181b",
        red:     "#f87171",
        green:   "#4ade80",
        yellow:  "#facc15",
        blue:    "#60a5fa",
        magenta: "#c084fc",
        cyan:    "#22d3ee",
        white:   "#e4e4e7",
        brightBlack:   "#3f3f46",
        brightRed:     "#fca5a5",
        brightGreen:   "#86efac",
        brightYellow:  "#fde047",
        brightBlue:    "#93c5fd",
        brightMagenta: "#d8b4fe",
        brightCyan:    "#67e8f9",
        brightWhite:   "#fafafa",
      },
      allowTransparency: false,
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(containerRef.current);
    fitAddon.fit();

    termRef.current = term;
    fitRef.current = fitAddon;

    // Connect WebSocket to backend shell.
    const url = wsUrl(API_ORIGIN, "/ws/terminal");
    const ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onopen = () => {
      // Send initial window size.
      const dims = fitAddon.proposeDimensions();
      if (dims) {
        ws.send(JSON.stringify({ type: "resize", cols: dims.cols, rows: dims.rows }));
      }
    };

    ws.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        term.write(new Uint8Array(event.data));
      } else {
        term.write(event.data as string);
      }
    };

    ws.onerror = () => {
      term.writeln("\r\n\x1b[31mWebSocket error — could not connect to controller.\x1b[0m");
    };

    ws.onclose = () => {
      term.writeln("\r\n\x1b[33mConnection closed.\x1b[0m");
    };

    // Forward keyboard input to shell.
    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(new TextEncoder().encode(data));
      }
    });

    // Resize observer: refit + notify server on container size change.
    const ro = new ResizeObserver(() => {
      if (!fitRef.current || !wsRef.current) return;
      fitRef.current.fit();
      const dims = fitRef.current.proposeDimensions();
      if (dims && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(
          JSON.stringify({ type: "resize", cols: dims.cols, rows: dims.rows })
        );
      }
    });
    if (containerRef.current) ro.observe(containerRef.current);

    // Cleanup stored so the effect return can call it.
    (term as Terminal & { _ro?: ResizeObserver })._ro = ro;
  }, []);

  useEffect(() => {
    cleanedUp.current = false;
    connect();

    return () => {
      cleanedUp.current = true;

      wsRef.current?.close();
      wsRef.current = null;

      const t = termRef.current as (Terminal & { _ro?: ResizeObserver }) | null;
      if (t) {
        t._ro?.disconnect();
        t.dispose();
        termRef.current = null;
      }

      fitRef.current = null;
    };
  }, [connect]);

  return (
    <div
      ref={containerRef}
      className="h-full w-full overflow-hidden rounded-lg"
      style={{ background: "#09090b" }}
      // xterm manages its own focus; the wrapper div is purely a mount point.
      aria-label="Terminal emulator"
      role="region"
    />
  );
}
