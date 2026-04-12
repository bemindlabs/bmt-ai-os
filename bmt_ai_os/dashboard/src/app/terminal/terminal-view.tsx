"use client";

import { useEffect, useRef, useState, useReducer, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

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

/**
 * Build the WebSocket URL from the browser's current location.
 * This avoids using NEXT_PUBLIC_API_URL which may contain Docker-internal
 * hostnames (e.g., "http://controller:8080") unresolvable from the browser.
 */
function getWsBaseUrl(): string {
  if (typeof window === "undefined") return "ws://localhost:8080";
  const loc = window.location;
  const proto = loc.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${loc.hostname}:8080`;
}

const LOCAL_WS_URL = `${getWsBaseUrl()}/ws/terminal`;

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

  useEffect(() => {
    return () => { dispose(); };
  }, [dispose]);

  // Pre-select SSH mode when host is in URL
  useEffect(() => {
    if (searchParams.get("host")) setMode("ssh");
  }, []); // eslint-disable-line react-hooks/exhaustive-deps — intentional: run once on mount

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

  const handleReconnect = useCallback(() => {
    disconnect();
    // Small delay to let cleanup finish
    setTimeout(() => handleConnect(), 100);
  }, [disconnect, handleConnect]);

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
        {(status === "error" || status === "disconnected") && (
          <Button
            variant="ghost"
            size="sm"
            onClick={handleReconnect}
            className="ml-2 h-6 gap-1 text-xs text-muted-foreground hover:text-foreground"
          >
            <RefreshCw className="size-3" />
            Reconnect
          </Button>
        )}
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
