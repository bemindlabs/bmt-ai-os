"use client";

import {
  useState,
  useCallback,
  useRef,
  type ReactNode,
  type DragEvent,
} from "react";
import { X, Plus, MessageSquare, Settings, BrainCog, LayoutDashboard, Layers, ScrollText, BrainCircuit } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

// ─── Types ────────────────────────────────────────────────────────────────────

export type TabKind =
  | "chat"
  | "settings"
  | "training"
  | "overview"
  | "models"
  | "providers"
  | "logs";

export interface WorkspaceTab {
  id: string;
  kind: TabKind;
  /** Display label override — defaults to kind display name */
  label?: string;
  /** True for tabs that cannot be closed (e.g. a permanent home tab) */
  pinned?: boolean;
}

interface WorkspaceTabsProps {
  tabs: WorkspaceTab[];
  activeTabId: string | null;
  onActivate: (id: string) => void;
  onClose: (id: string) => void;
  onNew: () => void;
  onReorder?: (fromIndex: number, toIndex: number) => void;
  children?: ReactNode;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const KIND_META: Record<TabKind, { label: string; Icon: React.ComponentType<{ className?: string }> }> = {
  chat: { label: "Chat", Icon: MessageSquare },
  settings: { label: "Settings", Icon: Settings },
  training: { label: "Training", Icon: BrainCog },
  overview: { label: "Overview", Icon: LayoutDashboard },
  models: { label: "Models", Icon: BrainCircuit },
  providers: { label: "Providers", Icon: Layers },
  logs: { label: "Logs", Icon: ScrollText },
};

function tabLabel(tab: WorkspaceTab): string {
  return tab.label ?? KIND_META[tab.kind]?.label ?? tab.kind;
}

function TabIcon({ kind, className }: { kind: TabKind; className?: string }) {
  const meta = KIND_META[kind];
  if (!meta) return null;
  const { Icon } = meta;
  return <Icon className={className} />;
}

// ─── Single tab button ────────────────────────────────────────────────────────

interface TabItemProps {
  tab: WorkspaceTab;
  isActive: boolean;
  index: number;
  onActivate: () => void;
  onClose: () => void;
  onDragStart: (index: number) => void;
  onDrop: (index: number) => void;
}

function TabItem({
  tab,
  isActive,
  index,
  onActivate,
  onClose,
  onDragStart,
  onDrop,
}: TabItemProps) {
  const [dragOver, setDragOver] = useState(false);

  function handleDragStart(e: DragEvent<HTMLDivElement>) {
    e.dataTransfer.effectAllowed = "move";
    onDragStart(index);
  }

  function handleDragOver(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    setDragOver(true);
  }

  function handleDragLeave() {
    setDragOver(false);
  }

  function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragOver(false);
    onDrop(index);
  }

  return (
    <div
      role="tab"
      aria-selected={isActive}
      tabIndex={isActive ? 0 : -1}
      draggable
      onDragStart={handleDragStart}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onClick={onActivate}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onActivate();
        }
      }}
      className={cn(
        "group relative flex h-full max-w-[180px] min-w-[100px] cursor-pointer select-none items-center gap-1.5 border-r border-border/50 px-3 text-sm transition-colors",
        isActive
          ? "bg-background text-foreground after:absolute after:bottom-0 after:inset-x-0 after:h-0.5 after:bg-primary"
          : "bg-muted/30 text-muted-foreground hover:bg-muted/60 hover:text-foreground",
        dragOver && "bg-primary/10",
      )}
    >
      <TabIcon kind={tab.kind} className="size-3.5 shrink-0 opacity-70" />
      <span className="flex-1 truncate text-xs font-medium">{tabLabel(tab)}</span>

      {!tab.pinned && (
        <button
          type="button"
          aria-label={`Close ${tabLabel(tab)}`}
          onClick={(e) => {
            e.stopPropagation();
            onClose();
          }}
          className={cn(
            "ml-0.5 flex size-4 shrink-0 items-center justify-center rounded transition-all",
            "opacity-0 group-hover:opacity-60 hover:!opacity-100",
            isActive && "opacity-50",
            "hover:bg-muted-foreground/20 focus:outline-none focus-visible:opacity-100"
          )}
          tabIndex={-1}
        >
          <X className="size-3" />
        </button>
      )}
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function WorkspaceTabs({
  tabs,
  activeTabId,
  onActivate,
  onClose,
  onNew,
  onReorder,
  children,
}: WorkspaceTabsProps) {
  const dragFromIndex = useRef<number | null>(null);

  const handleDragStart = useCallback((index: number) => {
    dragFromIndex.current = index;
  }, []);

  const handleDrop = useCallback(
    (toIndex: number) => {
      const fromIndex = dragFromIndex.current;
      dragFromIndex.current = null;
      if (fromIndex === null || fromIndex === toIndex) return;
      onReorder?.(fromIndex, toIndex);
    },
    [onReorder]
  );

  return (
    <div className="flex h-full flex-col">
      {/* Tab bar */}
      <div
        role="tablist"
        aria-label="Work area tabs"
        className="flex h-9 shrink-0 items-stretch overflow-x-auto border-b border-border bg-muted/20 scrollbar-none"
      >
        {tabs.map((tab, index) => (
          <TabItem
            key={tab.id}
            tab={tab}
            index={index}
            isActive={tab.id === activeTabId}
            onActivate={() => onActivate(tab.id)}
            onClose={() => onClose(tab.id)}
            onDragStart={handleDragStart}
            onDrop={handleDrop}
          />
        ))}

        {/* New tab button */}
        <Button
          variant="ghost"
          size="icon"
          className="mx-1 my-auto size-6 shrink-0 rounded text-muted-foreground hover:text-foreground"
          onClick={onNew}
          aria-label="Open new chat tab"
          title="New chat"
        >
          <Plus className="size-3.5" />
        </Button>
      </div>

      {/* Tab panel content */}
      <div
        role="tabpanel"
        className="min-h-0 flex-1 overflow-hidden"
      >
        {children}
      </div>
    </div>
  );
}
