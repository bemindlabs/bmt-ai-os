"use client";

import { useEffect, useState, useCallback } from "react";
import {
  fetchProviders,
  fetchProviderModels,
  fetchProviderKeys,
  groupModelsByProvider,
} from "@/lib/api";
import type { Provider } from "@/lib/api";
import { isCloudProvider } from "./ai-provider-selector";

export interface ProviderCatalogue {
  providers: Provider[];
  providerModels: Record<string, string[]>;
  keyedProviders: Set<string>;
  loadingProviders: boolean;
  loadingModels: boolean;
  loadingKeys: boolean;
  /** Re-fetch the provider list (models and keys auto-refresh when providers change). */
  refresh: () => void;
  /** Mark a provider as keyed after a successful key save. */
  markKeyed: (providerName: string) => void;
  /** Re-fetch models for a single provider and update the catalogue. */
  refreshModelsForProvider: (providerName: string) => Promise<string[]>;
}

export function useProviderCatalogue(): ProviderCatalogue {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [providerModels, setProviderModels] = useState<Record<string, string[]>>({});
  const [keyedProviders, setKeyedProviders] = useState<Set<string>>(new Set());
  const [loadingProviders, setLoadingProviders] = useState(false);
  const [loadingModels, setLoadingModels] = useState(false);
  const [loadingKeys, setLoadingKeys] = useState(false);

  // Fetch providers on mount
  const fetchProviderList = useCallback(() => {
    setLoadingProviders(true);
    fetchProviders()
      .then((res) => setProviders(res.providers ?? []))
      .catch(() => setProviders([]))
      .finally(() => setLoadingProviders(false));
  }, []);

  useEffect(() => {
    fetchProviderList();
  }, [fetchProviderList]);

  // Fetch models once providers load
  useEffect(() => {
    if (providers.length === 0) return;
    setLoadingModels(true);
    fetchProviderModels("all")
      .then((res) => {
        setProviderModels(groupModelsByProvider(res.models ?? [], providers));
      })
      .catch(() => setProviderModels({}))
      .finally(() => setLoadingModels(false));
  }, [providers]);

  // Fetch API key status for cloud providers once providers load
  useEffect(() => {
    if (providers.length === 0) return;
    const cloud = providers.filter((p) => isCloudProvider(p.name));
    if (cloud.length === 0) return;

    setLoadingKeys(true);
    Promise.allSettled(
      cloud.map((p) =>
        fetchProviderKeys(p.name).then((res) => ({
          name: p.name,
          hasKey: (res.keys ?? []).some((k) => k.status === "active"),
        })),
      ),
    )
      .then((results) => {
        const keyed = new Set<string>();
        for (const r of results) {
          if (r.status === "fulfilled" && r.value.hasKey) keyed.add(r.value.name);
        }
        setKeyedProviders(keyed);
      })
      .finally(() => setLoadingKeys(false));
  }, [providers]);

  const markKeyed = useCallback((name: string) => {
    setKeyedProviders((prev) => new Set([...prev, name]));
  }, []);

  const refreshModelsForProvider = useCallback(
    async (providerName: string): Promise<string[]> => {
      try {
        const res = await fetchProviderModels(providerName);
        const modelIds = (res.models ?? []).map((m) => m.id ?? m.name ?? "");
        setProviderModels((prev) => ({ ...prev, [providerName]: modelIds }));
        return modelIds;
      } catch {
        return [];
      }
    },
    [],
  );

  return {
    providers,
    providerModels,
    keyedProviders,
    loadingProviders,
    loadingModels,
    loadingKeys,
    refresh: fetchProviderList,
    markKeyed,
    refreshModelsForProvider,
  };
}
