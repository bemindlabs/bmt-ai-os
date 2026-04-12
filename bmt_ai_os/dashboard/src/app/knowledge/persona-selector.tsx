"use client";

import { useState, useEffect, useCallback } from "react";
import { Bot, RefreshCw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  fetchAgents,
  activatePersona,
  fetchActivePersona,
  type AgentPreset,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STORAGE_KEY = "bmt_active_persona";

// ---------------------------------------------------------------------------
// Hook: useActivePersona
// Manages the active persona selection with localStorage persistence.
// ---------------------------------------------------------------------------

export function useActivePersona(): {
  activePersona: string | null;
  workspacePath: string | null;
  setPersona: (name: string | null, workspacePath?: string | null) => void;
} {
  const [activePersona, setActivePersonaState] = useState<string | null>(null);
  const [workspacePath, setWorkspacePath] = useState<string | null>(null);

  useEffect(() => {
    // Restore from localStorage on mount
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored) as {
          name: string;
          workspace_path: string | null;
        };
        setActivePersonaState(parsed.name ?? null);
        setWorkspacePath(parsed.workspace_path ?? null);
      }
    } catch {
      // Ignore malformed storage
    }

    // Also try to fetch the server-side active persona
    fetchActivePersona()
      .then((res) => {
        if (res.active) {
          setActivePersonaState(res.active);
          setWorkspacePath(res.workspace_path ?? null);
          localStorage.setItem(
            STORAGE_KEY,
            JSON.stringify({
              name: res.active,
              workspace_path: res.workspace_path,
            }),
          );
        }
      })
      .catch(() => {
        // Server may not have persona/active endpoint — localStorage value stands
      });
  }, []);

  function setPersona(
    name: string | null,
    newWorkspacePath: string | null = null,
  ) {
    setActivePersonaState(name);
    setWorkspacePath(newWorkspacePath);
    if (name) {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ name, workspace_path: newWorkspacePath }),
      );
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  }

  return { activePersona, workspacePath, setPersona };
}

// ---------------------------------------------------------------------------
// Component: PersonaSelector
// ---------------------------------------------------------------------------

interface PersonaSelectorProps {
  activePersona: string | null;
  onPersonaChange: (name: string | null, workspacePath: string | null) => void;
}

export function PersonaSelector({
  activePersona,
  onPersonaChange,
}: PersonaSelectorProps) {
  const [presets, setPresets] = useState<AgentPreset[]>([]);
  const [loading, setLoading] = useState(true);
  const [activating, setActivating] = useState<string | null>(null);

  const loadPresets = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetchAgents();
      setPresets(res.presets);
    } catch {
      // fetchAgents already provides a fallback list, so this rarely fires
      setPresets([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadPresets();
  }, [loadPresets]);

  async function handleSelect(name: string) {
    if (activating) return;

    // Deselect if already active
    if (activePersona === name) {
      onPersonaChange(null, null);
      return;
    }

    setActivating(name);
    try {
      const res = await activatePersona(name);
      onPersonaChange(res.active, res.workspace_path ?? null);
    } catch {
      // Best-effort: activate locally even if the API is unavailable.
      // The workspace path will remain null and tabs will degrade gracefully.
      onPersonaChange(name, null);
    } finally {
      setActivating(null);
    }
  }

  function handleClear() {
    onPersonaChange(null, null);
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
        <Bot className="size-4 shrink-0" />
        <span className="font-medium text-foreground">Persona</span>
      </div>

      {loading ? (
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <RefreshCw className="size-3 animate-spin" />
          Loading…
        </div>
      ) : (
        <div
          role="group"
          aria-label="Select active persona"
          className="flex flex-wrap gap-1.5"
        >
          {presets.map((preset) => {
            const isActive = activePersona === preset.name;
            const isSpinning = activating === preset.name;
            return (
              <button
                key={preset.name}
                type="button"
                onClick={() => void handleSelect(preset.name)}
                disabled={!!activating}
                aria-pressed={isActive}
                title={preset.description}
                className={cn(
                  "inline-flex h-7 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50",
                  isActive
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-border bg-background text-foreground hover:bg-muted",
                )}
              >
                {isSpinning && (
                  <RefreshCw className="size-3 animate-spin" aria-hidden />
                )}
                <span className="capitalize">{preset.name}</span>
              </button>
            );
          })}
        </div>
      )}

      {activePersona && !activating && (
        <button
          type="button"
          onClick={handleClear}
          aria-label="Clear active persona"
          className="inline-flex h-5 w-5 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
        >
          <X className="size-3" aria-hidden />
        </button>
      )}

      {activePersona && (
        <Badge variant="secondary" className="capitalize">
          {activePersona} active
        </Badge>
      )}
    </div>
  );
}

// Export the storage key so consuming components can reference it
export { STORAGE_KEY as PERSONA_STORAGE_KEY };
