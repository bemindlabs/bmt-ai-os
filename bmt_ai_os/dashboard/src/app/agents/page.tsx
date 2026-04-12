"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
  CardFooter,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { BrainCog, Folder, ExternalLink } from "lucide-react";
import {
  fetchAgents,
  fetchActivePersona,
  activatePersona,
  type AgentPreset,
} from "@/lib/api";

const STORAGE_KEY = "bmt_active_agent";

interface AgentCardProps {
  agent: AgentPreset;
  isActive: boolean;
  workspacePath: string | null;
  onActivate: (name: string) => void;
  activating: boolean;
}

function AgentCard({
  agent,
  isActive,
  workspacePath,
  onActivate,
  activating,
}: AgentCardProps) {
  // Show up to 4 lines of the SOUL.md / description content
  const preview = agent.content
    ? agent.content
        .split("\n")
        .filter((l) => l.trim().length > 0)
        .slice(0, 4)
        .join("\n")
    : agent.description;

  return (
    <Card
      className={
        isActive
          ? "ring-2 ring-primary bg-primary/5"
          : undefined
      }
    >
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2">
            <BrainCog className="size-4 text-muted-foreground shrink-0 mt-0.5" />
            <CardTitle className="capitalize">{agent.name}</CardTitle>
          </div>
          {isActive && (
            <Badge variant="default" className="shrink-0">
              Active
            </Badge>
          )}
        </div>
        <CardDescription className="line-clamp-2 mt-1">
          {agent.description}
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-3">
        {/* SOUL.md preview */}
        {preview && (
          <pre className="rounded-md bg-muted p-3 text-xs text-muted-foreground whitespace-pre-wrap line-clamp-4 font-mono leading-relaxed">
            {preview}
          </pre>
        )}

        {/* Workspace path */}
        {workspacePath && isActive && (
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Folder className="size-3 shrink-0" />
            <span className="truncate font-mono">{workspacePath}</span>
          </div>
        )}
      </CardContent>

      <CardFooter className="flex items-center justify-between gap-2">
        <Button
          size="sm"
          variant={isActive ? "secondary" : "outline"}
          disabled={isActive || activating}
          onClick={() => onActivate(agent.name)}
        >
          {isActive ? "Active" : activating ? "Activating…" : "Activate"}
        </Button>

        <Link
          href="/knowledge"
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          <ExternalLink className="size-3" />
          Knowledge vault
        </Link>
      </CardFooter>
    </Card>
  );
}

export default function AgentsPage() {
  const [agents, setAgents] = useState<AgentPreset[]>([]);
  const [activePersona, setActivePersona] = useState<string | null>(null);
  const [workspacePath, setWorkspacePath] = useState<string | null>(null);
  const [activating, setActivating] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [agentsResult, activeResult] = await Promise.allSettled([
        fetchAgents(),
        fetchActivePersona(),
      ]);

      if (agentsResult.status === "fulfilled") {
        setAgents(agentsResult.value.presets ?? []);
      }

      if (activeResult.status === "fulfilled") {
        setActivePersona(activeResult.value.active ?? null);
        setWorkspacePath(activeResult.value.workspace_path ?? null);
      } else {
        // Fall back to localStorage value set by legacy agent-switcher
        const stored = localStorage.getItem(STORAGE_KEY);
        if (stored) setActivePersona(stored);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load agents");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Keep in sync when another tab changes the stored agent
  useEffect(() => {
    function onStorage(e: StorageEvent) {
      if (e.key === STORAGE_KEY && e.newValue) {
        setActivePersona(e.newValue);
      }
    }
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  async function handleActivate(name: string) {
    setActivating(name);
    try {
      const result = await activatePersona(name);
      setActivePersona(result.active);
      setWorkspacePath(result.workspace_path ?? null);
      // Sync to localStorage for legacy components
      localStorage.setItem(STORAGE_KEY, result.active);
      window.dispatchEvent(
        new StorageEvent("storage", {
          key: STORAGE_KEY,
          newValue: result.active,
          storageArea: localStorage,
        }),
      );
    } catch {
      // If API fails, apply locally so UI still responds
      setActivePersona(name);
      localStorage.setItem(STORAGE_KEY, name);
    } finally {
      setActivating(null);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold">Agents</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Manage agent personas. The active agent sets the system prompt and
          default model for new chat sessions.
        </p>
      </div>

      {error && (
        <p className="text-sm text-destructive">{error}</p>
      )}

      {loading && agents.length === 0 && (
        <p className="text-sm text-muted-foreground">Loading agents…</p>
      )}

      {!loading && agents.length === 0 && (
        <Card>
          <CardContent className="pt-4">
            <p className="text-sm text-muted-foreground">
              No agents found. Ensure the controller API is reachable.
            </p>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {agents.map((agent) => (
          <AgentCard
            key={agent.name}
            agent={agent}
            isActive={activePersona === agent.name}
            workspacePath={activePersona === agent.name ? workspacePath : null}
            onActivate={handleActivate}
            activating={activating === agent.name}
          />
        ))}
      </div>
    </div>
  );
}
