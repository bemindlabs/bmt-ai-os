"use client";

import { useEffect, useRef, useState, useCallback, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Plus, X, Terminal as TerminalIcon } from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TabInfo {
  id: string;
  label: string;
  host: string | null;
  user: string | null;
}

const STORAGE_KEY = "bmt_terminal_tabs";

let _tabCounter = 0;
function newTabId() {
  _tabCounter += 1;
  return `tab-${Date.now()}-${_tabCounter}`;
}

function tabLabel(host: string | null, user: string | null): string {
  if (!host) return "Local";
  return `${user ?? "root"}@${host}`;
}

// ---------------------------------------------------------------------------
// Single xterm-like terminal pane (uses WebSocket-based mock)
// We implement a minimal VT100-compatible terminal with a <textarea> because
// xterm.js is not installed. A real deployment can swap this component.
// ---------------------------------------------------------------------------

interface TerminalPaneProps {
  host: string | null;
  user: string | null;
  active: boolean;
}

function TerminalPane({ host, user, active }: TerminalPaneProps) {
  const outputRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [lines, setLines] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);

  // Attempt WebSocket connection
  useEffect(() => {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const wsBase = process.env.NEXT_PUBLIC_API_URL?.replace(/^https?/, protocol) ??
      `${protocol}://${window.location.hostname}:8080`;

    const params = new URLSearchParams();
    if (host) params.set("host", host);
    if (user) params.set("user", user ?? "root");

    const token = localStorage.getItem("bmt_auth_token");
    if (token) params.set("token", token);

    const url = `${wsBase}/api/v1/terminal/ws?${params.toString()}`;

    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        setLines((prev) => [
          ...prev,
          `\x1b[32mConnected to ${host ?? "localhost"}\x1b[0m`,
        ]);
      };

      ws.onmessage = (evt) => {
        const text: string = typeof evt.data === "string" ? evt.data : "";
        setLines((prev) => [...prev, text]);
      };

      ws.onclose = () => {
        setConnected(false);
        setLines((prev) => [
          ...prev,
          "\x1b[33mConnection closed.\x1b[0m",
        ]);
      };

      ws.onerror = () => {
        setConnected(false);
        setLines((prev) => [
          ...prev,
          `\x1b[31mWebSocket error — terminal backend may not be running.\x1b[0m`,
          `\x1b[2mTip: ensure the controller exposes /api/v1/terminal/ws\x1b[0m`,
        ]);
      };
    } catch {
      setLines([
        `\x1b[31mCould not open WebSocket to ${wsBase}\x1b[0m`,
      ]);
    }

    return () => {
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [host, user]);

  // Auto-scroll output
  useEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight;
    }
  }, [lines]);

  // Focus input when tab becomes active
  useEffect(() => {
    if (active) {
      inputRef.current?.focus();
    }
  }, [active]);

  function sendInput(line: string) {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(line + "\n");
    } else {
      // Echo locally when not connected
      setLines((prev) => [
        ...prev,
        `\x1b[2m$ ${line}\x1b[0m`,
        `\x1b[31m(not connected)\x1b[0m`,
      ]);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      const cmd = input.trim();
      if (cmd) {
        setLines((prev) => [...prev, `$ ${cmd}`]);
        sendInput(cmd);
      }
      setInput("");
    }
  }

  // Strip ANSI escape codes for plain rendering
  // (A real xterm.js integration would render colours natively.)
  function stripAnsi(text: string): string {
    // eslint-disable-next-line no-control-regex
    return text.replace(/\x1b\[[0-9;]*m/g, "");
  }

  return (
    <div
      className={cn(
        "flex h-full flex-col bg-[#0d1117] font-mono text-sm text-green-400",
        !active && "hidden",
      )}
    >
      {/* Status bar */}
      <div className="flex items-center gap-2 border-b border-white/10 px-3 py-1.5 text-xs text-muted-foreground">
        <span
          className={cn(
            "size-2 rounded-full",
            connected ? "bg-green-500" : "bg-red-500",
          )}
        />
        <span>{connected ? "Connected" : "Disconnected"}</span>
        {host && (
          <>
            <span className="opacity-40">|</span>
            <span>
              {user ?? "root"}@{host}
            </span>
          </>
        )}
      </div>

      {/* Output */}
      <div
        ref={outputRef}
        className="flex-1 overflow-y-auto px-3 py-2 text-xs leading-relaxed"
      >
        {lines.map((line, i) => (
          <div key={i} className="whitespace-pre-wrap break-all">
            {stripAnsi(line)}
          </div>
        ))}
      </div>

      {/* Input */}
      <div className="flex items-center gap-2 border-t border-white/10 px-3 py-2">
        <span className="text-xs text-green-500">$</span>
        <input
          ref={inputRef}
          className="flex-1 bg-transparent text-xs text-green-400 outline-none placeholder:text-green-900"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="type command and press Enter"
          autoComplete="off"
          spellCheck={false}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab bar + multi-tab orchestrator
// ---------------------------------------------------------------------------

function TerminalTabs({ initialHost, initialUser }: { initialHost: string | null; initialUser: string | null }) {
  const [tabs, setTabs] = useState<TabInfo[]>(() => {
    // Try to restore from localStorage
    if (typeof window !== "undefined") {
      try {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved) {
          const parsed = JSON.parse(saved) as TabInfo[];
          if (parsed.length > 0) return parsed;
        }
      } catch {
        // ignore
      }
    }
    // Default: one tab with the initial host (from query params)
    return [
      {
        id: newTabId(),
        label: tabLabel(initialHost, initialUser),
        host: initialHost,
        user: initialUser,
      },
    ];
  });

  const [activeId, setActiveId] = useState<string>(() => tabs[0]?.id ?? "");

  // Persist tabs to localStorage on change
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(tabs));
    } catch {
      // ignore
    }
  }, [tabs]);

  function addTab() {
    const id = newTabId();
    const tab: TabInfo = {
      id,
      label: tabLabel(initialHost, initialUser),
      host: initialHost,
      user: initialUser,
    };
    setTabs((prev) => [...prev, tab]);
    setActiveId(id);
  }

  function closeTab(id: string) {
    setTabs((prev) => {
      const next = prev.filter((t) => t.id !== id);
      if (next.length === 0) {
        // Always keep at least one tab
        const fallback: TabInfo = {
          id: newTabId(),
          label: tabLabel(initialHost, initialUser),
          host: initialHost,
          user: initialUser,
        };
        setActiveId(fallback.id);
        return [fallback];
      }
      // If closing the active tab, select adjacent tab
      if (id === activeId) {
        const idx = prev.findIndex((t) => t.id === id);
        const nextActive = next[Math.max(0, idx - 1)];
        setActiveId(nextActive.id);
      }
      return next;
    });
  }

  return (
    <div className="flex h-full flex-col bg-[#0d1117]">
      {/* Tab bar */}
      <div className="flex items-center gap-0 overflow-x-auto border-b border-white/10 bg-[#161b22] px-1">
        {tabs.map((tab) => (
          <div
            key={tab.id}
            className={cn(
              "group flex shrink-0 cursor-pointer items-center gap-1.5 rounded-t px-3 py-2 text-xs transition-colors",
              tab.id === activeId
                ? "bg-[#0d1117] text-green-400"
                : "text-muted-foreground hover:bg-[#0d1117]/50 hover:text-foreground",
            )}
            onClick={() => setActiveId(tab.id)}
          >
            <TerminalIcon className="size-3 shrink-0" />
            <span className="max-w-[120px] truncate">{tab.label}</span>
            <button
              className={cn(
                "ml-1 rounded p-0.5 opacity-0 transition-opacity hover:bg-white/10 group-hover:opacity-100",
                tab.id === activeId && "opacity-60",
              )}
              onClick={(e) => {
                e.stopPropagation();
                closeTab(tab.id);
              }}
              aria-label={`Close ${tab.label}`}
            >
              <X className="size-2.5" />
            </button>
          </div>
        ))}

        {/* New tab button */}
        <button
          className="ml-1 flex shrink-0 items-center justify-center rounded p-1.5 text-muted-foreground hover:bg-white/10 hover:text-foreground"
          onClick={addTab}
          aria-label="Open new terminal tab"
          title="New terminal tab"
        >
          <Plus className="size-3.5" />
        </button>
      </div>

      {/* Terminal panes */}
      <div className="min-h-0 flex-1">
        {tabs.map((tab) => (
          <TerminalPane
            key={tab.id}
            host={tab.host}
            user={tab.user}
            active={tab.id === activeId}
          />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page wrapper (reads search params via Suspense boundary)
// ---------------------------------------------------------------------------

function TerminalPageInner() {
  const params = useSearchParams();
  const host = params.get("host");
  const user = params.get("user");

  return (
    <div className="-m-6 h-[calc(100vh-3.5rem)] overflow-hidden">
      <TerminalTabs initialHost={host} initialUser={user} />
    </div>
  );
}

export default function TerminalPage() {
  return (
    <Suspense
      fallback={
        <div className="-m-6 flex h-[calc(100vh-3.5rem)] items-center justify-center bg-[#0d1117] font-mono text-sm text-green-400">
          Loading terminal…
        </div>
      }
    >
      <TerminalPageInner />
    </Suspense>
  );
}
