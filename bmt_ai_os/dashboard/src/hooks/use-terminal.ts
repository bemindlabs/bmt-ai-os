"use client";

import { useRef, useCallback, useState } from "react";

// xterm.js is ESM-only and uses browser APIs — dynamic import is required.
// Types are imported statically so TypeScript can type-check call sites.
import type { Terminal } from "@xterm/xterm";
import type { FitAddon } from "@xterm/addon-fit";

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
  /** Connect to the local WebSocket terminal (wsUrl is used directly). */
  connect: () => Promise<void>;
  /** Connect to the SSH WebSocket proxy. */
  connectSsh: (opts: SshConnectOptions) => Promise<void>;
  /** Close the current WebSocket connection. */
  disconnect: () => void;
  /** Current connection status. */
  status: ConnectionStatus;
  /** Write raw text to the terminal. */
  write: (data: string) => void;
  /**
   * Tear down xterm.js and close the WebSocket.
   * Call this inside a useEffect cleanup function.
   */
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

  // ------------------------------------------------------------------
  // Terminal initialisation (idempotent)
  // ------------------------------------------------------------------
  const initTerm = useCallback(async (): Promise<boolean> => {
    if (cleanedUp.current) return false;
    if (termRef.current) return true;

    const container = containerRef.current;
    if (!container) return false;

    const { Terminal: XTerm } = await import("@xterm/xterm");
    const { FitAddon } = await import("@xterm/addon-fit");

    // Guard against concurrent calls and unmount racing the async import.
    if (termRef.current) return true;
    if (cleanedUp.current) return false;

    const term = new XTerm({
      cursorBlink: true,
      fontFamily:
        "var(--font-geist-mono, 'Fira Mono', 'Cascadia Code', monospace)",
      fontSize: 13,
      lineHeight: 1.4,
      theme: XTERM_THEME,
      allowTransparency: false,
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(container);
    fitAddon.fit();

    termRef.current = term;
    fitRef.current = fitAddon;

    return true;
  }, [containerRef]);

  // ------------------------------------------------------------------
  // Connect to local WebSocket terminal
  // ------------------------------------------------------------------
  const connect = useCallback(async (): Promise<void> => {
    const ready = await initTerm();
    // Small tick to let React flush the DOM mount.
    await new Promise<void>((r) => setTimeout(r, 50));

    const term = termRef.current;
    const fitAddon = fitRef.current;
    if (!ready || !term || !fitAddon) return;

    term.clear();
    setStatus("connecting");

    const ws = new WebSocket(wsUrl);
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
      onDisconnect?.();
    };

    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(new TextEncoder().encode(data));
      }
    });

    _attachResizeObserver(term, fitAddon, ws);
  }, [wsUrl, initTerm, onConnect, onDisconnect, onError]);

  // ------------------------------------------------------------------
  // Connect to SSH WebSocket terminal
  // ------------------------------------------------------------------
  const connectSsh = useCallback(
    async ({
      host,
      port,
      username,
      authMethod,
      password,
    }: SshConnectOptions): Promise<void> => {
      const ready = await initTerm();
      await new Promise<void>((r) => setTimeout(r, 50));

      const term = termRef.current;
      const fitAddon = fitRef.current;
      if (!ready || !term || !fitAddon) return;

      term.clear();

      if (!host.trim()) {
        term.writeln("\r\n\x1b[31mError: SSH host is required.\x1b[0m");
        return;
      }

      setStatus("connecting");

      // Build the SSH WebSocket URL from the base wsUrl.
      const url = new URL(wsUrl);
      url.pathname = "/ws/ssh";
      url.searchParams.set("host", host);
      url.searchParams.set("port", String(port));
      url.searchParams.set("username", username);
      url.searchParams.set("auth", authMethod);

      const ws = new WebSocket(url.toString());
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      let handshakeDone = false;

      ws.onmessage = (event) => {
        // First messages may be JSON control frames.
        if (typeof event.data === "string") {
          try {
            const ctrl = JSON.parse(event.data as string) as Record<string, unknown>;
            const type = ctrl["type"] as string | undefined;

            if (type === "auth" && ctrl["method"] === "password") {
              if (password) {
                ws.send(password);
              } else {
                // Prompt for password inline in the terminal.
                term.write("\r\nPassword: ");
                let pwBuf = "";
                const dataSub = term.onData((key) => {
                  if (key === "\r" || key === "\n") {
                    dataSub.dispose();
                    term.writeln("");
                    ws.send(pwBuf);
                    pwBuf = "";
                  } else if (key === "\x7f" || key === "\b") {
                    if (pwBuf.length > 0) pwBuf = pwBuf.slice(0, -1);
                  } else if (key.charCodeAt(0) >= 32) {
                    pwBuf += key;
                  }
                });
              }
              return;
            }

            if (type === "connected") {
              handshakeDone = true;
              setStatus("connected");
              onConnect?.();
              const dims = fitAddon.proposeDimensions();
              if (dims) {
                ws.send(
                  JSON.stringify({ type: "resize", cols: dims.cols, rows: dims.rows })
                );
              }
              return;
            }

            if (type === "error") {
              setStatus("error");
              const msg = `SSH error: ${ctrl["message"] ?? "unknown"}`;
              term.writeln(`\r\n\x1b[31m${msg}\x1b[0m`);
              onError?.(msg);
              return;
            }
          } catch {
            // Not JSON — fall through to write as terminal data.
          }
        }

        // Binary or plain terminal data.
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
        if (!handshakeDone) {
          setStatus("error");
        } else {
          setStatus("disconnected");
          onDisconnect?.();
        }
        term.writeln("\r\n\x1b[33mSSH session closed.\x1b[0m");
      };

      term.onData((data) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(new TextEncoder().encode(data));
        }
      });

      _attachResizeObserver(term, fitAddon, ws);
    },
    [wsUrl, initTerm, onConnect, onDisconnect, onError]
  );

  // ------------------------------------------------------------------
  // Disconnect
  // ------------------------------------------------------------------
  const disconnect = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
    setStatus("disconnected");
  }, []);

  // ------------------------------------------------------------------
  // Write raw text to terminal
  // ------------------------------------------------------------------
  const write = useCallback((data: string) => {
    termRef.current?.write(data);
  }, []);

  // ------------------------------------------------------------------
  // Dispose — called from useEffect cleanup in the host component
  // ------------------------------------------------------------------
  const dispose = useCallback(() => {
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
  }, []);

  return { connect, connectSsh, disconnect, status, write, dispose };
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function _attachResizeObserver(
  term: Terminal,
  fitAddon: FitAddon,
  ws: WebSocket
): void {
  const container = (
    term as Terminal & { _core?: { _viewportElement?: Element } }
  )._core?._viewportElement?.parentElement;

  if (!container) return;

  const ro = new ResizeObserver(() => {
    fitAddon.fit();
    const dims = fitAddon.proposeDimensions();
    if (dims && ws.readyState === WebSocket.OPEN) {
      ws.send(
        JSON.stringify({ type: "resize", cols: dims.cols, rows: dims.rows })
      );
    }
  });

  ro.observe(container);
  (term as Terminal & { _ro?: ResizeObserver })._ro = ro;
}
