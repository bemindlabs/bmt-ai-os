"use client";

import type { ConnectionStatus as ConnectionStatusType } from "@/hooks/use-terminal";

const STATUS_CLASSES: Record<ConnectionStatusType, string> = {
  disconnected: "bg-zinc-500",
  connecting: "bg-yellow-400 animate-pulse",
  connected: "bg-green-400",
  error: "bg-red-500",
};

const STATUS_LABELS: Record<ConnectionStatusType, string> = {
  disconnected: "Disconnected",
  connecting: "Connecting...",
  connected: "Connected",
  error: "Error",
};

interface ConnectionStatusProps {
  status: ConnectionStatusType;
}

export function ConnectionStatus({ status }: ConnectionStatusProps) {
  return (
    <div className="ml-auto flex items-center gap-1.5">
      <span
        className={`size-2 rounded-full ${STATUS_CLASSES[status]}`}
        aria-hidden="true"
      />
      <span className="text-xs text-muted-foreground">{STATUS_LABELS[status]}</span>
    </div>
  );
}
