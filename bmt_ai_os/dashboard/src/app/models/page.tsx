"use client";

import { useEffect, useState, useCallback } from "react";
import { fetchModels, fetchProviders, discoverProviders } from "@/lib/api";
import type { Provider, OllamaModel } from "@/lib/api";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { BrainCircuit, Layers, RefreshCw, KeyRound } from "lucide-react";
import { fetchProviderKeys } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ModelManagerClient } from "./model-manager-client";
import { PullModelForm } from "./pull-model-form";
import { ProviderSwitcher } from "../providers/provider-switcher";
import { ProviderKeyManager } from "../providers/provider-key-manager";
import { FallbackChain } from "@/components/fallback-chain";
import { ProviderAuthConfig } from "../providers/provider-auth-config";

const REFRESH_INTERVAL_MS = 30_000;

export default function ModelsPage() {
  const [models, setModels] = useState<OllamaModel[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [activeProvider, setActiveProvider] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [providerKeyStatus, setProviderKeyStatus] = useState<Record<string, boolean>>({});

  const loadAll = useCallback(async () => {
    try {
      await discoverProviders().catch(() => null);
      const [modelsRes, providersRes] = await Promise.all([
        fetchModels().catch(() => null),
        fetchProviders().catch(() => null),
      ]);
      if (modelsRes) setModels(modelsRes.models ?? []);
      if (providersRes) {
        const provs = providersRes.providers ?? [];
        setProviders(provs);
        setActiveProvider(providersRes.active ?? null);
        // Check key status for each provider
        const keyChecks = await Promise.allSettled(
          provs.map(async (p) => {
            try {
              const res = await fetchProviderKeys(p.name);
              return { name: p.name, hasKeys: res.keys.length > 0 };
            } catch {
              return { name: p.name, hasKeys: false };
            }
          }),
        );
        const keyMap: Record<string, boolean> = {};
        for (const r of keyChecks) {
          if (r.status === "fulfilled") keyMap[r.value.name] = r.value.hasKeys;
        }
        setProviderKeyStatus(keyMap);
      }
    } finally {
      setLoading(false);
      setLastRefresh(new Date());
    }
  }, []);

  useEffect(() => {
    loadAll();
    const id = setInterval(loadAll, REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
  }, [loadAll]);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold">Models & Providers</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Manage LLM models, inference providers, and API keys. Auto-refreshes
            every 30s.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {lastRefresh && (
            <span className="text-xs text-muted-foreground">
              {lastRefresh.toLocaleTimeString()}
            </span>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={loadAll}
            disabled={loading}
          >
            <RefreshCw
              className={cn("size-3.5 mr-1.5", loading && "animate-spin")}
            />
            Refresh
          </Button>
        </div>
      </div>

      <Tabs defaultValue="models">
        <TabsList>
          <TabsTrigger value="models">
            <BrainCircuit className="mr-1.5 size-4" />
            Models
          </TabsTrigger>
          <TabsTrigger value="providers">
            <Layers className="mr-1.5 size-4" />
            Providers
            {providers.length > 0 && (
              <Badge variant="secondary" className="ml-1.5 h-4 px-1 text-[10px]">
                {providers.length}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="auth">
            <KeyRound className="mr-1.5 size-4" />
            Auth & Keys
          </TabsTrigger>
        </TabsList>

        {/* Models tab */}
        <TabsContent value="models" className="mt-4 space-y-8">
          <ModelManagerClient liveModels={models} />
          <PullModelForm installedModels={models.map((m) => m.name)} />
        </TabsContent>

        {/* Providers tab */}
        <TabsContent value="providers" className="mt-4 space-y-6">
          {loading && providers.length === 0 && (
            <Card>
              <CardContent className="pt-4">
                <p className="text-sm text-muted-foreground">
                  Loading providers...
                </p>
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
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Fallback Chain</CardTitle>
                <CardDescription>
                  Drag to reorder provider priority for automatic failover.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <FallbackChain providers={providers} />
              </CardContent>
            </Card>
          )}

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {providers.map((p) => {
              const isActive = activeProvider
                ? p.name === activeProvider
                : !!p.active;
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
                      {p.healthy ? "Responding normally" : "Not responding"}
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
        </TabsContent>
        {/* Auth & Keys tab */}
        <TabsContent value="auth" className="mt-4 space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Provider Authentication</CardTitle>
              <CardDescription>
                Configure API keys for cloud providers. Local providers (Ollama, vLLM, llama.cpp)
                don&apos;t require authentication.
              </CardDescription>
            </CardHeader>
          </Card>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {providers.map((p) => (
              <ProviderAuthConfig
                key={p.name}
                providerName={p.name}
                healthy={p.healthy}
                hasKeys={providerKeyStatus[p.name] ?? false}
                onKeyAdded={() => void loadAll()}
              />
            ))}
          </div>

          {providers.length === 0 && !loading && (
            <Card>
              <CardContent className="pt-4">
                <p className="text-sm text-muted-foreground">
                  No providers registered. Check that the controller is running.
                </p>
              </CardContent>
            </Card>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
