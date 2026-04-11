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
