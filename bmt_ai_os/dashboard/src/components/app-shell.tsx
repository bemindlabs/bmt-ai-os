"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";
import { WorkspaceLayout } from "@/components/workspace-layout";
import { WorkspaceTabs, type WorkspaceTab, type TabKind } from "@/components/workspace-tabs";
import { ContextPanel } from "@/components/context-panel";
import { SessionSidebar } from "@/components/session-sidebar";
import {
  listSessions,
  createSession,
  deleteSession,
  type Session,
} from "@/lib/sessions";

// ─── Constants ────────────────────────────────────────────────────────────────

const TABS_STORAGE_KEY = "bmt_workspace_tabs";
const DEFAULT_MODEL = "qwen2.5-coder:7b";

// ─── Tab persistence ──────────────────────────────────────────────────────────

interface PersistedTabs {
  tabs: WorkspaceTab[];
  activeTabId: string | null;
}

function loadTabs(): PersistedTabs {
  if (typeof window === "undefined") {
    return { tabs: [makeDefaultTab()], activeTabId: null };
  }
  try {
    const raw = localStorage.getItem(TABS_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as PersistedTabs;
      if (parsed.tabs?.length) return parsed;
    }
  } catch {
    // ignore
  }
  const defaultTab = makeDefaultTab();
  return { tabs: [defaultTab], activeTabId: defaultTab.id };
}

function saveTabs(tabs: WorkspaceTab[], activeTabId: string | null): void {
  try {
    localStorage.setItem(TABS_STORAGE_KEY, JSON.stringify({ tabs, activeTabId }));
  } catch {
    // ignore
  }
}

function makeId(): string {
  return `tab_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
}

function makeDefaultTab(): WorkspaceTab {
  return { id: makeId(), kind: "chat", label: "Chat", pinned: false };
}

/** Derive the TabKind from a Next.js pathname. */
function kindFromPathname(pathname: string): TabKind | null {
  if (pathname === "/") return "overview";
  if (pathname.startsWith("/chat")) return "chat";
  if (pathname.startsWith("/settings")) return "settings";
  if (pathname.startsWith("/training")) return "training";
  if (pathname.startsWith("/models")) return "models";
  if (pathname.startsWith("/providers")) return "providers";
  if (pathname.startsWith("/logs")) return "logs";
  return null;
}

/** Map a tab kind back to a route. */
function routeFromKind(kind: TabKind): string {
  const map: Record<TabKind, string> = {
    chat: "/chat",
    settings: "/settings",
    training: "/training",
    overview: "/",
    models: "/models",
    providers: "/providers",
    logs: "/logs",
  };
  return map[kind] ?? "/";
}

// ─── Props ────────────────────────────────────────────────────────────────────

interface AppShellProps {
  children: React.ReactNode;
}

// ─── Component ────────────────────────────────────────────────────────────────

export function AppShell({ children }: AppShellProps) {
  const router = useRouter();
  const pathname = usePathname();

  // ── Tab state ──────────────────────────────────────────────────────────────
  const [tabs, setTabs] = useState<WorkspaceTab[]>(() => loadTabs().tabs);
  const [activeTabId, setActiveTabId] = useState<string | null>(
    () => loadTabs().activeTabId
  );

  // Persist tab state whenever it changes
  useEffect(() => {
    saveTabs(tabs, activeTabId);
  }, [tabs, activeTabId]);

  // Sync active tab when pathname changes (e.g. sidebar nav click)
  const lastSyncedPathname = useRef<string | null>(null);
  useEffect(() => {
    if (pathname === lastSyncedPathname.current) return;
    lastSyncedPathname.current = pathname;

    const kind = kindFromPathname(pathname);
    if (!kind) return;

    // Check if an existing tab for this kind is already active
    const activeTab = tabs.find((t) => t.id === activeTabId);
    if (activeTab?.kind === kind) return;

    // Find an existing tab of that kind
    const existing = tabs.find((t) => t.kind === kind);
    if (existing) {
      setActiveTabId(existing.id);
    } else {
      // Open a new tab for the navigated page
      const newTab: WorkspaceTab = { id: makeId(), kind };
      setTabs((prev) => [...prev, newTab]);
      setActiveTabId(newTab.id);
    }
  }, [pathname, tabs, activeTabId]);

  const handleActivate = useCallback(
    (id: string) => {
      const tab = tabs.find((t) => t.id === id);
      if (!tab) return;
      setActiveTabId(id);
      router.push(routeFromKind(tab.kind));
    },
    [tabs, router]
  );

  const handleClose = useCallback(
    (id: string) => {
      setTabs((prev) => {
        const next = prev.filter((t) => t.id !== id);
        // Always keep at least one tab
        if (next.length === 0) {
          const fallback = makeDefaultTab();
          setActiveTabId(fallback.id);
          router.push("/chat");
          return [fallback];
        }
        // If closing the active tab, activate the nearest one
        if (id === activeTabId) {
          const closedIdx = prev.findIndex((t) => t.id === id);
          const nextActive = next[Math.min(closedIdx, next.length - 1)];
          setActiveTabId(nextActive.id);
          router.push(routeFromKind(nextActive.kind));
        }
        return next;
      });
    },
    [activeTabId, router]
  );

  const handleNewTab = useCallback(() => {
    const newTab: WorkspaceTab = { id: makeId(), kind: "chat" };
    setTabs((prev) => [...prev, newTab]);
    setActiveTabId(newTab.id);
    router.push("/chat");
  }, [router]);

  const handleReorder = useCallback((fromIndex: number, toIndex: number) => {
    setTabs((prev) => {
      const next = [...prev];
      const [moved] = next.splice(fromIndex, 1);
      next.splice(toIndex, 0, moved);
      return next;
    });
  }, []);

  // ── Session state (left panel) ─────────────────────────────────────────────
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);

  useEffect(() => {
    const loaded = listSessions();
    setSessions(loaded);
    if (loaded.length > 0 && !activeSessionId) {
      setActiveSessionId(loaded[0].id);
    }
  }, []);

  const handleNewSession = useCallback(() => {
    const s = createSession(DEFAULT_MODEL);
    setSessions((prev) => [s, ...prev]);
    setActiveSessionId(s.id);
    // Ensure a chat tab is open
    const chatTab = tabs.find((t) => t.kind === "chat");
    if (chatTab) {
      setActiveTabId(chatTab.id);
    } else {
      const newTab: WorkspaceTab = { id: makeId(), kind: "chat" };
      setTabs((prev) => [...prev, newTab]);
      setActiveTabId(newTab.id);
    }
    router.push("/chat");
  }, [tabs, router]);

  const handleSelectSession = useCallback(
    (id: string) => {
      setActiveSessionId(id);
      // Ensure chat is in view
      const chatTab = tabs.find((t) => t.kind === "chat");
      if (chatTab) {
        setActiveTabId(chatTab.id);
      } else {
        const newTab: WorkspaceTab = { id: makeId(), kind: "chat" };
        setTabs((prev) => [...prev, newTab]);
        setActiveTabId(newTab.id);
      }
      router.push("/chat");
    },
    [tabs, router]
  );

  const handleDeleteSession = useCallback(
    (id: string) => {
      deleteSession(id);
      setSessions((prev) => {
        const next = prev.filter((s) => s.id !== id);
        if (activeSessionId === id) {
          setActiveSessionId(next[0]?.id ?? null);
        }
        return next;
      });
    },
    [activeSessionId]
  );

  // ── Render ─────────────────────────────────────────────────────────────────

  const leftPanel = (
    <SessionSidebar
      sessions={sessions}
      activeSessionId={activeSessionId}
      onSelect={handleSelectSession}
      onNew={handleNewSession}
      onDelete={handleDeleteSession}
    />
  );

  const centerPanel = (
    <WorkspaceTabs
      tabs={tabs}
      activeTabId={activeTabId}
      onActivate={handleActivate}
      onClose={handleClose}
      onNew={handleNewTab}
      onReorder={handleReorder}
    >
      <div className="h-full overflow-y-auto p-6">{children}</div>
    </WorkspaceTabs>
  );

  const rightPanel = <ContextPanel />;

  return (
    <WorkspaceLayout
      leftPanel={leftPanel}
      centerPanel={centerPanel}
      rightPanel={rightPanel}
      className="h-full"
    />
  );
}
