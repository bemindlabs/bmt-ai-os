"use client";

import { useRef, useCallback, useState } from "react";

import type { Terminal } from "@xterm/xterm";
import type { FitAddon } from "@xterm/addon-fit";
import type { IDisposable } from "@xterm/xterm";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ConnectionStatus = "disconnected" | "connecting" | "connected" | "error";

export interface UseTerminalOptions {
  containerRef: React.RefObject<HTMLDivElement | null>;
  wsUrl: string;
  onConnect?: () => void;
  onDisconnect?: () => void;
  onError?: (message: string) => void;
}

export interface SshConnectOptions {
  host: string;
  port: number;
  username: string;
  authMethod: "password" | "key";
  password?: string;
}

export interface UseTerminalReturn {
  connect: () => Promise<void>;
  connectSsh: (opts: SshConnectOptions) => Promise<void>;
  disconnect: () => void;
  status: ConnectionStatus;
  write: (data: string) => void;
  dispose: () => void;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const XTERM_THEME = {
  background: "#09090b",
  foreground: "#e4e4e7",
  cursor: "#a1a1aa",
  selectionBackground: "#3f3f46",
  black: "#18181b",
  red: "#f87171",
  green: "#4ade80",
  yellow: "#facc15",
  blue: "#60a5fa",
  magenta: "#c084fc",
  cyan: "#22d3ee",
  white: "#e4e4e7",
  brightBlack: "#3f3f46",
  brightRed: "#fca5a5",
  brightGreen: "#86efac",
  brightYellow: "#fde047",
  brightBlue: "#93c5fd",
  brightMagenta: "#d8b4fe",
  brightCyan: "#67e8f9",
  brightWhite: "#fafafa",
};

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useTerminal({
  containerRef,
  wsUrl,
  onConnect,
  onDisconnect,
  onError,
}: UseTerminalOptions): UseTerminalReturn {
  const [status, setStatus] = useState<ConnectionStatus>("disconnected");

  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const cleanedUp = useRef(false);

  // Track subscriptions for proper cleanup
  const dataSubRef = useRef<IDisposable | null>(null);
  const roRef = useRef<ResizeObserver | null>(null);

  // ------------------------------------------------------------------
  // Cleanup subscriptions before (re)connecting
  // ------------------------------------------------------------------
  const cleanupSubscriptions = useCallback(() => {
    dataSubRef.current?.dispose();
    dataSubRef.current = null;
    roRef.current?.disconnect();
    roRef.current = null;
  }, []);

  // ------------------------------------------------------------------
  // Terminal initialisation (idempotent)
  // ------------------------------------------------------------------
  const initTerm = useCallback(async (): Promise<boolean> => {
    if (cleanedUp.current) return false;
    if (termRef.current) return true;

    const container = containerRef.current;
    if (!container) return false;

    const { Terminal: XTerm } = await import("@xterm/xterm");
    const { FitAddon: Fit } = await import("@xterm/addon-fit");

    if (termRef.current) return true;
    if (cleanedUp.current) return false;

    const term = new XTerm({
      cursorBlink: true,
      fontFamily: "var(--font-geist-mono, 'Fira Mono', 'Cascadia Code', monospace)",
      fontSize: 13,
      lineHeight: 1.4,
      theme: XTERM_THEME,
      allowTransparency: false,
    });

    const fitAddon = new Fit();
    term.loadAddon(fitAddon);
    term.open(container);
    fitAddon.fit();

    termRef.current = term;
    fitRef.current = fitAddon;
    return true;
  }, [containerRef]);

  // ------------------------------------------------------------------
  // Attach resize observer (tracked for cleanup)
  // ------------------------------------------------------------------
  const attachResize = useCallback((term: Terminal, fitAddon: FitAddon, ws: WebSocket) => {
    roRef.current?.disconnect();

    const el = term.element?.parentElement;
    if (!el) return;

    const ro = new ResizeObserver(() => {
      fitAddon.fit();
      const dims = fitAddon.proposeDimensions();
      if (dims && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "resize", cols: dims.cols, rows: dims.rows }));
      }
    });

    ro.observe(el);
    roRef.current = ro;
  }, []);

  // ------------------------------------------------------------------
  // Build WS URL with JWT token
  // ------------------------------------------------------------------
  const buildAuthUrl = useCallback((url: string): string => {
    const token = typeof window !== "undefined" ? localStorage.getItem("bmt_auth_token") : null;
    if (!token) return url;
    const u = new URL(url);
    u.searchParams.set("token", token);
    return u.toString();
  }, []);

  // ------------------------------------------------------------------
  // Connect to local WebSocket terminal
  // ------------------------------------------------------------------
  const connect = useCallback(async (): Promise<void> => {
    const ready = await initTerm();
    await new Promise<void>((r) => setTimeout(r, 50));

    const term = termRef.current;
    const fitAddon = fitRef.current;
    if (!ready || !term || !fitAddon) return;

    // Clean up old subscriptions before reconnecting
    cleanupSubscriptions();
    wsRef.current?.close();

    term.clear();
    setStatus("connecting");

    const ws = new WebSocket(buildAuthUrl(wsUrl));
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onopen = () => {
      setStatus("connected");
      onConnect?.();
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
      setStatus("error");
      const msg = "WebSocket error — could not connect to controller.";
      term.writeln(`\r\n\x1b[31m${msg}\x1b[0m`);
      onError?.(msg);
    };

    ws.onclose = () => {
      setStatus("disconnected");
      term.writeln("\r\n\x1b[33mConnection closed.\x1b[0m");
      cleanupSubscriptions();
      onDisconnect?.();
    };

    // Single data subscription — tracked for cleanup
    dataSubRef.current = term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(new TextEncoder().encode(data));
      }
    });

    attachResize(term, fitAddon, ws);
  }, [wsUrl, initTerm, onConnect, onDisconnect, onError, cleanupSubscriptions, attachResize, buildAuthUrl]);

  // ------------------------------------------------------------------
  // SSH password prompt helper
  // ------------------------------------------------------------------
  const promptPassword = useCallback(
    (term: Terminal, ws: WebSocket): IDisposable => {
      term.write("\r\nPassword: ");
      let buf = "";
      return term.onData((key) => {
        if (key === "\r" || key === "\n") {
          term.writeln("");
          ws.send(buf);
        } else if (key === "\x7f" || key === "\b") {
          if (buf.length > 0) buf = buf.slice(0, -1);
        } else if (key.charCodeAt(0) >= 32) {
          buf += key;
        }
      });
    },
    [],
  );

  // ------------------------------------------------------------------
  // Connect to SSH WebSocket terminal
  // ------------------------------------------------------------------
  const connectSsh = useCallback(
    async ({ host, port, username, authMethod, password }: SshConnectOptions): Promise<void> => {
      const ready = await initTerm();
      await new Promise<void>((r) => setTimeout(r, 50));

      const term = termRef.current;
      const fitAddon = fitRef.current;
      if (!ready || !term || !fitAddon) return;

      cleanupSubscriptions();
      wsRef.current?.close();
      term.clear();

      if (!host.trim()) {
        term.writeln("\r\n\x1b[31mError: SSH host is required.\x1b[0m");
        return;
      }

      setStatus("connecting");

      const url = new URL(wsUrl);
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      url.pathname = "/ws/ssh";
      url.searchParams.set("host", host);
      url.searchParams.set("port", String(port));
      url.searchParams.set("username", username);
      url.searchParams.set("auth", authMethod);
      const token = typeof window !== "undefined" ? localStorage.getItem("bmt_auth_token") : null;
      if (token) url.searchParams.set("token", token);

      const ws = new WebSocket(url.toString());
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      let handshakeDone = false;
      let pwSub: IDisposable | null = null;

      ws.onmessage = (event) => {
        // Try to parse control messages (JSON)
        if (typeof event.data === "string") {
          try {
            const ctrl = JSON.parse(event.data) as Record<string, unknown>;
            const type = ctrl["type"] as string | undefined;

            if (type === "auth" && ctrl["method"] === "password") {
              if (password) {
                ws.send(password);
              } else {
                pwSub?.dispose();
                pwSub = promptPassword(term, ws);
              }
              return;
            }
            if (type === "connected") {
              handshakeDone = true;
              setStatus("connected");
              onConnect?.();
              const dims = fitAddon.proposeDimensions();
              if (dims) ws.send(JSON.stringify({ type: "resize", cols: dims.cols, rows: dims.rows }));
              dataSubRef.current = term.onData((data) => {
                if (ws.readyState === WebSocket.OPEN) ws.send(new TextEncoder().encode(data));
              });
              return;
            }
            if (type === "error") {
              setStatus("error");
              term.writeln(`\r\n\x1b[31mSSH error: ${ctrl["message"] ?? "unknown"}\x1b[0m`);
              onError?.(`SSH error: ${ctrl["message"] ?? "unknown"}`);
              return;
            }
          } catch {
            // Not JSON — fall through to terminal write
          }
        }

        if (event.data instanceof ArrayBuffer) {
          term.write(new Uint8Array(event.data));
        } else if (typeof event.data === "string") {
          term.write(event.data);
        }
      };

      ws.onerror = () => {
        setStatus("error");
        const msg = "WebSocket error — could not connect.";
        term.writeln(`\r\n\x1b[31m${msg}\x1b[0m`);
        onError?.(msg);
      };

      ws.onclose = () => {
        pwSub?.dispose();
        pwSub = null;
        setStatus(handshakeDone ? "disconnected" : "error");
        if (handshakeDone) onDisconnect?.();
        term.writeln("\r\n\x1b[33mSSH session closed.\x1b[0m");
        cleanupSubscriptions();
      };

      attachResize(term, fitAddon, ws);
    },
    [wsUrl, initTerm, onConnect, onDisconnect, onError, cleanupSubscriptions, attachResize, promptPassword],
  );

  // ------------------------------------------------------------------
  // Disconnect
  // ------------------------------------------------------------------
  const disconnect = useCallback(() => {
    cleanupSubscriptions();
    wsRef.current?.close();
    wsRef.current = null;
    setStatus("disconnected");
  }, [cleanupSubscriptions]);

  // ------------------------------------------------------------------
  // Write raw text to terminal
  // ------------------------------------------------------------------
  const write = useCallback((data: string) => {
    termRef.current?.write(data);
  }, []);

  // ------------------------------------------------------------------
  // Dispose — called from useEffect cleanup
  // ------------------------------------------------------------------
  const dispose = useCallback(() => {
    cleanedUp.current = true;
    cleanupSubscriptions();
    wsRef.current?.close();
    wsRef.current = null;

    termRef.current?.dispose();
    termRef.current = null;
    fitRef.current = null;
  }, [cleanupSubscriptions]);

  return { connect, connectSsh, disconnect, status, write, dispose };
}
