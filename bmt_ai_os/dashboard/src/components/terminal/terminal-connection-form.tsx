"use client";

import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import type { ConnectionStatus } from "@/hooks/use-terminal";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type Mode = "local" | "ssh";
export type AuthMethod = "password" | "key";

export interface SshFormState {
  host: string;
  port: number;
  username: string;
  authMethod: AuthMethod;
}

interface TerminalConnectionFormProps {
  mode: Mode;
  sshState: SshFormState;
  status: ConnectionStatus;
  onModeChange: (mode: Mode) => void;
  onSshChange: (patch: Partial<SshFormState>) => void;
  onConnect: () => void;
  onDisconnect: () => void;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface ToggleGroupProps<T extends string> {
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}

function ToggleGroup<T extends string>({ options, value, onChange }: ToggleGroupProps<T>) {
  return (
    <div className="flex rounded-lg border border-border overflow-hidden text-xs font-medium">
      {options.map((opt) => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          className={`px-3 py-1.5 transition-colors ${
            value === opt.value
              ? "bg-primary text-primary-foreground"
              : "bg-background hover:bg-muted text-foreground"
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function TerminalConnectionForm({
  mode,
  sshState,
  status,
  onModeChange,
  onSshChange,
  onConnect,
  onDisconnect,
}: TerminalConnectionFormProps) {
  const isActive = status === "connected" || status === "connecting";

  return (
    <div className="flex flex-wrap items-end gap-2 border-b border-border bg-muted/30 px-3 py-2">
      <ToggleGroup
        options={[
          { value: "local" as Mode, label: "Local" },
          { value: "ssh" as Mode, label: "SSH" },
        ]}
        value={mode}
        onChange={onModeChange}
      />

      {mode === "ssh" && (
        <>
          <div className="flex items-center gap-1">
            <label className="text-xs text-muted-foreground shrink-0">Host</label>
            <Input
              className="h-7 w-36 text-xs"
              placeholder="192.168.1.1"
              value={sshState.host}
              onChange={(e) => onSshChange({ host: e.target.value })}
            />
          </div>

          <div className="flex items-center gap-1">
            <label className="text-xs text-muted-foreground shrink-0">Port</label>
            <Input
              className="h-7 w-16 text-xs"
              type="number"
              min={1}
              max={65535}
              value={sshState.port}
              onChange={(e) => onSshChange({ port: Number(e.target.value) })}
            />
          </div>

          <div className="flex items-center gap-1">
            <label className="text-xs text-muted-foreground shrink-0">User</label>
            <Input
              className="h-7 w-24 text-xs"
              placeholder="root"
              value={sshState.username}
              onChange={(e) => onSshChange({ username: e.target.value })}
            />
          </div>

          <ToggleGroup
            options={[
              { value: "password" as AuthMethod, label: "Password" },
              { value: "key" as AuthMethod, label: "Key" },
            ]}
            value={sshState.authMethod}
            onChange={(v) => onSshChange({ authMethod: v })}
          />
        </>
      )}

      {isActive ? (
        <Button size="sm" variant="destructive" onClick={onDisconnect} className="h-7 text-xs">
          Disconnect
        </Button>
      ) : (
        <Button size="sm" onClick={onConnect} className="h-7 text-xs">
          Connect
        </Button>
      )}
    </div>
  );
}
