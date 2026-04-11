"use client";

import { useEffect, useRef, useState, useReducer, useCallback } from "react";
import { useSearchParams } from "next/navigation";

import { useTerminal } from "@/hooks/use-terminal";
import { ConnectionStatus } from "@/components/terminal/connection-status";
import {
  TerminalConnectionForm,
  type Mode,
  type SshFormState,
} from "@/components/terminal/terminal-connection-form";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const API_ORIGIN = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

/** Convert an HTTP(S) origin to a WS(S) URL with a given path. */
function buildWsUrl(origin: string, path: string): string {
  const url = new URL(origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = path;
  return url.toString();
}

const LOCAL_WS_URL = buildWsUrl(API_ORIGIN, "/ws/terminal");

// ---------------------------------------------------------------------------
// SSH form state reducer
// ---------------------------------------------------------------------------

function sshReducer(state: SshFormState, patch: Partial<SshFormState>): SshFormState {
  return { ...state, ...patch };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TerminalView() {
  const searchParams = useSearchParams();

  const [mode, setMode] = useState<Mode>("local");
  const [sshState, dispatch] = useReducer(sshReducer, {
    host: searchParams.get("host") ?? "",
    port: searchParams.get("port") ? Number(searchParams.get("port")) : 22,
    username: searchParams.get("user") ?? "root",
    authMethod: "password",
  });

  const containerRef = useRef<HTMLDivElement>(null);

  const { connect, connectSsh, disconnect, status, dispose } = useTerminal({
    containerRef,
    wsUrl: LOCAL_WS_URL,
  });

  // ------------------------------------------------------------------
  // Lifecycle — init terminal on mount, clean up on unmount
  // ------------------------------------------------------------------
  useEffect(() => {
    return () => {
      dispose();
    };
  }, [dispose]);

  // Pre-select SSH mode when a host is passed via URL query params.
  useEffect(() => {
    if (searchParams.get("host")) {
      setMode("ssh");
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ------------------------------------------------------------------
  // Connect handler
  // ------------------------------------------------------------------
  const handleConnect = useCallback(() => {
    if (mode === "local") {
      void connect();
    } else {
      void connectSsh({
        host: sshState.host,
        port: sshState.port,
        username: sshState.username,
        authMethod: sshState.authMethod,
      });
    }
  }, [mode, connect, connectSsh, sshState]);

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------
  return (
    <div className="flex h-full flex-col">
      <TerminalConnectionForm
        mode={mode}
        sshState={sshState}
        status={status}
        onModeChange={setMode}
        onSshChange={dispatch}
        onConnect={handleConnect}
        onDisconnect={disconnect}
      />

      <div className="flex items-center border-b border-border bg-muted/10 px-3 py-1">
        <ConnectionStatus status={status} />
      </div>

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
