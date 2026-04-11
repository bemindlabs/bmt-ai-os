"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import { useSearchParams } from "next/navigation";

// xterm.js is ESM-only and uses browser APIs — dynamic import is required.
// Types are imported statically so TypeScript can type-check call sites.
import type { Terminal } from "@xterm/xterm";
import type { FitAddon } from "@xterm/addon-fit";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const API_ORIGIN =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

/** Convert an HTTP(S) origin to a WS(S) URL. */
function wsUrl(origin: string, path: string): string {
  const url = new URL(origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = path;
  return url.toString();
}

/** Build a WS URL for the SSH proxy with query params. */
function sshWsUrl(host: string, port: number, username: string, auth: string): string {
  const url = new URL(API_ORIGIN);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = "/ws/ssh";
  url.searchParams.set("host", host);
  url.searchParams.set("port", String(port));
  url.searchParams.set("username", username);
  url.searchParams.set("auth", auth);
  return url.toString();
}

type Mode = "local" | "ssh";
type AuthMethod = "password" | "key";
type ConnectionStatus = "disconnected" | "connecting" | "connected" | "error";

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

const STATUS_CLASSES: Record<ConnectionStatus, string> = {
  disconnected: "bg-zinc-500",
  connecting: "bg-yellow-400 animate-pulse",
  connected: "bg-green-400",
  error: "bg-red-500",
};

const STATUS_LABELS: Record<ConnectionStatus, string> = {
  disconnected: "Disconnected",
  connecting: "Connecting...",
  connected: "Connected",
  error: "Error",
};

export function TerminalView() {
  const searchParams = useSearchParams();

  // Connection form state — pre-filled from URL query params.
  const [mode, setMode] = useState<Mode>("local");
  const [sshHost, setSshHost] = useState(searchParams.get("host") ?? "");
  const [sshPort, setSshPort] = useState(
    searchParams.get("port") ? Number(searchParams.get("port")) : 22
  );
  const [sshUser, setSshUser] = useState(searchParams.get("user") ?? "root");
  const [authMethod, setAuthMethod] = useState<AuthMethod>("password");
  const [status, setStatus] = useState<ConnectionStatus>("disconnected");

  // Terminal and WebSocket refs.
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const cleanedUp = useRef(false);

  // ------------------------------------------------------------------
  // Terminal initialisation (runs once)
  // ------------------------------------------------------------------
  const initTerm = useCallback(async () => {
    if (!containerRef.current || cleanedUp.current || termRef.current) return;

    const { Terminal: XTerm } = await import("@xterm/xterm");
    const { FitAddon } = await import("@xterm/addon-fit");

    if (termRef.current || cleanedUp.current) return;

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
    term.open(containerRef.current);
    fitAddon.fit();

    termRef.current = term;
    fitRef.current = fitAddon;
  }, []);

  // ------------------------------------------------------------------
  // Connect local terminal
  // ------------------------------------------------------------------
  const connectLocal = useCallback(() => {
    const term = termRef.current;
    const fitAddon = fitRef.current;
    if (!term || !fitAddon) return;

    setStatus("connecting");
    const url = wsUrl(API_ORIGIN, "/ws/terminal");
    const ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onopen = () => {
      setStatus("connected");
      const dims = fitAddon.proposeDimensions();
      if (dims) {
        ws.send(
          JSON.stringify({ type: "resize", cols: dims.cols, rows: dims.rows })
        );
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
      term.writeln(
        "\r\n\x1b[31mWebSocket error — could not connect to controller.\x1b[0m"
      );
    };

    ws.onclose = () => {
      setStatus("disconnected");
      term.writeln("\r\n\x1b[33mConnection closed.\x1b[0m");
    };

    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(new TextEncoder().encode(data));
      }
    });

    _attachResizeObserver(term, fitAddon, ws);
  }, []);

  // ------------------------------------------------------------------
  // Connect SSH terminal
  // ------------------------------------------------------------------
  const connectSsh = useCallback(
    (password?: string) => {
      const term = termRef.current;
      const fitAddon = fitRef.current;
      if (!term || !fitAddon) return;

      setStatus("connecting");
      const url = sshWsUrl(sshHost, sshPort, sshUser, authMethod);
      const ws = new WebSocket(url);
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      let handshakeDone = false;

      ws.onopen = () => {
        // Server will send {"type":"auth","method":"password"} if needed.
        // No action required here; wait for first message.
      };

      ws.onmessage = (event) => {
        // First messages may be JSON control frames.
        if (typeof event.data === "string") {
          try {
            const ctrl = JSON.parse(event.data as string) as Record<
              string,
              unknown
            >;
            const type = ctrl["type"] as string | undefined;

            if (type === "auth" && ctrl["method"] === "password") {
              // Server is requesting the password.
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
                    if (pwBuf.length > 0) {
                      pwBuf = pwBuf.slice(0, -1);
                    }
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
              const dims = fitAddon.proposeDimensions();
              if (dims) {
                ws.send(
                  JSON.stringify({
                    type: "resize",
                    cols: dims.cols,
                    rows: dims.rows,
                  })
                );
              }
              return;
            }

            if (type === "error") {
              setStatus("error");
              term.writeln(
                `\r\n\x1b[31mSSH error: ${ctrl["message"] ?? "unknown"}\x1b[0m`
              );
              return;
            }
          } catch {
            // Not JSON — fall through to write as terminal data.
          }
        }

        // Binary or terminal data.
        if (event.data instanceof ArrayBuffer) {
          term.write(new Uint8Array(event.data));
        } else if (typeof event.data === "string") {
          term.write(event.data);
        }
      };

      ws.onerror = () => {
        setStatus("error");
        term.writeln(
          "\r\n\x1b[31mWebSocket error — could not connect.\x1b[0m"
        );
      };

      ws.onclose = () => {
        if (!handshakeDone) {
          setStatus("error");
        } else {
          setStatus("disconnected");
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
    [sshHost, sshPort, sshUser, authMethod]
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
  // Connect button handler
  // ------------------------------------------------------------------
  const handleConnect = useCallback(async () => {
    // Ensure terminal is initialised.
    if (!termRef.current) {
      await initTerm();
    }
    // Small tick to let React flush the DOM mount.
    await new Promise((r) => setTimeout(r, 50));

    if (!termRef.current) return;
    termRef.current.clear();

    if (mode === "local") {
      connectLocal();
    } else {
      if (!sshHost.trim()) {
        termRef.current.writeln(
          "\r\n\x1b[31mError: SSH host is required.\x1b[0m"
        );
        return;
      }
      connectSsh();
    }
  }, [mode, sshHost, connectLocal, connectSsh, initTerm]);

  // ------------------------------------------------------------------
  // Lifecycle
  // ------------------------------------------------------------------
  useEffect(() => {
    cleanedUp.current = false;
    initTerm();

    return () => {
      cleanedUp.current = true;
      wsRef.current?.close();
      wsRef.current = null;

      const t = termRef.current as
        | (Terminal & { _ro?: ResizeObserver })
        | null;
      if (t) {
        t._ro?.disconnect();
        t.dispose();
        termRef.current = null;
      }
      fitRef.current = null;
    };
  }, [initTerm]);

  // Auto-connect local mode on first load when no SSH host in URL.
  useEffect(() => {
    const hostParam = searchParams.get("host");
    if (hostParam) {
      setMode("ssh");
      setSshHost(hostParam);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const isConnected = status === "connected" || status === "connecting";

  return (
    <div className="flex h-full flex-col">
      {/* Connection form */}
      <div className="flex flex-wrap items-end gap-2 border-b border-border bg-muted/30 px-3 py-2">
        {/* Mode toggle */}
        <div className="flex rounded-lg border border-border overflow-hidden text-xs font-medium">
          <button
            onClick={() => setMode("local")}
            className={`px-3 py-1.5 transition-colors ${
              mode === "local"
                ? "bg-primary text-primary-foreground"
                : "bg-background hover:bg-muted text-foreground"
            }`}
          >
            Local
          </button>
          <button
            onClick={() => setMode("ssh")}
            className={`px-3 py-1.5 transition-colors ${
              mode === "ssh"
                ? "bg-primary text-primary-foreground"
                : "bg-background hover:bg-muted text-foreground"
            }`}
          >
            SSH
          </button>
        </div>

        {/* SSH-specific fields */}
        {mode === "ssh" && (
          <>
            <div className="flex items-center gap-1">
              <label className="text-xs text-muted-foreground shrink-0">
                Host
              </label>
              <Input
                className="h-7 w-36 text-xs"
                placeholder="192.168.1.1"
                value={sshHost}
                onChange={(e) => setSshHost(e.target.value)}
              />
            </div>
            <div className="flex items-center gap-1">
              <label className="text-xs text-muted-foreground shrink-0">
                Port
              </label>
              <Input
                className="h-7 w-16 text-xs"
                type="number"
                min={1}
                max={65535}
                value={sshPort}
                onChange={(e) => setSshPort(Number(e.target.value))}
              />
            </div>
            <div className="flex items-center gap-1">
              <label className="text-xs text-muted-foreground shrink-0">
                User
              </label>
              <Input
                className="h-7 w-24 text-xs"
                placeholder="root"
                value={sshUser}
                onChange={(e) => setSshUser(e.target.value)}
              />
            </div>
            {/* Auth method toggle */}
            <div className="flex rounded-lg border border-border overflow-hidden text-xs font-medium">
              <button
                onClick={() => setAuthMethod("password")}
                className={`px-3 py-1.5 transition-colors ${
                  authMethod === "password"
                    ? "bg-primary text-primary-foreground"
                    : "bg-background hover:bg-muted text-foreground"
                }`}
              >
                Password
              </button>
              <button
                onClick={() => setAuthMethod("key")}
                className={`px-3 py-1.5 transition-colors ${
                  authMethod === "key"
                    ? "bg-primary text-primary-foreground"
                    : "bg-background hover:bg-muted text-foreground"
                }`}
              >
                Key
              </button>
            </div>
          </>
        )}

        {/* Connect / Disconnect buttons */}
        {!isConnected ? (
          <Button size="sm" onClick={handleConnect} className="h-7 text-xs">
            Connect
          </Button>
        ) : (
          <Button
            size="sm"
            variant="destructive"
            onClick={disconnect}
            className="h-7 text-xs"
          >
            Disconnect
          </Button>
        )}

        {/* Status indicator */}
        <div className="ml-auto flex items-center gap-1.5">
          <span
            className={`size-2 rounded-full ${STATUS_CLASSES[status]}`}
            aria-hidden="true"
          />
          <span className="text-xs text-muted-foreground">
            {STATUS_LABELS[status]}
          </span>
        </div>
      </div>

      {/* Terminal area */}
      <div
        ref={containerRef}
        className="min-h-0 flex-1 overflow-hidden rounded-b-lg"
        style={{ background: "#09090b" }}
        aria-label="Terminal emulator"
        role="region"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _attachResizeObserver(
  term: Terminal,
  fitAddon: FitAddon,
  ws: WebSocket
): void {
  const container = (term as Terminal & { _core?: { _viewportElement?: Element } })
    ._core?._viewportElement?.parentElement;

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
