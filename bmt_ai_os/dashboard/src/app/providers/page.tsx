"use client";

import { useEffect, useState, useCallback } from "react";
import { fetchProviders, discoverProviders } from "@/lib/api";
import type { Provider } from "@/lib/api";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ProviderSwitcher } from "./provider-switcher";
import { ProviderKeyManager } from "./provider-key-manager";
import { FallbackChain } from "@/components/fallback-chain";

// ---------------------------------------------------------------------------
// Latency colour helpers
// ---------------------------------------------------------------------------

function latencyColor(ms: number): string {
  if (ms < 100) return "bg-green-500";
  if (ms <= 500) return "bg-yellow-400";
  return "bg-red-500";
}

function latencyLabel(ms: number): string {
  if (ms < 100) return "text-green-600 dark:text-green-400";
  if (ms <= 500) return "text-yellow-600 dark:text-yellow-400";
  return "text-red-600 dark:text-red-400";
}

function healthBadgeVariant(healthy: boolean, latency_ms?: number): "default" | "destructive" | "secondary" {
  if (!healthy) return "destructive";
  if (latency_ms !== undefined && latency_ms > 500) return "destructive";
  if (latency_ms !== undefined && latency_ms > 100) return "secondary";
  return "default";
}

// ---------------------------------------------------------------------------
// Sparkline — CSS-only dots representing last 5 latency readings
// ---------------------------------------------------------------------------

function Sparkline({ history }: { history: number[] }) {
  if (!history || history.length === 0) return null;
  const max = Math.max(...history, 1);
  return (
    <div className="flex items-end gap-0.5 h-5" aria-label="Latency trend">
      {history.map((ms, i) => {
        const heightPct = Math.max(10, Math.round((ms / max) * 100));
        return (
          <span
            key={i}
            title={`${Math.round(ms)}ms`}
            className={`inline-block w-1.5 rounded-sm ${latencyColor(ms)}`}
            style={{ height: `${heightPct}%` }}
          />
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Credential freshness helper
// ---------------------------------------------------------------------------

function formatLastSuccess(ts: number | null | undefined): string {
  if (!ts) return "Never";
  const diff = Math.floor(Date.now() / 1000 - ts);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

// ---------------------------------------------------------------------------
// Provider card
// ---------------------------------------------------------------------------

function ProviderCard({
  p,
  isActive,
}: {
  p: Provider;
  isActive: boolean;
}) {
  const latency = p.latency_ms ?? 0;
  const history = p.latency_history ?? [];
  const errCount = p.error_count ?? 0;
  const cooldown = p.cooldown_remaining_s ?? 0;
  const hasCooldown = cooldown > 0;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="capitalize">{p.name}</CardTitle>
          <div className="flex flex-wrap items-end gap-1 justify-end">
            <Badge variant={healthBadgeVariant(p.healthy, latency)}>
              {p.healthy ? "healthy" : "unhealthy"}
            </Badge>
            {isActive && <Badge variant="secondary">active</Badge>}
            {p.discovered && (
              <Badge variant="outline" className="text-xs border-blue-400 text-blue-600 dark:text-blue-400">
                discovered
              </Badge>
            )}
          </div>
        </div>
        <CardDescription>
          {p.healthy ? (
            <span className={latencyLabel(latency)}>
              {Math.round(latency)}ms
            </span>
          ) : (
            "Not responding"
          )}
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-3">
        {/* Sparkline */}
        {history.length > 0 && (
          <div className="space-y-0.5">
            <p className="text-xs text-muted-foreground">Latency trend (last {history.length})</p>
            <Sparkline history={history} />
          </div>
        )}

        {/* Error count + cooldown */}
        {errCount > 0 && (
          <div className="flex items-center gap-2 text-xs">
            <span className="text-destructive font-medium">
              {errCount} error{errCount !== 1 ? "s" : ""}
            </span>
            {hasCooldown && (
              <span className="text-muted-foreground">
                · cooldown {Math.round(cooldown)}s
              </span>
            )}
          </div>
        )}

        {/* Credential freshness */}
        <p className="text-xs text-muted-foreground">
          Last success: {formatLastSuccess(p.last_success_ts)}
        </p>

        <ProviderSwitcher providerName={p.name} isActive={isActive} />
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

const REFRESH_INTERVAL_MS = 30_000;

export default function ProvidersPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [activeProvider, setActiveProvider] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const load = useCallback(async () => {
    try {
      // Trigger discovery (registers new providers) then fetch full list
      await discoverProviders().catch(() => null);
      const result = await fetchProviders().catch(() => null);
      if (result) {
        setProviders(result.providers ?? []);
        setActiveProvider(result.active ?? null);
      }
    } finally {
      setLoading(false);
      setLastRefresh(new Date());
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
  }, [load]);

  return (
    <div className="space-y-8">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold">Providers</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Manage and switch between LLM inference providers. Auto-refreshes every 30s.
          </p>
        </div>
        {lastRefresh && (
          <p className="text-xs text-muted-foreground pt-1 shrink-0">
            Updated {lastRefresh.toLocaleTimeString()}
          </p>
        )}
      </div>

      {loading && providers.length === 0 && (
        <Card>
          <CardContent className="pt-4">
            <p className="text-sm text-muted-foreground">Loading providers…</p>
          </CardContent>
        </Card>
      )}

      {!loading && providers.length === 0 && (
        <Card>
          <CardContent className="pt-4">
            <p className="text-sm text-muted-foreground">
              No providers found. Ensure the controller API is reachable.
            </p>
          </CardContent>
        </Card>
      )}

      {providers.length > 0 && (
        <Card>
          <CardContent className="pt-4">
            <FallbackChain providers={providers} />
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {providers.map((p) => {
          const isActive = activeProvider ? p.name === activeProvider : !!p.active;
          return (
            <Card key={p.name}>
              <CardHeader>
                <div className="flex items-start justify-between gap-2">
                  <CardTitle className="capitalize">{p.name}</CardTitle>
                  <div className="flex flex-col items-end gap-1">
                    <Badge
                      variant={p.healthy ? "default" : "destructive"}
                    >
                      {p.healthy ? "healthy" : "unhealthy"}
                    </Badge>
                    {isActive && (
                      <Badge variant="secondary">active</Badge>
                    )}
                  </div>
                </div>
                <CardDescription>
                  {p.healthy
                    ? "Responding normally"
                    : "Not responding"}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ProviderSwitcher
                  providerName={p.name}
                  isActive={isActive}
                />
                <ProviderKeyManager providerName={p.name} />
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
